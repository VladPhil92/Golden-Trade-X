# Golden Trade X

[![CI](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml/badge.svg)](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml)
[![MQL5 Windows Build](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/mql5-windows.yml/badge.svg)](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/mql5-windows.yml)
[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-blue.svg)](LICENSE)
![MQL5](https://img.shields.io/badge/MQL5-MetaTrader%205-orange)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)

**Golden Trade X** es una plataforma experimental de trading sistemático para MetaTrader 5, orientada inicialmente a XAUUSD M15. Combina un EA modular en MQL5 con herramientas Python para validación estadística, research, monitoreo y futura operación controlada.

Desarrollado y mantenido por **CTG One Technology S.A.S.**

## Estado del proyecto

> **Experimental / quantitative validation pending.** La ingeniería del sistema tiene un nivel de madurez avanzado, pero todavía **no existe evidencia empírica reproducible suficiente** para afirmar que la estrategia posee un edge rentable y estable fuera de muestra. No debe interpretarse un CI verde, una compilación correcta ni una métrica de backtest aislada como evidencia de rentabilidad futura.

El trading apalancado puede producir pérdida parcial o total del capital. Este repositorio no constituye asesoría financiera.

## Objetivo técnico

El programa de desarrollo prioriza, en este orden:

```text
CORRECTNESS
→ DATA QUALITY
→ REPRODUCIBILITY
→ QUANTITATIVE VALIDATION
→ OPTIMIZATION
→ ML
→ FORWARD VALIDATION
→ CONTROLLED PRODUCTION
```

No se añaden indicadores o modelos por complejidad nominal. Cada cambio de estrategia debe convertirse en una hipótesis falsable y validarse OOS.

## Arquitectura actual

```text
Market / Broker
      │
      ▼
SignalEngine
      │
      ├── MarketRegimeEngine
      ├── SmartMoneyEngine
      ├── FibonacciEngine
      └── ConfidenceEngine (heuristic Confluence Score)
      │
      ▼
RiskManager
      │
      ▼
OrderManager ── server-side confirmation
      │
      ▼
Broker
      │
      ├── PositionStateManager
      ├── PartialTakeProfit
      ├── Break-Even / ATR Trailing
      ├── HealthMonitor
      └── TradeLogger
```

### Componentes MQL5 principales

| Módulo | Responsabilidad |
|---|---|
| `SignalEngine.mqh` | EMA 21/55, RSI, ADX, ATR, volumen, filtro H4 |
| `MarketRegimeEngine.mqh` | clasificación heurística de régimen |
| `SmartMoneyEngine.mqh` | BOS, CHOCH, FVG, order blocks, liquidity sweep |
| `FibonacciEngine.mqh` | contexto/swing y confluencia Fibonacci |
| `ConfidenceEngine.mqh` | Confluence Score heurístico configurable |
| `RiskManager.mqh` | sizing, DD, kill switch, Kelly opcional, portfolio cap |
| `OrderManager.mqh` | ejecución, retries y confirmación server-side |
| `PositionStateManager.mqh` | Initial R inmutable, identidad y estado persistente |
| `PartialTakeProfit.mqh` | cierre parcial basado en Initial R |
| `EquityCurveFilter.mqh` | reducción de tamaño según curva de equity |
| `NewsFilter.mqh` | ventanas FOMC verificadas + proxies NFP/CPI |
| `SessionFilter.mqh` | sesión y protección de viernes |
| `HealthMonitor.mqh` | conexión, margen, SL huérfano |
| `TradeLogger.mqh` | ledger CSV por posición cerrada |

## Correctness v2.62

La versión 2.62 introduce una capa explícita de integridad de trading:

- `CTrade::PositionOpen()/Close()/Modify()` no se consideran exitosos únicamente porque el wrapper retorne `true`; se exige evidencia server-side apropiada.
- Se distinguen `order ticket`, `deal ticket`, `POSITION_IDENTIFIER` y `position ticket`.
- El estado durable se indexa por `POSITION_IDENTIFIER`.
- El riesgo inicial es inmutable durante la vida de la posición.
- Partial TP y break-even dejan de depender del SL móvil.
- `RMultiple` se define como `net P/L completo / initial monetary risk`.
- sizing y riesgo monetario usan `OrderCalcProfit()` para respetar el contrato del símbolo.
- cuentas netting con ownership ambiguo fallan cerrado.
- `InpMinInitialRR` existe como guard, pero permanece en `0.0` por defecto hasta disponer de evidencia OOS para elegir un umbral.

## Gestión de riesgo por defecto

| Control | Default |
|---|---:|
| Riesgo por operación | 1.0 % |
| DD diario | 4 % |
| DD semanal | 8 % |
| DD mensual | 15 % |
| Pérdidas consecutivas | 3 |
| SL base | ATR × 2 |
| TP base | ATR × 3 |
| Partial TP | 50 % a +1 Initial R |
| Break-even | +0.5 Initial R |
| Portfolio Risk Cap | OFF, 1.5 % si se activa |
| Kelly | OFF |
| Minimum Initial RR | OFF (`0.0`) |

Estos valores son configuración de referencia, **no parámetros demostrados como óptimos**.

## NewsFilter

FOMC 2025–2027 utiliza fechas de decisión publicadas por la Federal Reserve y convierte 14:00 US Eastern a UTC teniendo en cuenta DST. `InpNewsCalendarPolicy` permite:

- `0 = WARN`
- `1 = FAIL_CLOSED`
- `2 = FAIL_OPEN`

NFP y CPI todavía usan **proxies de fecha**. Su hora sí se convierte desde 08:30 US Eastern con DST. Antes de usar backtests históricos como evidencia oficial debe incorporarse el calendar cache histórico exacto; no debe asumirse que el filtro actual reproduce perfectamente eventos 2020–2024.

## CI y verificación

### CI Linux

En cada push/PR se ejecutan gates para:

- integridad de dependencias;
- `pip check`;
- compilación Python;
- Ruff;
- tests Python + coverage;
- XGBoost/scikit-learn compatibility;
- análisis estático MQL5;
- presets y invariantes cruzadas;
- estructura del repositorio;
- consistencia EA/CHANGELOG;
- dashboard.

### MetaEditor Windows

`.github/workflows/mql5-windows.yml` instala MetaTrader 5 oficial en `windows-latest` y compila realmente:

```text
GoldenTradeX.mq5
→ MetaEditor
→ 0 errors required
→ GoldenTradeX.ex5
→ SHA-256
→ build artifact
```

Un linter MQL5 no sustituye este gate.

### Próximo nivel de testing

La existencia de scripts en `MQL5/Scripts/Tests/` no significa todavía que todos se ejecuten automáticamente. El roadmap inmediato incluye un harness que diferencie:

```text
L1 MQL5 unit tests
L2 EA integration tests
L3 MetaTrader Strategy Tester
```

## Python / Quant tooling

`scripts/` incluye actualmente:

- `backtest_analysis.py` — métricas, retornos diarios, Monte Carlo, PSR/DSR;
- `performance_report.py` — degradación y evaluación recurrente;
- `walk_forward_optimizer.py` — análisis post-hoc por threshold;
- `ml_pipeline.py` — scaffold XGBoost;
- `regime_analysis.py`;
- `session_analyzer.py`;
- `correlation_engine.py`;
- `fomc_calendar.py`;
- `live_monitor.py` / `monitor.py`.

### Advertencia importante sobre walk-forward

El `walk_forward_optimizer.py` existente opera sobre trades ya generados y filtra retrospectivamente por confidence. Es útil como **diagnóstico**, pero **no constituye el verdadero walk-forward definitivo del EA**, porque eliminar un trade cambia equity, drawdown, rachas, sizing y estados futuros.

El walk-forward oficial deberá ser:

```text
IS Strategy Tester optimization
→ freeze parameters
→ independent OOS Strategy Tester run
→ roll window
```

## Instalación

1. MetaTrader 5 → **Archivo → Abrir carpeta de datos**.
2. Copiar `MQL5/Experts/GoldenTradeX/` a `MQL5/Experts/`.
3. Copiar `MQL5/Include/GoldenTradeX/` a `MQL5/Include/`.
4. Compilar `GoldenTradeX.mq5` en MetaEditor.
5. Cargar `config/GoldenTradeX.set` sobre XAUUSD M15.
6. Operar únicamente en demo mientras no se hayan superado los gates cuantitativos y forward.

## Backtesting

Exploración:

```text
1 minute OHLC
```

Evidencia final:

```text
Every tick based on real ticks
```

Conservar siempre:

- EA/Git SHA;
- preset y hash;
- broker;
- símbolo exacto;
- MT5 build;
- periodo;
- capital/leverage;
- spread;
- comisión;
- swap;
- slippage assumption;
- número de configuraciones probadas.

## Gates antes de capital real

Los umbrales son criterios internos de investigación, no garantías. Como referencia, una candidata no debería promoverse sin:

- expectancy OOS > 0;
- PF OOS aproximadamente > 1.25–1.30;
- Max DD < 15 %;
- PSR ≥ 95 %;
- DSR > 0;
- parameter stability;
- walk-forward robusto;
- stress de costes;
- robustez entre brokers;
- forward demo suficiente;
- observabilidad y recovery operacional.

## Roadmap

```text
v2.62  Trading Correctness
v2.63  Automated MQL5 Verification
v2.70  Research Telemetry / Event Ledger
v2.80  Quant Research / Ablation
v2.90  Reproducible Validation
v3.0-rc1  OOS validated
v3.0-rc2  Forward validated
v3.0      Controlled production
```

## Licencia

MIT © 2026 CTG One Technology S.A.S.
