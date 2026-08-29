# Golden Trade X

[![CI](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml/badge.svg)](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml)
[![MQL5 Windows Build](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/mql5-windows.yml/badge.svg)](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/mql5-windows.yml)
[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-blue.svg)](LICENSE)
![MQL5](https://img.shields.io/badge/MQL5-MetaTrader%205-orange)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)

**Golden Trade X** es una plataforma experimental de trading sistemático para MetaTrader 5, orientada inicialmente a XAUUSD M15. Combina un EA modular en MQL5 con herramientas Python para validación estadística, telemetría, Strategy Tester reproducible, rolling IS → frozen OOS, robustez y forward demo controlado.

Desarrollado y mantenido por **CTG One Technology S.A.S.**

## Estado del proyecto

> **Experimental / official quantitative validation pending.** La ingeniería y el sistema de validación tienen un nivel de madurez avanzado, pero todavía **no existe una campaña oficial OOS + robustness + forward DEMO completada** que demuestre un edge rentable y estable. Un CI verde, una compilación correcta o un backtest aislado no constituyen evidencia de rentabilidad futura.

El trading apalancado puede producir pérdida parcial o total del capital. Este repositorio no constituye asesoría financiera.

La secuencia de desarrollo es deliberadamente fail-closed:

```text
CORRECTNESS
→ DATA QUALITY
→ REPRODUCIBILITY
→ QUANTITATIVE VALIDATION
→ ROBUSTNESS
→ FORWARD DEMO
→ MANUAL RELEASE REVIEW
→ CONTROLLED PRODUCTION
```

No se añaden indicadores o modelos por complejidad nominal. Cada modificación de estrategia debe convertirse en una hipótesis falsable y evaluarse sin contaminación OOS.

## Arquitectura del EA

```text
Market / Broker
      │
      ▼
SignalEngine
      │
      ├── MarketRegimeEngine
      ├── SmartMoneyEngine
      ├── FibonacciEngine
      └── ConfidenceEngine
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
      ├── TradeLogger
      └── ResearchTelemetry
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
| `NewsFilter.mqh` | ventanas macroeconómicas y política fail-closed |
| `EconomicCalendarData.mqh` | calendario generado desde contrato económico versionado |
| `SessionFilter.mqh` | sesión y protección de viernes |
| `HealthMonitor.mqh` | conexión, margen, SL huérfano |
| `TradeLogger.mqh` | ledger CSV por posición cerrada |
| `ResearchTelemetry.mqh` | señales, ejecuciones, outcomes y procedencia de sesión |

## Trading correctness y capital real

La capa de integridad del EA exige evidencia server-side y distingue `order ticket`, `deal ticket`, `POSITION_IDENTIFIER` y position ticket. El estado durable se indexa por `POSITION_IDENTIFIER`; Initial R permanece inmutable; sizing usa `OrderCalcProfit()` y cuentas netting con ownership ambiguo fallan cerrado.

Además, el repositorio incorpora un interlock explícito:

```text
InpAllowRealTrading=false
```

Una cuenta REAL con el valor por defecto aborta `OnInit()`. Los presets versionados deben conservar ese valor en `false`, el validator rechaza overrides y el bit forma parte del fingerprint de runtime. La infraestructura de investigación **no autoriza capital real**.

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

Estos valores son configuración de referencia, no parámetros demostrados como óptimos.

## Calendario económico

El repositorio diferencia dos niveles:

1. **Exploración/demo no oficial:** mientras `EconomicCalendarData.mqh` indique `GTX_ECONOMIC_CALENDAR_APPROVED=false`, NFP/CPI pueden conservar el fallback heurístico documentado y FOMC conserva fechas verificadas de fallback.
2. **Campaña oficial:** `scripts/pre_campaign_readiness.py` exige un contrato económico aprobado, con procedencia BLS/Federal Reserve, cobertura completa de toda la ventana walk-forward y un `EconomicCalendarData.mqh` generado exactamente desde ese contrato.

Por diseño, los archivos `config/economic_calendar.example.json` y `config/official_validation_campaign.example.json` son DRAFT. No pueden convertirse en evidencia oficial simplemente cambiando una etiqueta: el gate valida contenido, cobertura y consistencia del include generado.

## Testing real

### CI Linux

En cada push/PR se verifican, entre otros:

- integridad de dependencias;
- `pip check`;
- compilación Python;
- Ruff;
- tests Python + coverage;
- cobertura específica de módulos críticos de evidencia;
- XGBoost/scikit-learn compatibility;
- análisis estático MQL5;
- presets e invariantes cruzadas;
- contrato económico generado;
- estructura del repositorio;
- consistencia EA/CHANGELOG;
- dashboard;
- secret scanning;
- supply-chain de GitHub Actions.

### MetaEditor + MetaTrader Windows

`.github/workflows/mql5-windows.yml` instala MetaTrader 5, compila realmente `GoldenTradeX.mq5` y ejecuta la batería automatizada de scripts MQL5. El gate requiere compilación sin errores y ejecución satisfactoria; un linter no sustituye esta verificación.

La estructura actual es:

```text
L1  Python/unit contracts
L2  MQL5 module/integration scripts ejecutados en MetaTrader
L3  Registered Strategy Tester experiments
L4  Official rolling IS → frozen OOS campaign
L5  Robustness + fixed-window forward DEMO
```

## Research y reproducibilidad

`scripts/` incluye tooling para:

- análisis de backtests, Monte Carlo, PSR/DSR y performance;
- telemetry SQLite;
- experiment registry content-addressed;
- parser normalizado de reportes MT5;
- Strategy Tester harness y matrices de ablación;
- walk-forward planner, selector IS, aggregate OOS y promotion gate;
- robustness planner/aggregate/gate;
- forward demo readiness/planner/evaluator/gate;
- execution-environment attestation;
- official campaign freeze y runner;
- RC1 manual release-review gate;
- calendario económico content-addressed y pre-campaign readiness.

El antiguo `walk_forward_optimizer.py` sigue siendo una herramienta diagnóstica post-hoc; **no sustituye** al pipeline oficial. El walk-forward oficial vuelve a ejecutar Strategy Tester:

```text
IS candidate runs
→ IS-only selection
→ exact preset freeze
→ independent OOS Strategy Tester run
→ roll window
→ aggregate OOS
→ promotion policy frozen before observation
```

## Campaña oficial v3.0-rc1

La infraestructura ya puede congelar:

```text
Git SHA
candidate universe + preset hashes
DEMO execution environment
MT5 build / broker / server / symbol / timeframe
walk-forward plan
OOS promotion policy
robustness template + policy
forward-demo policy
economic-calendar contract
exact campaign dependency lock
```

El workflow manual `Official Validation Campaign` ejecuta un preflight, congela la campaña, compila el build, realiza attestation de la cuenta DEMO y sólo entonces ejecuta rolling IS → frozen OOS.

**Estado actual:** infraestructura disponible; campaña oficial todavía no materializada. Los templates siguen en DRAFT y no existen resultados OOS oficiales que permitan declarar `v3.0-rc1 OOS validated`.

## Backtesting y evidencia

Exploración rápida puede usar modelos menos costosos. La evidencia final debe usar:

```text
Every tick based on real ticks
```

Conservar siempre:

- EA/Git SHA;
- EX5/hash;
- preset/hash;
- candidate-universe hash;
- broker/company/server;
- símbolo exacto;
- MT5 build;
- período IS/OOS;
- capital/leverage/currency;
- spread, comisión, swap y slippage model;
- economic-calendar hash;
- policy hashes;
- número de configuraciones probadas;
- reportes MT5 raw + normalizados;
- experiment registry.

## Gates antes de capital real

Una candidata no puede avanzar sólo porque un backtest sea positivo. La secuencia prevista requiere:

- OOS aggregate positivo bajo policy pre-registrada;
- tamaño muestral suficiente;
- drawdown aceptable;
- estabilidad entre folds y parámetros;
- control de selección/multiple testing;
- stress de costes;
- replicación entre brokers cuando aplique;
- forward DEMO de ventana fija;
- continuidad de telemetría/fingerprint;
- recovery operacional;
- revisión manual RC1/RC2.

Incluso un `FORWARD_DEMO_PASS` conserva `live_trading_authorized=false` hasta una decisión de producción separada.

## Supply-chain y gobernanza

Los workflows versionados usan referencias de GitHub Actions fijadas a commits completos. `scripts/workflow_supply_chain_check.py` rechaza refs mutables. Para campañas oficiales existe además `config/campaign_requirements.lock` con versiones directas exactas.

`.github/scripts/configure-governance.ps1` declara la protección deseada de `main`: PR obligatorio, rama actualizada, resolución de conversaciones, bloqueo de force-push/deletion y los cuatro gates agregados (`CI`, `Security`, `MQL5`, `Reproducibility`). La aplicación efectiva de esa política depende de permisos administrativos de GitHub y debe verificarse en la configuración del repositorio.

## Roadmap

```text
v2.62     Trading Correctness                         DONE
v2.63     Automated MQL5 Verification                DONE
v2.70     Research Telemetry / Event Ledger           DONE
v2.80     Quant Research / Ablation tooling           DONE; evidence pending
v2.90     Reproducible Validation                     DONE
v2.90.2   Rolling IS → Frozen OOS contracts           DONE
v2.90.3   Robustness framework                        DONE
v2.90.4   Forward Demo observation contracts          DONE
v3.0-rc1  Official OOS validation infrastructure      READY; evidence pending
v3.0-rc2  Forward validated                           PENDING
v3.0      Controlled production                       BLOCKED
```

## Instalación

1. MetaTrader 5 → **Archivo → Abrir carpeta de datos**.
2. Copiar `MQL5/Experts/GoldenTradeX/` a `MQL5/Experts/`.
3. Copiar `MQL5/Include/GoldenTradeX/` a `MQL5/Include/`.
4. Compilar `GoldenTradeX.mq5` en MetaEditor.
5. Cargar `config/GoldenTradeX.set` sobre XAUUSD M15.
6. Operar únicamente en DEMO mientras no se hayan superado los gates cuantitativos y forward.

## Licencia

MIT © 2026 CTG One Technology S.A.S.
