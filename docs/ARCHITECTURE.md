# Golden Trade X — Arquitectura

> La versión vigente del EA es la del `#property version` de `GoldenTradeX.mq5`
> y la primera entrada de `CHANGELOG.md` — este documento no fija versión
> para evitar quedar desactualizado.

## Visión general

Golden Trade X es un Expert Advisor para MetaTrader 5 con arquitectura
modular de capas. Cada capa tiene responsabilidad única y se comunica
a través de interfaces claras. La decisión de entrada se produce mediante
un **Confluence Score** heurístico que agrega múltiples fuentes de señal.

```
┌─────────────────────────────────────────────────────────────┐
│                       GoldenTradeX.mq5                       │
│                 (Orquestador / Entry Point)                   │
└──────────┬──────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────┐
    │                   CAPA DE FILTROS                        │
    │  SessionFilter  │  NewsFilter  │  RiskManager           │
    │  (horario/FV)   │  (NFP/FOMC)  │  (DD/consec/CB/KS)    │
    └──────┬──────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────┐
    │                CAPA DE ANÁLISIS DE MERCADO               │
    │  SignalEngine        MarketRegimeEngine  SmartMoneyEngine │
    │  (EMA+RSI+ADX+ATR)  (7 regímenes)       (BOS/CHOCH/FVG/OB)│
    └──────┬──────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────┐
    │               ENSEMBLE CONFIDENCE ENGINE                  │
    │  Score 0-100 = BaseSignal(25) + Regime(25) +             │
    │               SMC(30) + HTF(15) + ATR(5)                 │
    │  Umbral configurable: InpMinConfidence (default 55)       │
    └──────┬──────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────┐
    │                  CAPA DE EJECUCIÓN                        │
    │  CalculateLotSize  │  PositionOpen  │  ManageTrailing    │
    │  (% equity × mult) │  (CTrade)      │  (BE + Trailing)   │
    └──────┬──────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────┐
    │              CAPA DE OBSERVABILIDAD                       │
    │  TradeLogger.mqh    │  monitor.py     │  dashboard/      │
    │  (CSV por trade)    │  (Telegram/log) │  (HTML/Chart.js) │
    └─────────────────────────────────────────────────────────┘
```

## Módulos MQL5

### Núcleo (MQL5/Include/GoldenTradeX/)

| Módulo | Responsabilidad | Entradas | Salidas |
|--------|-----------------|----------|---------|
| `SignalEngine.mqh` | Cruce EMA+RSI+ADX+ATR+H4 | Symbol, TF, parámetros | `ENUM_SIGNAL`, ATR |
| `MarketRegimeEngine.mqh` | Clasificación de régimen | Symbol, TF | `ENUM_MARKET_REGIME`, RegimeScore |
| `SmartMoneyEngine.mqh` | BOS, CHOCH, FVG, OB, LS | Symbol, TF, lookbacks | `SSmcContext`, SmcScore |
| `ConfidenceEngine.mqh` | Confluence scoring 0-100 (heurístico) | Scores de capas | `SConfidenceResult` |
| `RiskManager.mqh` | DD, lotes, circuit breakers | % riesgo, límites | lots, bool guards |
| `SessionFilter.mqh` | Horario y fin de semana | Horas, flags | bool |
| `NewsFilter.mqh` | NFP/FOMC/CPI calendario | Buffers min | bool |
| `TradeLogger.mqh` | CSV de trades cerrados | Deal ticket | CSV file |

### Flujo de decisión por barra

```
OnTick()
  ├─ ManageTrailing()            ← cada tick
  └─ IsNewBar() → true
       ├─ KillSwitch?            → STOP
       ├─ SessionFilter?         → SKIP
       ├─ Spread?                → SKIP
       ├─ DD diario/sem/mensual? → SKIP
       ├─ ConsecLosses?          → SKIP
       ├─ NewsBlocked?           → SKIP
       ├─ MaxPositions?          → SKIP
       ├─ Regime == VOLATILE?    → SKIP
       ├─ SignalEngine.GetSignal() == NONE? → SKIP
       ├─ ConfidenceEngine.Compute()
       │    < InpMinConfidence?  → SKIP (loguea score)
       └─ PositionOpen(lots, sl, tp, comment="GTX|Conf=N|Reg=X")
```

## Módulos Python

