#!/usr/bin/env python3
"""
Golden Trade X v2.00 — Pipeline de Machine Learning.

Entrena un modelo XGBoost sobre los trades exportados por TradeLogger para:
  - Predecir si un trade será ganador (clasificación binaria)
  - Calcular probabilidad de éxito por señal
  - Identificar las features más predictivas

Flujo:
  1. Carga trades desde CSV
  2. Feature engineering (R anterior, sequencia, día/hora, etc.)
  3. Train/test split temporal (no aleatorio — evita data leakage)
  4. Entrenamiento XGBoost
  5. Evaluación con métricas: Accuracy, Precision, Recall, AUC-ROC
  6. Feature importance
  7. Export del modelo como JSON para referencia

Requisitos:
    pip install scikit-learn xgboost

Uso:
    python scripts/ml_pipeline.py                        # auto-descubre CSVs
    python scripts/ml_pipeline.py trades.csv
    python scripts/ml_pipeline.py --test-ratio 0.3 --threshold 0.60
"""

import argparse
import csv
import glob
import math
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Importaciones ML (opcionales — el script informa si no están instaladas)
try:
    import xgboost as xgb
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
    _ML_OK = True
except ImportError:
    _ML_OK = False


@dataclass
class Trade:
    close_date:  str
    close_time:  str
    symbol:      str
    side:        str
    lots:        float
    open_price:  float
    sl:          float
    tp:          float
    close_price: float
    pnl:         float
    commission:  float
    r_multiple:  float
    comment:     str = ""
    open_date:   str = ""   # v2.50: hora de APERTURA (evita leakage temporal)
    open_time:   str = ""

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def is_win(self) -> bool:
        return self.net > 0

    # v2.50: las features temporales usan la hora de APERTURA cuando el CSV
    # la trae (TradeLogger >= v2.50). La hora de cierre no se conoce en el
    # momento de decidir la entrada — usarla como feature es leakage.
    # Fallback a close para CSVs antiguos (marcado en el log al cargar).
    @property
    def _feat_date(self) -> str:
        return self.open_date or self.close_date

    @property
    def _feat_time(self) -> str:
        return self.open_time or self.close_time

    @property
    def hour(self) -> int:
        try:
            return int(self._feat_time.split(":")[0])
        except (ValueError, IndexError):
            return -1

    @property
    def day_of_week(self) -> int:
        # 0=Mon…6=Sun — calculado desde fecha YYYY-MM-DD
        try:
            from datetime import date
            y, m, d = map(int, self._feat_date.split("-"))
            return date(y, m, d).weekday()
        except Exception:
            return -1

    @property
    def month(self) -> int:
        try:
            return int(self._feat_date.split("-")[1])
        except (ValueError, IndexError):
            return -1

    @property
    def confidence(self) -> int:
        for part in self.comment.split("|"):
            if part.startswith("Conf="):
                try:
                    return int(part.split("=")[1])
                except ValueError:
                    pass
        return 50  # default para trades sin confidence (v1.x)

    @property
    def regime(self) -> str:
        for part in self.comment.split("|"):
            if part.startswith("Reg="):
                return part.split("=")[1].strip()
        return "UNKNOWN"


def load_csv(path: str) -> List[Trade]:
    trades: List[Trade] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(Trade(
                    close_date=row["CloseDate"],
                    close_time=row["CloseTime"],
                    symbol=row["Symbol"],
                    side=row["Type"],
                    lots=float(row["Lots"]),
                    open_price=float(row["OpenPrice"]),
                    sl=float(row["InitialSL"]),
                    tp=float(row["InitialTP"]),
                    close_price=float(row["ClosePrice"]),
                    pnl=float(row["ProfitLoss"]),
                    commission=float(row["Commission"]),
                    r_multiple=float(row["RMultiple"]),
                    comment=row.get("Comment", ""),
                    open_date=row.get("OpenDate", ""),
                    open_time=row.get("OpenTime", ""),
                ))
            except (KeyError, ValueError):
                continue
    if trades and not any(t.open_date for t in trades):
        print("  AVISO: CSV sin columnas OpenDate/OpenTime (TradeLogger < v2.50)."
              " Features horarias usaran la hora de CIERRE (leakage temporal).")
    if trades and not any(t.comment for t in trades):
        print("  AVISO: CSV sin columna Comment (TradeLogger < v2.50)."
              " confidence=50 y regime=UNKNOWN seran constantes — el modelo"
              " no puede aprender de esas features.")
    return trades


