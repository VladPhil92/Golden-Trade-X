#!/usr/bin/env python3
"""
Golden Trade X — Static lint for MQL5 sources (v2.50).

Catches the exact MQL4-isms and API misuses that break MetaEditor compilation
but that a structure-only CI cannot see. This is NOT a compiler — it is a
regression guard for the error classes that already bit this project once
(77 compilation errors in v2.30):

  1. MQL4-style indicator calls: iATR/iRSI/iADX/iMA/iBands with the wrong
     argument count (MQL5 versions return a handle and take fewer/different args).
  2. '->' member access (MQL5 uses '.' even on object pointers; '->' parses
     as minus + greater-than under #property strict).
  3. ArraySetAsSeries() on statically-sized arrays (compile error in MQL5).
  4. CTrade::ResultRetcodeDescription() — method does not exist in the
     standard library (use ResultComment()).

Usage:
    python scripts/mql5_lint.py                 # lints MQL5/ recursively
    python scripts/mql5_lint.py path1 path2 ...
Exit code 0 = clean, 1 = findings.
"""

import re
import sys
from pathlib import Path

# MQL5 argument counts for the indicator functions this codebase uses.
# iMA(symbol,tf,period,shift,method,price)=6, iATR(symbol,tf,period)=3, etc.
INDICATOR_ARGS = {
    "iATR":    3,
    "iRSI":    4,
    "iADX":    3,
    "iMA":     6,
    "iBands":  6,
    "iStdDev": 6,
}

_ARR_TYPES = (
    r"(?:double|float|int|uint|long|ulong|short|ushort|char|uchar|bool|datetime|color|string)"
)
STATIC_ARRAY_DECL = re.compile(r"\b" + _ARR_TYPES + r"\s+(\w+)\s*\[\s*\d+\s*\]")
DYNAMIC_ARRAY_DECL = re.compile(r"\b" + _ARR_TYPES + r"\s+(\w+)\s*\[\s*\]")


def strip_comments_and_strings(text: str) -> str:
    """Replace comments and string literals with spaces, preserving offsets/newlines."""
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


def count_call_args(code: str, open_paren: int) -> int:
    """Count top-level comma-separated args of the call starting at '('."""
    depth, args, has_content = 0, 0, False
    i = open_paren
    while i < len(code):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return (args + 1) if has_content else 0
        elif depth == 1 and c == ",":
            args += 1
        elif depth >= 1 and not c.isspace():
            has_content = True
        i += 1
    return -1  # unbalanced — let the compiler complain


def lint_file(path: Path):
    findings = []
    raw = path.read_text(encoding="utf-8", errors="replace")
    code = strip_comments_and_strings(raw)

    def lines_upto(pos: int) -> int:
        return code.count("\n", 0, pos) + 1

    # 1. Indicator calls with MQL4 argument counts
    for name, expected in INDICATOR_ARGS.items():
        for m in re.finditer(r"\b" + name + r"\s*\(", code):
            got = count_call_args(code, m.end() - 1)
            if got >= 0 and got != expected:
                findings.append((
                    lines_upto(m.start()),
                    f"{name}() con {got} argumentos — MQL5 requiere {expected} "
                    f"(devuelve handle; usar CopyBuffer para leer valores)",
                ))

    # 2. '->' member access
    for m in re.finditer(r"\w\s*->\s*\w", code):
        findings.append((
            lines_upto(m.start()),
            "operador '->' — MQL5 usa '.' incluso sobre punteros a objetos",
        ))

    # 3. ArraySetAsSeries on statically-sized arrays.
    # Heurística a nivel de archivo: si el mismo nombre también está declarado
    # como array dinámico en otro scope del archivo, es ambiguo → no flaggear.
    static_arrays = set(STATIC_ARRAY_DECL.findall(code)) - set(DYNAMIC_ARRAY_DECL.findall(code))
    for m in re.finditer(r"\bArraySetAsSeries\s*\(\s*(\w+)", code):
        if m.group(1) in static_arrays:
            findings.append((
                lines_upto(m.start()),
                f"ArraySetAsSeries('{m.group(1)}') sobre array de tamaño estático "
                f"— declarar como array dinámico ('tipo nombre[]')",
            ))

    # 4. Non-existent CTrade method
    for m in re.finditer(r"\bResultRetcodeDescription\s*\(", code):
        findings.append((
            lines_upto(m.start()),
            "ResultRetcodeDescription() no existe en CTrade — usar ResultComment()",
        ))

    return findings


def main() -> None:
    targets = [Path(p) for p in sys.argv[1:]] or [Path("MQL5")]
    files = []
    for t in targets:
        if t.is_dir():
            files += sorted(t.rglob("*.mq5")) + sorted(t.rglob("*.mqh"))
        elif t.is_file():
            files.append(t)
        else:
            print(f"ERROR: no existe {t}")
            sys.exit(1)

    total = 0
    for f in files:
        for line, msg in lint_file(f):
            print(f"{f}:{line}: {msg}")
            total += 1

    if total:
        print(f"\nFAIL — {total} problema(s) MQL5 detectado(s) en {len(files)} archivo(s)")
        sys.exit(1)
    print(f"OK — {len(files)} archivo(s) MQL5 sin MQL4-ismos conocidos")


if __name__ == "__main__":
    main()
