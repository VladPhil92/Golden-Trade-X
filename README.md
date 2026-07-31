# Golden Trade X

[![CI](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml/badge.svg)](https://github.com/VladPhil92/Golden-Trade-X/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/Licencia-MIT-blue.svg)](LICENSE)
![MQL5](https://img.shields.io/badge/MQL5-MetaTrader%205-orange)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)

**Sistema algorítmico de trading para metales preciosos (XAUUSD) sobre MetaTrader 5**, con gestión de riesgo multicapa, ejecución con tolerancia a fallos y una plataforma completa de análisis estadístico y monitoreo continuo.

Desarrollado y mantenido por **CTG One Technology S.A.S.**

---

## Aviso legal y de riesgo

> ⚠️ El trading apalancado en metales conlleva un **riesgo elevado de pérdida parcial o total del capital**. Este software se distribuye "tal cual" (*as is*), con fines educativos y de investigación. Debe probarse siempre en **cuenta demo** y validarse con backtesting exhaustivo antes de considerar capital real. Nada en este repositorio constituye asesoría financiera ni una oferta de servicios de inversión.
>
> **Estado del proyecto:** sistema experimental en etapa de validación. La infraestructura de software se encuentra en un estado de madurez avanzado; sin embargo, **no existe todavía evidencia empírica reproducible** (backtest auditado, forward test prolongado) de que la estrategia posea una ventaja estadística rentable. Este repositorio documenta sus limitaciones metodológicas de forma explícita — ver [Advertencias metodológicas](#advertencias-metodológicas-conocidas).

---

## Acerca de CTG One Technology S.A.S.

CTG One Technology S.A.S. es una sociedad de tecnología dentro de cuyo portafolio se desarrolla Golden Trade X como plataforma de investigación, ejecución y gestión de riesgo para estrategias sistemáticas sobre metales preciosos.

| | |
|---|---|
| **Sitio web** | [ctgone.com](https://ctgone.com) |
| **Contacto** | [ctgone@gmail.com](mailto:ctgone@gmail.com) |
| **Repositorio** | [github.com/VladPhil92/Golden-Trade-X](https://github.com/VladPhil92/Golden-Trade-X) |

---

## Descripción del producto

Golden Trade X es un Expert Advisor (EA) para MetaTrader 5 orientado a Oro (XAUUSD) en timeframe M15, acompañado de un ecosistema de herramientas Python para análisis, validación y observabilidad. El sistema se estructura en tres planos:

1. **Motor de decisión (MQL5)** — señal técnica multicapa con clasificación de régimen de mercado, análisis de estructura (Smart Money Concepts), confluencia Fibonacci y un puntaje de confluencia configurable.
2. **Gestión de riesgo y ejecución (MQL5)** — límites de drawdown diario/semanal/mensual persistentes, kill switch, control de riesgo agregado entre instancias, validación de margen y ejecución con reintentos y validación de restricciones del broker.
3. **Plataforma de análisis y monitoreo (Python)** — estadística de desempeño con métricas ajustadas por riesgo (Sortino, Calmar, PSR/DSR), Monte Carlo con block bootstrap, optimización walk-forward, evaluación continua con alertas de degradación y notificaciones Telegram.

### Arquitectura del repositorio

```
golden-trade-x/
├── MQL5/
│   ├── Experts/GoldenTradeX/
│   │   └── GoldenTradeX.mq5          ← EA principal (orquestador)
│   ├── Include/GoldenTradeX/
│   │   ├── SignalEngine.mqh          ← Señal base: EMA21/55 + RSI + ADX + ATR + H4
│   │   ├── MarketRegimeEngine.mqh    ← Clasificación de régimen (tendencia/rango/volátil)
│   │   ├── SmartMoneyEngine.mqh      ← BOS/CHOCH/FVG/Order Blocks/Liquidity Sweep
│   │   ├── FibonacciEngine.mqh       ← Confluencia con niveles Fibonacci
│   │   ├── ConfidenceEngine.mqh      ← Confluence Score heurístico (pesos configurables)
│   │   ├── RiskManager.mqh           ← Riesgo, DD multicapa, Kelly, Portfolio Risk Cap
│   │   ├── OrderManager.mqh          ← Ejecución con retry, validación, stops_level
│   │   ├── HealthMonitor.mqh         ← Monitor periódico: margen, conexión, SL huérfano
│   │   ├── PartialTakeProfit.mqh     ← Cierre parcial al alcanzar R objetivo
│   │   ├── EquityCurveFilter.mqh     ← Reduce lote si equity < su propia EMA
│   │   ├── SessionFilter.mqh         ← Filtro de sesiones, fin de semana y aviso DST
│   │   ├── NewsFilter.mqh            ← Filtro NFP / FOMC (2025–2027) / CPI
│   │   └── TradeLogger.mqh           ← Registro CSV auditable por operación cerrada
│   └── Scripts/Tests/                ← Tests unitarios MQL5 (ejecución manual en MT5)
├── scripts/
│   ├── backtest_analysis.py          ← Estadística, Monte Carlo, PSR/DSR, reporte HTML
│   ├── performance_report.py         ← Evaluación continua con alertas de degradación
│   ├── walk_forward_optimizer.py     ← Walk-forward real (ventanas IS/OOS deslizantes)
│   ├── ml_pipeline.py                ← Pipeline XGBoost sobre el historial de trades
│   ├── correlation_engine.py         ← Correlaciones macro (DXY, VIX, US10Y, SP500)
│   ├── fomc_calendar.py              ← Actualizador del calendario FOMC → código MQL5
│   ├── mql5_lint.py                  ← Linter estático MQL5 (integrado en CI)
│   ├── validate_set.py               ← Validador de presets .set (integrado en CI)
│   └── live_monitor.py / monitor.py  ← Monitoreo en vivo con alertas Telegram
├── config/                           ← Presets del Strategy Tester (XAUUSD / XAGUSD)
├── dashboard/                        ← Dashboard offline (carga CSV del TradeLogger)
├── docs/                             ← STRATEGY.md · ARCHITECTURE.md
├── tests/                            ← Suite pytest (69 tests) de la capa estadística
└── CHANGELOG.md                      ← Historial completo de versiones (fuente de verdad)
```

### Flujo de decisión

```
Nueva vela → Guardianes: kill switch / sesión / spread / DD diario-semanal-mensual /
             pérdidas consecutivas / noticias / margen
          → Señal base: EMA21/55 + RSI + ADX + ATR + tendencia H4
          → Régimen de mercado (bloqueo total en régimen VOLATILE)
          → Confluence Score ≥ umbral configurado
          → Dimensionamiento: % de riesgo (o Kelly fraccional), Portfolio Risk Cap,
             validación de margen libre
          → Ejecución: SL/TP validados contra restricciones del broker, retry automático
          → Gestión: break-even con buffer, partial TP, trailing ATR, cierre de viernes
```

---

## Proceso de desarrollo

El proyecto sigue prácticas de ingeniería verificables en el propio repositorio:

- **Versionado documentado** — cada versión queda registrada en [`CHANGELOG.md`](CHANGELOG.md) (formato *Keep a Changelog*), incluyendo causas raíz de los defectos corregidos.
- **Integración continua** — 7 verificaciones automáticas en cada push: lint Python (ruff), linter estático MQL5, suite pytest, validación de presets, consistencia de versiones, estructura del repositorio y validación del dashboard.
- **Auditorías críticas iterativas** — el código ha sido sometido a revisiones internas y externas sucesivas (correctitud de ejecución, seguridad, control de riesgo, metodología estadística), con los hallazgos y su resolución documentados en el CHANGELOG.
- **Honestidad metodológica** — las limitaciones conocidas se documentan en lugar de ocultarse; los nombres de los componentes reflejan lo que realmente son (p. ej. *Confluence Score heurístico*, no "ensemble estadístico").

### Gestión de riesgo por defecto

| Control | Valor por defecto |
|---|---|
| Riesgo por operación | 1 % del equity (Kelly fraccional opcional, desactivado) |
| Stop Loss / Take Profit | ATR(14) × 2 / ATR(14) × 3 |
| Drawdown diario / semanal / mensual | 4 % / 8 % / 15 % — persistentes entre reinicios |
| Pérdidas consecutivas | Pausa tras 3 (neto de posición completa) |
| Kill switch | Automático ante errores fatales del broker; persistente |
| Portfolio Risk Cap | Opcional — riesgo agregado entre instancias correlacionadas |
| Validación de margen | Máx. 80 % del margen libre antes de enviar |

> Estos son valores por defecto configurables, no objetivos de rendimiento validados. Para capital real se recomienda iniciar con riesgo sustancialmente menor (0.25–0.5 %).

---

## Instalación

1. Abra MetaTrader 5 → **Archivo → Abrir carpeta de datos**.
2. Copie:
   - `MQL5/Experts/GoldenTradeX/` → carpeta `MQL5/Experts/` del terminal
   - `MQL5/Include/GoldenTradeX/` → carpeta `MQL5/Include/` del terminal
3. Abra **MetaEditor** (F4) y compile `GoldenTradeX.mq5` (F7). Debe compilar con 0 errores.
4. En MT5, arrastre el EA al gráfico **XAUUSD M15** y habilite *Algo Trading*.
5. Verifique el nombre exacto del símbolo de su broker (`XAUUSD`, `GOLD`, `XAUUSD.m`, etc.).

## Validación y backtesting (obligatorio antes de demo/real)

1. **Ver → Probador de estrategias** (Ctrl+R), símbolo de oro de su broker, M15.
2. En **Inputs**: engranaje ⚙ → **Load Settings** → `config/GoldenTradeX.set`.
3. Modelo *1 minute OHLC* para exploración; *Every tick based on real ticks* para el resultado final.
4. Analice el CSV generado por el TradeLogger:

```bash
pip install -r requirements.txt

# Análisis estadístico completo (Monte Carlo, Sharpe %, Sortino, PSR/DSR)
python scripts/backtest_analysis.py trades.csv --html-output report.html
python scripts/backtest_analysis.py --block-size 5 --trials 20

# Walk-forward real (ventanas in-sample / out-of-sample deslizantes)
python scripts/walk_forward_optimizer.py trades.csv

# Evaluación continua en demo/real (alertas de degradación)
python scripts/performance_report.py --watch 300
```

Este repositorio no publica resultados de ejemplo: genere su propia evidencia con `--html-output` y consérvela junto con el `.set` utilizado, el build de MT5, el broker y el periodo exacto.

## Operación multi-símbolo (XAGUSD)

1. Gráfico **XAGUSD M15** → arrastre el EA → preset `config/GoldenTradeX_XAGUSD.set` (magic `920261`).
2. Active `InpUsePortfolioCap=true` en **ambas** instancias con el mismo límite: XAUUSD y XAGUSD están correlacionados y, sin este control, cada instancia gestiona su riesgo de forma aislada aunque la exposición macro real esté sumada.

## Monitoreo continuo

```bash
python scripts/live_monitor.py --dry-run        # alertas Telegram (trades, salud del EA)
python scripts/performance_report.py --watch 300  # degradación de desempeño
```

Configure las credenciales en `.env` (plantilla en `.env.example`). Requiere el terminal MT5 abierto en la misma máquina Windows para `monitor.py`.

---

## Advertencias metodológicas conocidas

- El **Confluence Score** es un puntaje heurístico por confluencia de filtros, no un ensemble estadístico calibrado. Sus pesos (`InpConfWeight*`) son configurables precisamente para optimizarse con datos reales.
- El desglose trimestral de `backtest_analysis.py` es descriptivo; el walk-forward de entrenamiento/prueba real es `walk_forward_optimizer.py`.
- El Monte Carlo por defecto asume independencia entre operaciones; use `--block-size 5` o mayor para preservar rachas.
- Los "objetivos internos de calidad" del reporte son umbrales propios del proyecto, no una certificación externa.
- Las fechas FOMC 2027 son proyectadas, pendientes de confirmación por la Reserva Federal.
- El CI no compila MQL5 (MetaEditor no existe para Linux); el linter estático cubre las clases de error conocidas y la compilación final se verifica en MetaEditor.

## Soporte y contribuciones

- **Consultas y soporte:** [ctgone@gmail.com](mailto:ctgone@gmail.com)
- **Defectos y sugerencias:** [Issues del repositorio](https://github.com/VladPhil92/Golden-Trade-X/issues)
- **Historial de cambios:** [`CHANGELOG.md`](CHANGELOG.md)

## Licencia

MIT © 2026 [CTG One Technology S.A.S.](https://ctgone.com) — ver [`LICENSE`](LICENSE).

El uso de este software implica la aceptación de que el usuario es el único responsable de las decisiones de inversión tomadas con él.