# ── Feature engineering ────────────────────────────────────────────────────────

REGIME_MAP = {
    "TRENDING_BULL": 0, "TRENDING_BEAR": 1, "RANGING": 2,
    "VOLATILE": 3, "ACCUMULATION": 4, "DISTRIBUTION": 5, "UNKNOWN": 6,
}


def build_features(trades: List[Trade]) -> Tuple[List[List[float]], List[int]]:
    """
    Construye matrix de features X y vector de labels y.

    Features (15 total):
      0  confidence_score     — score 0-100 del Confidence Engine
      1  side_is_buy          — 1=BUY, 0=SELL
      2  regime_code          — régimen codificado (0-6)
      3  sl_pct               — % SL sobre precio entrada
      4  tp_pct               — % TP sobre precio entrada
      5  rr_ratio             — TP/SL ratio configurado
      6  hour_sin / hour_cos  — hora de cierre (encoding cíclico)
      7  hour_cos
      8  day_of_week_sin
      9  day_of_week_cos
      10 month_sin
      11 month_cos
      12 prev_r               — R-múltiplo del trade anterior (-99 si primero)
      13 streak               — racha actual (+ = wins, - = losses)
      14 win_rate_10          — win rate en los últimos 10 trades
    """
    X: List[List[float]] = []
    y: List[int] = []

    streak  = 0
    wins_10: List[int] = []

    for i, t in enumerate(trades):
        prev_r = trades[i - 1].r_multiple if i > 0 else 0.0

        # Win rate últimos 10
        wr10 = sum(wins_10[-10:]) / min(len(wins_10), 10) if wins_10 else 0.5

        sl_pct = abs(t.open_price - t.sl) / t.open_price * 100 if t.open_price > 0 else 0
        tp_pct = abs(t.open_price - t.tp) / t.open_price * 100 if t.open_price > 0 else 0
        rr     = tp_pct / sl_pct if sl_pct > 0 else 0

        def cyc(val: float, period: float) -> Tuple[float, float]:
            angle = 2 * math.pi * val / period
            return math.sin(angle), math.cos(angle)

        h_sin, h_cos = cyc(t.hour if t.hour >= 0 else 12, 24)
        d_sin, d_cos = cyc(t.day_of_week if t.day_of_week >= 0 else 2, 7)
        m_sin, m_cos = cyc(t.month if t.month >= 0 else 6, 12)

        row = [
            float(t.confidence),
            1.0 if t.side.upper() == "BUY" else 0.0,
            float(REGIME_MAP.get(t.regime, 6)),
            sl_pct,
            tp_pct,
            rr,
            h_sin, h_cos,
            d_sin, d_cos,
            m_sin, m_cos,
            prev_r,
            float(streak),
            wr10,
        ]
        X.append(row)
        y.append(1 if t.is_win else 0)

        # Actualizar estado
        streak  = (streak + 1) if t.is_win else (streak - 1 if streak < 0 else -1)
        wins_10.append(1 if t.is_win else 0)

    return X, y


FEATURE_NAMES = [
    "confidence_score", "side_is_buy", "regime_code",
    "sl_pct", "tp_pct", "rr_ratio",
    "hour_sin", "hour_cos",
    "day_of_week_sin", "day_of_week_cos",
    "month_sin", "month_cos",
    "prev_r", "streak", "win_rate_10",
]


# ── Training ───────────────────────────────────────────────────────────────────

