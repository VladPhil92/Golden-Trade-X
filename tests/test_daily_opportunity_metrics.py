from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.daily_opportunity_metrics import (
    ActivityMetricsError,
    TradeActivity,
    compute_activity_metrics,
    load_trades_csv,
    load_trading_days,
    weekday_trading_days,
)


def trade(day: int, symbol: str = "XAUUSD", setup: str = "A") -> TradeActivity:
    return TradeActivity(datetime(2026, 1, day, 14, 0, tzinfo=timezone.utc), symbol, setup)


def test_activity_metrics_measure_participation_not_just_trade_count() -> None:
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8), date(2026, 1, 9)]
    trades = [trade(5), trade(6), trade(6, "EURUSD", "B"), trade(9, "GBPUSD", "C")]
    result = compute_activity_metrics(trades, days)
    assert result["trading_days"] == 5
    assert result["active_trading_days"] == 3
    assert result["zero_trade_days"] == 2
    assert result["active_trading_day_ratio"] == pytest.approx(0.6)
    assert result["zero_trade_day_ratio"] == pytest.approx(0.4)
    assert result["trades_per_day_mean"] == pytest.approx(0.8)
    assert result["trades_per_day_median"] == 1.0
    assert result["max_trades_single_day"] == 2
    assert result["daily_distribution"] == {"0": 2, "1": 2, "2": 1, "3_plus": 0}
    assert result["trades_by_symbol"] == {"EURUSD": 1, "GBPUSD": 1, "XAUUSD": 2}
    assert result["live_trading_authorized"] is False
    assert result["real_capital_authorized"] is False


def test_zero_trade_period_is_valid_evidence_not_forced_activity() -> None:
    days = weekday_trading_days(date(2026, 1, 5), date(2026, 1, 10))
    result = compute_activity_metrics([], days)
    assert result["total_trades"] == 0
    assert result["zero_trade_day_ratio"] == 1.0
    assert result["active_trading_day_ratio"] == 0.0


def test_trade_outside_explicit_denominator_fails_closed() -> None:
    with pytest.raises(ActivityMetricsError, match="outside eligible trading days"):
        compute_activity_metrics([trade(10)], [date(2026, 1, 9)])


def test_exact_broker_trading_day_file_rejects_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "days.txt"
    path.write_text("2026-01-05\n2026-01-05\n", encoding="utf-8")
    with pytest.raises(ActivityMetricsError, match="duplicate"):
        load_trading_days(path)


def test_csv_requires_timezone_aware_entry_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "trades.csv"
    path.write_text("entry_utc,symbol,setup\n2026-01-05T14:00:00,XAUUSD,A\n", encoding="utf-8")
    with pytest.raises(ActivityMetricsError, match="UTC offset"):
        load_trades_csv(path)