| Script | Uso |
|--------|-----|
| `monitor.py` | Monitoreo en vivo con Telegram y reconexión |
| `backtest_analysis.py` | Métricas post-backtest + Monte Carlo + Walk-Forward |
| `regime_analysis.py` | Análisis por régimen de mercado + stress test |
| `ml_pipeline.py` | Feature engineering + XGBoost (señal de calidad) |
| `validate_set.py` | Validación de parámetros del preset `.set` |

## Dashboard Web

`dashboard/index.html` — archivo estático, sin servidor.

- Abrir directamente en el browser (`file://`)
- Cargar CSV(s) exportados por TradeLogger via drag-and-drop
- Muestra: equity curve, KPIs, régimen, confidence buckets, P/L mensual,
  checklist institucional, tabla de últimas 30 operaciones

## Confluence Score — Desglose (heurístico, no calibrado)

```
┌──────────────────┬──────────────┬────────────────────────────────┐
│ Componente       │ Puntos máx.  │ Condición máxima               │
├──────────────────┼──────────────┼────────────────────────────────┤
│ Señal base       │ 25           │ EMA cross + RSI en zona        │
│ Régimen mercado  │ 25           │ Régimen TRENDING alineado      │
│ Smart Money      │ 30           │ BOS + CHOCH + FVG + OB         │
│ Alineación HTF   │ 15           │ Precio H4 sobre/bajo EMA50     │
│ Calidad ATR      │ 5            │ ATR ratio 0.8–1.5              │
├──────────────────┼──────────────┼────────────────────────────────┤
│ TOTAL            │ 100          │                                 │
└──────────────────┴──────────────┴────────────────────────────────┘

Umbrales recomendados:
  InpMinConfidence = 40  → alta frecuencia, menor calidad
  InpMinConfidence = 55  → equilibrio (default)
  InpMinConfidence = 70  → baja frecuencia, alta calidad
  InpMinConfidence = 80  → solo confluencias excepcionales
```

## Gestión de riesgo multicapa

```
Nivel 1: Spread > InpMaxSpreadPoints          → skip entrada
Nivel 2: DD diario > InpMaxDailyDD            → pausa hasta mañana
Nivel 3: DD semanal > InpMaxWeeklyDD          → pausa hasta semana sig.
Nivel 4: Circuit Breaker mensual              → pausa hasta mes sig.
Nivel 5: Pérdidas consec. >= InpMaxConsecLosses → pausa hasta semana sig.
Nivel 6: Lote < mínimo broker                 → no operar
Nivel 7: Capital Preservation Mode (auto)     → riesgo reducido al 25%
Nivel 8: Kill Switch (manual)                 → parada total
```

## Smart Money Concepts — Lógica

### BOS (Break of Structure)
- **Bullish BOS**: `close[1] > swing_high_reciente`
- **Bearish BOS**: `close[1] < swing_low_reciente`
- Swing detectado con fractal de 3 barras (N barras a cada lado)

### FVG (Fair Value Gap)
- **Bullish FVG**: `high[bar+2] < low[bar]` — brecha entre 3 velas
- **Bearish FVG**: `low[bar+2] > high[bar]`
- Proximity: precio dentro de 1×ATR del gap

### Order Block
- **Bullish OB**: última vela bajista antes de un BOS alcista
- **Bearish OB**: última vela alcista antes de un BOS bajista

### Liquidity Sweep
- **Bull sweep**: wick bajo el swing low, cierre sobre él
- **Bear sweep**: wick sobre el swing high, cierre bajo él

## Roadmap hacia producción

| Fase | Descripción | Estado |
|------|-------------|--------|
| 1 | EA base + riesgo multicapa | ✅ Completo |
| 2 | TradeLogger + tests unitarios | ✅ Completo |
| 3 | CI/CD GitHub Actions | ✅ Completo |
| 4 | Telegram + análisis estadístico | ✅ Completo |
| 5 | Market Regime + SMC + Confidence | ✅ Completo (v2.00) |
| 6 | ML Pipeline (XGBoost) | ✅ Scaffold completo |
| 7 | Dashboard Web | ✅ Completo |
| 8 | Backtest XAUUSD 2020-2026 (MT5) | ⏳ Requiere MT5 |
| 9 | Walk-forward 8 ventanas | ⏳ Requiere MT5 |
| 10 | Demo 3 meses (≥100 trades) | ⏳ Requiere broker |
| 11 | VPS deploy + monitor 24/5 | ⏳ Producción |
| 12 | ML reentrenamiento mensual | ⏳ Post-producción |
| 13 | SaaS / multi-cuenta | ⏳ Expansión comercial |