def train_and_evaluate(trades: List[Trade], test_ratio: float,
                       threshold: float, verbose: bool) -> Optional[Dict]:
    if not _ML_OK:
        print("\n  ⚠  XGBoost / scikit-learn no están instalados.")
        print("     Ejecute: pip install xgboost scikit-learn")
        return None

    n = len(trades)
    if n < 50:
        print(f"\n  ⚠  Muy pocos trades ({n}) para entrenar un modelo confiable.")
        print("     Se recomienda mínimo 200 trades.")
        return None

    X, y = build_features(trades)
    split = int(n * (1 - test_ratio))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    print(f"\n  Entrenamiento: {split} trades | Test OOS: {n - split} trades")

    # use_label_encoder fue eliminado en XGBoost 2.0 (requirements pide >=2.0)
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    proba  = model.predict_proba(X_test)[:, 1]
    y_pred = [1 if p >= threshold else 0 for p in proba]

    acc  = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec  = recall_score(y_test, y_pred, zero_division=0)
    try:
        auc = roc_auc_score(y_test, proba)
    except ValueError:
        auc = float("nan")

    print(f"\n  {'Métrica':<28} {'Valor':>8}")
    print(f"  {'Accuracy':<28} {acc:>8.3f}")
    print(f"  {'Precision':<28} {prec:>8.3f}")
    print(f"  {'Recall':<28} {rec:>8.3f}")
    print(f"  {'AUC-ROC':<28} {auc:>8.3f}")
    print(f"  {'Threshold':<28} {threshold:>8.2f}")

    # Feature importance
    imp = dict(zip(FEATURE_NAMES, model.feature_importances_.tolist()))
    sorted_imp = sorted(imp.items(), key=lambda x: x[1], reverse=True)

    print(f"\n  {'Feature':<28} {'Importancia':>12}")
    for name, val in sorted_imp:
        bar = "█" * int(val * 40)
        print(f"  {name:<28} {val:>8.4f}  {bar}")

    # Filtrado ML: ¿ganaríamos más aplicando el filtro de probabilidad?
    filtered_trades = [
        (trades[split + i], proba[i])
        for i in range(len(X_test))
        if proba[i] >= threshold
    ]
    all_net   = sum(trades[split + i].net for i in range(len(X_test)))
    filt_net  = sum(t.net for t, _ in filtered_trades)
    kept_pct  = len(filtered_trades) / len(X_test) * 100 if X_test else 0

    print(f"\n  P/L OOS sin filtro ML:   {all_net:>+.2f}")
    print(f"  P/L OOS con filtro ML:   {filt_net:>+.2f}  "
          f"({kept_pct:.0f}% de trades aceptados)")

    result = {
        "accuracy": acc, "precision": prec, "recall": rec, "auc": auc,
        "threshold": threshold, "feature_importance": imp,
        "pnl_unfiltered": all_net, "pnl_filtered": filt_net,
        "trades_kept_pct": kept_pct,
    }

    # Guardar modelo como JSON de referencia
    model.save_model("ml_model.json")
    print("\n  Modelo guardado → ml_model.json")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — ML Pipeline"
    )
    parser.add_argument("files", nargs="*",
                        help="CSV de TradeLogger. Auto-descubre GoldenTradeX_*.csv")
    parser.add_argument("--test-ratio", type=float, default=0.25,
                        help="Fracción de datos para test OOS temporal (default 0.25)")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="Umbral de probabilidad para clasificar como 'ganador' (default 0.55)")
    parser.add_argument("--features-only", action="store_true",
                        help="Solo mostrar tabla de features sin entrenar")
    args = parser.parse_args()

    paths = list(args.files)
    if not paths:
        paths = sorted(
            glob.glob("GoldenTradeX_*.csv")
            + glob.glob("**/GoldenTradeX_*.csv", recursive=True)
        )
    if not paths:
        print("No se encontraron CSV.")
        sys.exit(1)

    trades: List[Trade] = []
    for p in paths:
        loaded = load_csv(p)
        print(f"  Cargados {len(loaded):>4} trades  ← {p}")
        trades.extend(loaded)

    if not trades:
        sys.exit(1)

    trades.sort(key=lambda t: (t.close_date, t.close_time))
    print(f"\n  Total: {len(trades)} trades | "
          f"Win rate: {sum(t.is_win for t in trades)/len(trades)*100:.1f}%")

    if args.features_only:
        X, y = build_features(trades)
        print(f"\n  {len(X)} filas × {len(X[0])} features generadas correctamente.")
        return

    print("\n" + "─" * 62)
    print("  ENTRENAMIENTO XGBoost — Split temporal (no aleatorio)")
    print("─" * 62)

    train_and_evaluate(trades, args.test_ratio, args.threshold, verbose=True)

    print("\n  Nota: AUC > 0.55 indica valor predictivo real.")
    print("  Para producción: reentrenar mensualmente con datos recientes.")


if __name__ == "__main__":
    main()
