#!/usr/bin/env python3
"""Parse MetaTrader 5 Strategy Tester HTML reports into auditable metrics.

The parser is intentionally fail-closed for the research metrics Golden Trade X
uses as minimum evidence. A report is not accepted merely because it exists: the
required metrics must be located in the original report and every normalized
value keeps its source label and raw text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

PARSER_SCHEMA_VERSION = 1
PARSER_VERSION = "2.90.1"

REQUIRED_SUMMARY_METRICS = (
    "total_net_profit",
    "profit_factor",
    "expected_payoff",
    "max_drawdown_pct",
    "total_trades",
)

# Canonical metric -> labels observed in English/Spanish MT5 reports.
LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "initial_deposit": ("initial deposit", "deposito inicial", "depósito inicial"),
    "history_quality": ("history quality", "calidad del historial"),
    "bars": ("bars", "barras"),
    "ticks": ("ticks",),
    "total_net_profit": (
        "total net profit",
        "beneficio neto total",
        "ganancia neta total",
    ),
    "gross_profit": ("gross profit", "beneficio bruto", "ganancia bruta"),
    "gross_loss": ("gross loss", "perdida bruta", "pérdida bruta"),
    "profit_factor": ("profit factor", "factor de beneficio"),
    "expected_payoff": (
        "expected payoff",
        "expected payoff ",
        "beneficio esperado",
        "pago esperado",
    ),
    "recovery_factor": ("recovery factor", "factor de recuperacion", "factor de recuperación"),
    "sharpe_ratio": ("sharpe ratio", "ratio de sharpe"),
    "balance_drawdown_absolute": (
        "balance drawdown absolute",
        "reduccion absoluta del balance",
        "reducción absoluta del balance",
    ),
    "balance_drawdown_maximal": (
        "balance drawdown maximal",
        "reduccion maxima del balance",
        "reducción máxima del balance",
    ),
    "balance_drawdown_relative": (
        "balance drawdown relative",
        "reduccion relativa del balance",
        "reducción relativa del balance",
    ),
    "equity_drawdown_absolute": (
        "equity drawdown absolute",
        "reduccion absoluta del capital",
        "reducción absoluta del capital",
    ),
    "equity_drawdown_maximal": (
        "equity drawdown maximal",
        "reduccion maxima del capital",
        "reducción máxima del capital",
    ),
    "equity_drawdown_relative": (
        "equity drawdown relative",
        "reduccion relativa del capital",
        "reducción relativa del capital",
    ),
    "total_trades": ("total trades", "operaciones totales"),
    "profit_trades": (
        "profit trades (% of total)",
        "operaciones con beneficio (% del total)",
        "operaciones ganadoras (% del total)",
    ),
    "loss_trades": (
        "loss trades (% of total)",
        "operaciones con perdida (% del total)",
        "operaciones con pérdidas (% del total)",
        "operaciones perdedoras (% del total)",
    ),
    "largest_profit_trade": (
        "largest profit trade",
        "mayor operacion ganadora",
        "mayor operación ganadora",
    ),
    "largest_loss_trade": (
        "largest loss trade",
        "mayor operacion perdedora",
        "mayor operación perdedora",
    ),
    "average_profit_trade": (
        "average profit trade",
        "promedio operacion ganadora",
        "promedio operación ganadora",
    ),
    "average_loss_trade": (
        "average loss trade",
        "promedio operacion perdedora",
        "promedio operación perdedora",
    ),
    "maximum_consecutive_wins": (
        "maximum consecutive wins ($)",
        "maximos beneficios consecutivos ($)",
        "máximos beneficios consecutivos ($)",
    ),
    "maximum_consecutive_losses": (
        "maximum consecutive losses ($)",
        "maximas perdidas consecutivas ($)",
        "máximas pérdidas consecutivas ($)",
    ),
}

ALIAS_TO_METRIC = {
    alias.casefold().strip().rstrip(":"): metric
    for metric, aliases in LABEL_ALIASES.items()
    for alias in aliases
}

INTEGER_METRICS = {"bars", "ticks", "total_trades"}
PERCENT_ONLY_METRICS = {"history_quality", "balance_drawdown_relative", "equity_drawdown_relative"}
COUNT_PERCENT_METRICS = {"profit_trades", "loss_trades"}


class StrategyTesterResultError(ValueError):
    """Raised when a tester report cannot be accepted as research evidence."""


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._cell_parts is not None and self._row is not None:
            text = " ".join("".join(self._cell_parts).replace("\xa0", " ").split())
            self._row.append(text)
            self._cell_parts = None
        elif lowered == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None
            self._cell_parts = None


def _read_report_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    if not raw:
        raise StrategyTesterResultError(f"empty Strategy Tester report: {path}")

    encodings: list[str]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16", "utf-8-sig", "cp1252"]
    else:
        encodings = ["utf-8-sig", "utf-16", "cp1252"]

    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "<" in text and ">" in text:
            return text, encoding
    raise StrategyTesterResultError("unable to decode Strategy Tester report as HTML text")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _label_key(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()).casefold().strip().rstrip(":")


def _first_number_token(raw: str) -> str:
    match = re.search(r"[-+]?\d(?:[\d\s.,]*\d)?", raw.replace("\xa0", " "))
    if not match:
        raise StrategyTesterResultError(f"numeric value not found in {raw!r}")
    return match.group(0).strip()


def _parse_number(raw: str) -> float:
    token = _first_number_token(raw).replace(" ", "")
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        if token.count(",") == 1:
            left, right = token.split(",")
            token = left + right if len(right) == 3 and len(left.lstrip("+-")) <= 3 else left + "." + right
        else:
            token = token.replace(",", "")
    elif token.count(".") > 1:
        pieces = token.split(".")
        token = "".join(pieces[:-1]) + "." + pieces[-1]

    try:
        value = float(token)
    except ValueError as exc:
        raise StrategyTesterResultError(f"invalid numeric value: {raw!r}") from exc
    if not math.isfinite(value):
        raise StrategyTesterResultError(f"non-finite numeric value: {raw!r}")
    return value


def _parse_percent(raw: str) -> float:
    matches = re.findall(r"([-+]?\d(?:[\d\s.,]*\d)?)\s*%", raw.replace("\xa0", " "))
    if not matches:
        raise StrategyTesterResultError(f"percentage not found in {raw!r}")
    return _parse_number(matches[-1])


def _extract_pairs(rows: list[list[str]]) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for row in rows:
        for index, cell in enumerate(row):
            metric = ALIAS_TO_METRIC.get(_label_key(cell))
            if metric is None or metric in found:
                continue
            value = ""
            for candidate in row[index + 1 :]:
                if candidate:
                    value = candidate
                    break
            if value:
                found[metric] = (cell.rstrip(":"), value)
    return found


def _metric_entry(metric: str, label: str, raw: str) -> dict[str, Any]:
    if metric in INTEGER_METRICS:
        value: Any = int(round(_parse_number(raw)))
        unit = "count"
    elif metric in PERCENT_ONLY_METRICS:
        value = _parse_percent(raw)
        unit = "percent"
    elif metric in COUNT_PERCENT_METRICS:
        value = {
            "count": int(round(_parse_number(raw))),
            "percent": _parse_percent(raw),
        }
        unit = "count_percent"
    else:
        value = _parse_number(raw)
        unit = "ratio" if metric in {"profit_factor", "recovery_factor", "sharpe_ratio"} else "currency"
    return {
        "value": value,
        "unit": unit,
        "source_label": label,
        "raw_value": raw,
    }


def parse_strategy_tester_report(
    report_path: str | Path,
    *,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    path = Path(report_path)
    if not path.is_file():
        raise StrategyTesterResultError(f"Strategy Tester report not found: {path}")

    text, encoding = _read_report_text(path)
    parser = _TableParser()
    parser.feed(text)
    if not parser.rows:
        raise StrategyTesterResultError("Strategy Tester report contains no parseable table rows")

    pairs = _extract_pairs(parser.rows)
    metrics: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for metric, (label, raw) in pairs.items():
        try:
            metrics[metric] = _metric_entry(metric, label, raw)
        except StrategyTesterResultError as exc:
            warnings.append(f"{metric}: {exc}")

    drawdown_source = None
    for candidate in ("equity_drawdown_relative", "balance_drawdown_relative"):
        if candidate in metrics:
            drawdown_source = candidate
            break
    if drawdown_source is not None:
        source = metrics[drawdown_source]
        metrics["max_drawdown_pct"] = {
            "value": source["value"],
            "unit": "percent",
            "source_label": source["source_label"],
            "raw_value": source["raw_value"],
            "derived_from": drawdown_source,
        }

    if "profit_trades" in metrics:
        source = metrics["profit_trades"]
        metrics["win_rate"] = {
            "value": source["value"]["percent"],
            "unit": "percent",
            "source_label": source["source_label"],
            "raw_value": source["raw_value"],
            "derived_from": "profit_trades",
        }
    if "loss_trades" in metrics:
        source = metrics["loss_trades"]
        metrics["loss_rate"] = {
            "value": source["value"]["percent"],
            "unit": "percent",
            "source_label": source["source_label"],
            "raw_value": source["raw_value"],
            "derived_from": "loss_trades",
        }

    missing = [metric for metric in REQUIRED_SUMMARY_METRICS if metric not in metrics]
    if missing:
        raise StrategyTesterResultError(
            "report missing required normalized metrics: " + ", ".join(missing)
        )

    if metrics["total_trades"]["value"] < 0:
        raise StrategyTesterResultError("total_trades cannot be negative")
    if metrics["profit_factor"]["value"] < 0:
        raise StrategyTesterResultError("profit_factor cannot be negative")
    if metrics["max_drawdown_pct"]["value"] < 0:
        raise StrategyTesterResultError("max_drawdown_pct cannot be negative")

    summary = {
        metric: metrics[metric]["value"]
        for metric in (
            "total_net_profit",
            "profit_factor",
            "expected_payoff",
            "max_drawdown_pct",
            "total_trades",
            "win_rate",
            "recovery_factor",
            "sharpe_ratio",
        )
        if metric in metrics
    }

    return {
        "schema_version": PARSER_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "experiment_id": experiment_id,
        "source_report": {
            "path": path.as_posix(),
            "sha256": _sha256(path),
            "size": path.stat().st_size,
            "encoding": encoding,
        },
        "summary": summary,
        "metrics": metrics,
        "warnings": warnings,
    }


def write_normalized_results(
    report_path: str | Path,
    output_path: str | Path,
    *,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    result = parse_strategy_tester_report(report_path, experiment_id=experiment_id)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--output")
    parser.add_argument("--experiment-id")
    args = parser.parse_args()

    try:
        result = parse_strategy_tester_report(args.report, experiment_id=args.experiment_id)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    except StrategyTesterResultError as exc:
        parser.error(str(exc))
        return
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
