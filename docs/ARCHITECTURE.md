# Golden Trade X — Arquitectura

> La versión vigente es la indicada por el EA y `CHANGELOG.md`.

## Objetivo arquitectónico

Golden Trade X separa decisión, riesgo, ejecución y observabilidad. La arquitectura debe impedir que un fallo de datos, identidad o broker incremente silenciosamente el riesgo.

```text
Market Data / MT5 Indicators
          │
          ▼
     SignalEngine
          │
   ┌──────┼───────────────┐
   ▼      ▼               ▼
Regime   SMC          Fibonacci
   └──────┼───────────────┘
          ▼
   ConfluenceEngine
     (heurístico)
          │
          ▼
       Guards
 Session / News / DD /
 ownership / spread / RR
          │
          ▼
     RiskManager
          │
          ▼
     OrderManager
(server-confirmed execution)
          │
          ▼
        Broker
          │
   ┌──────┼────────────────────┐
   ▼      ▼                    ▼
PositionState            TradeLogger
Partial/BE/Trail         HealthMonitor
```

## Identidad de trading

Los siguientes identificadores son diferentes y nunca deben intercambiarse:

```text
order_ticket
   ↓
deal_ticket(s)
   ↓
POSITION_IDENTIFIER / DEAL_POSITION_ID
   ↓
current position_ticket
```

`POSITION_IDENTIFIER` es la clave durable usada por Golden Trade X para estado y Portfolio Risk Cap. El position ticket es una referencia operativa actual y se resuelve desde el identificador estable.

## Execution Engine

`OrderManager` clasifica resultados server-side:

```text
SUCCESS
PARTIAL_SUCCESS
RETRYABLE
REJECTED
FATAL
UNKNOWN
```

Un booleano `true` retornado por `CTrade` no es suficiente para declarar éxito. Las aperturas exigen deal confirmado y datos de ejecución server-side; los cierres también exigen confirmación del deal. Modificaciones utilizan retcodes compatibles con modificación confirmada/no-change.

Retries se limitan a errores clasificados como temporales. Un resultado desconocido no se transforma en éxito.

## PositionStateManager

Estado persistente por:

```text
account + magic + POSITION_IDENTIFIER
```

Core state:

- entry price;
- Initial SL;
- Initial TP;
- Initial Risk Price;
- Initial Risk Money;
- Initial Volume;
- entry time;
- confidence;
- regime.

Runtime state:

- MFE price/R/time;
- MAE price/R/time;
- closure tombstone para idempotencia.

En startup `ReconcileOpenPositions()` reconstruye posiciones cuya información puede probarse mediante historial. Ownership ambiguo en netting se considera unsafe.

## Definición de R

```text
InitialRiskPrice = abs(entry - initialSL)
InitialRiskMoney = abs(OrderCalcProfit(entry → initialSL, initialVolume))
RealizedR        = totalNetPnL / InitialRiskMoney
```

El SL actual nunca redefine Initial R.

## Gestión de posición por tick

```text
OnTick
 ├─ Friday close guard
 ├─ ManageOpenPositions
 │   ├─ Ensure PositionState
 │   ├─ Update MFE/MAE
 │   ├─ Partial TP (Initial R)
 │   ├─ Break-Even (Initial R)
 │   └─ ATR trailing (si habilitado)
 └─ if NewBar
     └─ evaluate new entry
```

Partial TP y Break-Even no dependen de que trailing esté habilitado.

## Flujo de nueva entrada

```text
New bar
  ↓
Kill switch
  ↓
Session
  ↓
Spread
  ↓
Daily/Weekly/Monthly DD
  ↓
Consecutive loss guard
  ↓
News
  ↓
Max positions
  ↓
Netting ownership
  ↓
Connection
  ↓
Regime
  ↓
Base signal
  ↓
SMC + Fib + HTF context
  ↓
Confluence Score
  ↓
Final structural SL / TP
  ↓
Initial RR guard
  ↓
Risk sizing
  ↓
Equity Curve multiplier
  ↓
OrderManager
  ↓
server-confirmed deal
  ↓
resolve POSITION_IDENTIFIER + ticket
  ↓
PositionState
  ↓
Portfolio risk reservation
```

## RiskManager

Responsabilidades:

- fixed risk sizing;
- optional Kelly;
- daily/weekly/monthly drawdown;
- consecutive losses;
- Capital Preservation;
- margin guard;
- Portfolio Risk Cap;
- kill switch.

Sizing y riesgo monetario usan `OrderCalcProfit()` para incorporar la semántica contractual real del símbolo en lugar de depender exclusivamente de fórmulas manuales con tick value/tick size.

Portfolio Risk Cap usa reservas idempotentes por `POSITION_IDENTIFIER` y reconcilia reservas huérfanas en startup.

## NewsFilter

FOMC: fechas de decisión verificadas 2025–2027 y statement 14:00 US Eastern con conversión DST.

NFP/CPI: hora DST-aware pero fecha proxy. No son todavía un calendario histórico auditable.

Coverage policy:

```text
WARN
FAIL_CLOSED
FAIL_OPEN
```

Las ventanas usan timestamps absolutos para soportar buffers que atraviesan medianoche.

## Confluence Score

No es un ensemble estadístico ni una probabilidad.

```text
Base      25
Regime    25
SMC       30
HTF       15
Fib        5
---------
Total    100
```

Los pesos necesitan ablation/sensitivity/OOS antes de promoverse como calibrados.

## Python / Research plane

Actual:

```text
TradeLogger CSV
  ├─ backtest_analysis.py
  ├─ performance_report.py
  ├─ regime_analysis.py
  ├─ session_analyzer.py
  ├─ walk_forward_optimizer.py (diagnóstico post-hoc)
  └─ ml_pipeline.py (scaffold, no live)
```

Target:

```text
MT5 events
   ↓
Event Collector
   ↓
SQLite → PostgreSQL when justified
   ↓
Signals / Decisions / Orders / Deals / Positions / Trades
   ↓
Analytics / Dashboard / Alerts / Experiment Registry
```

## Verificación

### Linux CI

Dependency integrity, Ruff, Python tests/coverage, ML compatibility, config validation, MQL5 static analysis, structure, version and dashboard checks.

### Windows CI

MetaTrader 5 + MetaEditor compilan realmente `GoldenTradeX.mq5`; el gate requiere `0 errors` y genera EX5 + SHA-256 artifact.

### Pendiente inmediato

El siguiente milestone debe automatizar:

1. compilación de TODOS los scripts de tests MQL5;
2. ejecución automatizada de tests MQL5/integration donde MT5 lo permita;
3. Strategy Tester smoke tests separados de unit tests.

## Roadmap técnico

| Milestone | Alcance | Estado |
|---|---|---|
| v2.62 | Trading Correctness | En integración |
| v2.63 | Automated MQL5 Verification | Pendiente |
| v2.70 | Event Ledger / Research Telemetry | Pendiente |
| v2.80 | Baseline + ablation + exit research | Pendiente |
| v2.90 | Experiment Registry + true WF + robustness | Pendiente |
| v3.0-rc1 | OOS gates | NOT VALIDATED |
| v3.0-rc2 | Forward demo gates | NOT VALIDATED |
| v3.0 | Controlled production | NOT VALIDATED |

## Principio de seguridad

Ante incertidumbre de:

- ownership;
- Initial R;
- position identity;
- riesgo monetario;
- broker execution;

toda lógica safety-critical debe **fallar cerrada** y no incrementar exposición.
