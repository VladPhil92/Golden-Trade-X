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

## Real-money interlock

El EA declara `InpAllowRealTrading=false` por defecto. Durante `OnInit()`, una cuenta `ACCOUNT_TRADE_MODE_REAL` falla cerrada con `INIT_FAILED` salvo que ese input haya sido cambiado explícitamente.

Los presets versionados XAUUSD/XAGUSD mantienen el valor en `false` y `scripts/validate_set.py` rechaza un override a `true`. El bit también forma parte del snapshot canónico de configuración de research/forward, por lo que un cambio posterior altera el fingerprint y no puede reutilizar la evidencia DEMO previa.

Este interlock no constituye autorización de producción: cualquier futura activación requiere una revisión de producción controlada separada y no puede derivarse automáticamente de los gates cuantitativos.

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

Actual desde v2.70:

```text
MT5 / EA
  ├─ signal funnel observations
  ├─ order request/result observations
  ├─ immutable broker deals
  └─ final PositionState outcome (Initial R + MFE/MAE + Realized R)
          │
          ▼
ResearchTelemetry append-only CSV
          │
          ▼
telemetry_db.py
          │
          ▼
SQLite research DB
          │
          ├─ research_report.py → versioned JSON summary
          └─ dashboard/research.html
```

La capa de research es observacional y no autoriza trading. Valores faltantes permanecen faltantes; no se sustituyen por resultados sintéticos ni se convierten en evidencia de rentabilidad, OOS o forward.

Target de validación:

```text
SQLite telemetry
   ↓
Baseline / Ablation / Confidence / Exit research
   ↓
Experiment Registry
   ↓
True Strategy Tester Walk-Forward / robustness
   ↓
OOS gates / forward demo gates
   ↓
Official Validation Campaign Lock
   ↓
RC1 manual release review
```

## Verificación

### Linux CI

Dependency integrity, Ruff, Python tests/coverage, ML compatibility, config validation, MQL5 static analysis, structure, version and dashboard checks.

### Windows CI

MetaTrader 5 + MetaEditor compilan realmente `GoldenTradeX.mq5` y todos los `MQL5/Scripts/Tests/Test*.mq5`. Los scripts se ejecutan mediante MetaTrader; el gate falla ante error de compilación, timeout, ausencia de resumen o cualquier `FAIL>0`.

### Próximo nivel de testing

La automatización MQL5 L1/L2 quedó cubierta en v2.63. La infraestructura cuantitativa posterior está implementada, pero la evidencia empírica oficial permanece separada para no confundir software verification con validación económica:

1. ejecutar Strategy Tester oficial sobre el campaign lock congelado;
2. completar true walk-forward con optimización IS y ejecución OOS independiente;
3. ejecutar stress de costes, estabilidad paramétrica y replicación entre brokers pre-registrados;
4. completar la ventana forward DEMO antes de cualquier revisión de producción controlada.

## Roadmap técnico

| Milestone | Alcance | Estado |
|---|---|---|
| v2.62 | Trading Correctness | Completado |
| v2.63 | Automated MQL5 Verification | Completado |
| v2.70 | Event Ledger / Research Telemetry | Completado |
| v2.80 | Baseline + ablation + exit research tooling | Infraestructura completada; evidencia cuantitativa pendiente |
| v2.90 | Experiment Registry + true WF + robustness + forward gates | Infraestructura completada; campaña empírica pendiente |
| v3.0-rc1 | Official evidence freeze + OOS/robustness/forward lineage | En implementación/validación CI; NOT EMPIRICALLY VALIDATED |
| v3.0 | Controlled production | NOT VALIDATED |

## Principio de seguridad

Ante incertidumbre de:

- account trade mode / autorización real;
- ownership;
- Initial R;
- position identity;
- riesgo monetario;
- broker execution;
- procedencia de evidencia;

toda lógica safety-critical debe **fallar cerrada** y no incrementar exposición.