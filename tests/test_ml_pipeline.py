"""Compatibility and regression tests for the Golden Trade X ML pipeline."""

from __future__ import annotations

from datetime import date, timedelta

from scripts import ml_pipeline as ml


def _synthetic_trades(n: int = 80) -> list[ml.Trade]:
    regimes = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "ACCUMULATION"]
    start = date(2026, 1, 1)
    trades: list[ml.Trade] = []
    for i in range(n):
        d = start + timedelta(days=i)
        is_win = i % 2 == 0
        open_price = 2000.0 + i
        trades.append(
            ml.Trade(
                close_date=d.isoformat(),
                close_time=f"{10 + (i % 8):02d}:45:00",
                symbol="XAUUSD",
                side="BUY" if i % 3 else "SELL",
                lots=0.10,
                open_price=open_price,
                sl=open_price - 10.0,
                tp=open_price + 15.0,
                close_price=open_price + (8.0 if is_win else -6.0),
                pnl=12.0 if is_win else -9.0,
                commission=-0.5,
                r_multiple=1.2 if is_win else -0.9,
                comment=f"GTX|Conf={45 + (i % 36)}|Reg={regimes[i % len(regimes)]}",
                open_date=d.isoformat(),
                open_time=f"{8 + (i % 10):02d}:15:00",
            )
        )
    return trades


def test_build_features_is_deterministic_and_has_expected_shape() -> None:
    trades = _synthetic_trades(12)
    x1, y1 = ml.build_features(trades)
    x2, y2 = ml.build_features(trades)

    assert x1 == x2
    assert y1 == y2
    assert len(x1) == 12
    assert len(x1[0]) == len(ml.FEATURE_NAMES) == 15
    assert set(y1) == {0, 1}


def test_time_features_use_open_timestamp_not_close_timestamp() -> None:
    trade = _synthetic_trades(1)[0]
    trade.open_time = "08:15:00"
    trade.close_time = "19:45:00"

    features, _ = ml.build_features([trade])

    assert trade.hour == 8
    assert features[0][6] != 0.0  # hour_sin for 08:00


def test_xgboost_training_predict_and_model_roundtrip(tmp_path, monkeypatch) -> None:
    """Detect breaking API changes in XGBoost/scikit-learn before merge."""
    monkeypatch.chdir(tmp_path)
    trades = _synthetic_trades(80)

    result = ml.train_and_evaluate(trades, test_ratio=0.25, threshold=0.50, verbose=False)

    assert result is not None
    assert 0.0 <= result["accuracy"] <= 1.0
    assert 0.0 <= result["precision"] <= 1.0
    assert 0.0 <= result["recall"] <= 1.0
    assert set(result["feature_importance"]) == set(ml.FEATURE_NAMES)

    model_path = tmp_path / "ml_model.json"
    assert model_path.is_file()

    model = ml.xgb.XGBClassifier()
    model.load_model(model_path)
    features, _ = ml.build_features(trades)
    probabilities = model.predict_proba(features[-10:])

    assert probabilities.shape == (10, 2)
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()
