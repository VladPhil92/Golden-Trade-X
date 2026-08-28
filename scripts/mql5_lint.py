#!/usr/bin/env python3
"""
Golden Trade X — conservative static lint for MQL5 sources.

This does not replace MetaEditor. It catches known high-value error classes
that can be detected safely on Linux CI:

  1. MQL4-style indicator calls with invalid MQL5 argument counts.
  2. '->' member access (MQL5 uses '.').
  3. ArraySetAsSeries() on statically-sized arrays.
  4. Non-existent CTrade::ResultRetcodeDescription().
  5. Direct CTrade entry calls with literal zero Stop Loss.
  6. Literal GlobalVariable names outside the GTX_ namespace.

Usage:
    python scripts/mql5_lint.py                 # lints MQL5/ recursively
    python scripts/mql5_lint.py path1 path2 ...
Exit code 0 = clean, 1 = findings.
"""

import re
import sys
from pathlib import Path

INDICATOR_ARGS = {
    "iATR": 3,
    "iRSI": 4,
    "iADX": 3,
    "iMA": 6,
    "iBands": 6,
    "iStdDev": 6,
}

_ARR_TYPES = (
    r"(?:double|float|int|uint|long|ulong|short|ushort|char|uchar|bool|datetime|color|string)"
)
STATIC_ARRAY_DECL = re.compile(r"\b" + _ARR_TYPES + r"\s+(\w+)\s*\[\s*\d+\s*\]")
DYNAMIC_ARRAY_DECL = re.compile(r"\b" + _ARR_TYPES + r"\s+(\w+)\s*\[\s*\]")
ZERO_LITERAL = re.compile(r"^[+]?0(?:\.0*)?(?:[eE][+-]?\d+)?$")


def strip_comments_and_strings(text: str) -> str:
    """Replace comments and string contents with spaces, preserving offsets/newlines."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append('"' + " " * (j - i - 2) + '"' if j - i >= 2 else '"')
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_call_args(code: str, open_paren: int) -> list[str] | None:
    """Return top-level arguments for a function call, or None if unbalanced."""
    depth = 0
    start = open_paren + 1
    args: list[str] = []
    i = open_paren
    while i < len(code):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                tail = code[start:i].strip()
                if tail or args:
                    args.append(tail)
                return args
        elif depth == 1 and c == ",":
            args.append(code[start:i].strip())
            start = i + 1
        i += 1
    return None


def count_call_args(code: str, open_paren: int) -> int:
    args = split_call_args(code, open_paren)
    return -1 if args is None else len(args)


def _is_zero_literal(expr: str) -> bool:
    return bool(ZERO_LITERAL.fullmatch(expr.strip()))


def lint_file(path: Path):
    findings = []
    raw = path.read_text(encoding="utf-8", errors="replace")
    code = strip_comments_and_strings(raw)

    def lines_upto(pos: int) -> int:
        return code.count("\n", 0, pos) + 1

    # 1. Indicator calls with MQL4 argument counts.
    for name, expected in INDICATOR_ARGS.items():
        for match in re.finditer(r"\b" + name + r"\s*\(", code):
            got = count_call_args(code, match.end() - 1)
            if got >= 0 and got != expected:
                findings.append((
                    lines_upto(match.start()),
                    f"{name}() con {got} argumentos — MQL5 requiere {expected} "
                    f"(devuelve handle; usar CopyBuffer para leer valores)",
                ))

    # 2. '->' member access.
    for match in re.finditer(r"\w\s*->\s*\w", code):
        findings.append((
            lines_upto(match.start()),
            "operador '->' — MQL5 usa '.' incluso sobre punteros a objetos",
        ))

    # 3. ArraySetAsSeries on statically-sized arrays.
    static_arrays = set(STATIC_ARRAY_DECL.findall(code)) - set(DYNAMIC_ARRAY_DECL.findall(code))
    for match in re.finditer(r"\bArraySetAsSeries\s*\(\s*(\w+)", code):
        if match.group(1) in static_arrays:
            findings.append((
                lines_upto(match.start()),
                f"ArraySetAsSeries('{match.group(1)}') sobre array de tamaño estático "
                f"— declarar como array dinámico ('tipo nombre[]')",
            ))

    # 4. Non-existent CTrade method.
    for match in re.finditer(r"\bResultRetcodeDescription\s*\(", code):
        findings.append((
            lines_upto(match.start()),
            "ResultRetcodeDescription() no existe en CTrade — usar ResultComment()",
        ))

    # 5. Direct CTrade entries with a literal zero SL. Dynamic expressions are
    # intentionally not guessed here; MetaEditor/runtime guards cover those.
    # PositionOpen(symbol,type,volume,price,sl,tp,comment)
    for match in re.finditer(r"\bPositionOpen\s*\(", code):
        args = split_call_args(code, match.end() - 1)
        if args is not None and len(args) >= 6 and _is_zero_literal(args[4]):
            findings.append((
                lines_upto(match.start()),
                "PositionOpen() con SL literal 0 — ninguna entrada Golden Trade X debe enviarse sin SL",
            ))

    # Buy/Sell(volume,symbol,price,sl,tp,comment)
    for name in ("Buy", "Sell"):
        for match in re.finditer(r"\b" + name + r"\s*\(", code):
            args = split_call_args(code, match.end() - 1)
            if args is not None and len(args) >= 5 and _is_zero_literal(args[3]):
                findings.append((
                    lines_upto(match.start()),
                    f"{name}() con SL literal 0 — usar OrderManager con Stop Loss válido",
                ))

    # 6. Literal terminal GlobalVariables must use the GTX_ namespace to avoid
    # collisions with unrelated EAs. Dynamic StringFormat names are not flagged.
    for match in re.finditer(
        r"\bGlobalVariable(?:Set|Get|Del|Check)\s*\(\s*\"([^\"]+)\"",
        raw,
    ):
        name = match.group(1)
        if not name.startswith("GTX_"):
            findings.append((
                raw.count("\n", 0, match.start()) + 1,
                f"GlobalVariable literal '{name}' fuera del namespace GTX_",
            ))

    return findings


def main() -> None:
    targets = [Path(p) for p in sys.argv[1:]] or [Path("MQL5")]
    files = []
    for target in targets:
        if target.is_dir():
            files += sorted(target.rglob("*.mq5")) + sorted(target.rglob("*.mqh"))
        elif target.is_file():
            files.append(target)
        else:
            print(f"ERROR: no existe {target}")
            sys.exit(1)

    total = 0
    for file_path in files:
        for line, msg in lint_file(file_path):
            print(f"{file_path}:{line}: {msg}")
            total += 1

    if total:
        print(f"\nFAIL — {total} problema(s) MQL5 detectado(s) en {len(files)} archivo(s)")
        sys.exit(1)
    print(f"OK — {len(files)} archivo(s) MQL5 sin patrones estáticos críticos conocidos")


if __name__ == "__main__":
    main()
