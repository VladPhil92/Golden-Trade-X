# Changelog

All notable changes to Golden Trade X are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.20] — 2026-07-30

### Fixed (bugs críticos)
- **`RiskManager.mqh`** — Kill Switch ahora persiste via `GlobalVariable` entre reinicios
  del EA. Antes `m_killSwitch = false` en `Init()` reseteaba silenciosamente el kill switch
  al recargar el EA. Ahora `SetKillSwitch(true)` escribe `GTX_{login}_{magic}_KillSwitch=1`
  y `Init()` lo restaura automáticamente.
- **`GoldenTradeX.mq5`** — Trailing stop ahora se activa a **1 ATR** de ganancia
  (antes era `atr × InpAtrSlMultiplier` = 2 ATR), reduciendo significativamente el tiempo
  muerto antes de que el trailing proteja la posición.
- **`GoldenTradeX.mq5`** — Break-even y trailing stop son ahora **secuenciales** en el mismo
  tick. El `continue` que impedía que el trailing se ejecutara en el tick donde se movía a
  break-even fue eliminado. Break-even mueve el SL; luego trailing lo mueve si corresponde.

### Added — MQL5
- **`PartialTakeProfit.mqh`** — Módulo de cierre parcial de posiciones (`CPartialTP`):
  cierra `InpPartialTPPct`% del lote cuando el flotante supera `InpPartialTPR × riesgo`.
  Estado persistido via `GlobalVariable` (`GTX_PTP_{login}_{magic}_{ticket}`).
- **`EquityCurveFilter.mqh`** — Filtro de curva de equity (`CEquityCurveFilter`):
  calcula EMA exponencial del equity; reduce el tamaño de posición al 50% cuando
  `equity < EMA`. EMA persiste via `GlobalVariable` entre reinicios.
- **`GoldenTradeX.mq5`** — Anclaje estructural de SL (Fibonacci swing points):
  el SL se ancla al swing low/high de `FibonacciEngine` cuando éste da más margen
  que el SL basado en ATR (mayor protección estructural).

### Added — SignalEngine
- **`SignalEngine.mqh`** — Filtro de volumen mínimo de ticks (`InpMinTickVolume`):
  bloquea señales en barras con volumen de ticks inferior al umbral configurado,
  evitando falsas señales en barras de escasa liquidez (default=10).

### Added — Python
- **`scripts/session_analyzer.py`** — Análisis de rendimiento por sesión y hora:
  desglosa trades por sesión (Asian/London/NY/Overlap) y por hora de cierre.
  Genera heatmap horario de texto, tabla por sesión (PF, WR%, NetP/L, AvgR).
  Flags `--utc-offset` (default +3, EET/XM), `--output`.
- **`scripts/walk_forward_optimizer.py`** — Optimizador walk-forward por ventana deslizante:
  ventana IS + ventana OOS, grid search de `InpMinConfidence`, calcula eficiencia OOS/IS.
  Flags `--is-months`, `--oos-months`, `--step-months`, `--threshold-step`, `--metric`,
  `--output`. Recomienda el umbral más estable y valida en OOS combinado.

### Changed — Python
- **`scripts/backtest_analysis.py`** — Sharpe ratio ahora usa **buckets diarios** de P&L
  con factor de anualización `sqrt(252)`, en lugar de Sharpe per-trade que sobreestima.
- **`scripts/backtest_analysis.py`** — Monte Carlo ahora usa **bootstrap con reposición**
  (`random.choice`) en lugar de solo permutación (shuffle), modelando correctamente
  secuencias de retornos con reemplazo.

### Changed — Infrastructure
- **`.github/workflows/ci.yml`** — Syntax check extendido a `session_analyzer.py` y
  `walk_forward_optimizer.py`; structure-check extendido a `PartialTakeProfit.mqh`,
  `EquityCurveFilter.mqh`, `session_analyzer.py`, `walk_forward_optimizer.py`.
- **`scripts/validate_set.py`** — Añadidos 6 nuevos parámetros v2.20 a `REQUIRED` y
  `RANGE_CHECKS`: `InpUsePartialTP`, `InpPartialTPR`, `InpPartialTPPct`,
  `InpUseEqCurveFilter`, `InpEqCurvePeriod`, `InpMinTickVolume`.
- **`config/GoldenTradeX.set`** / **`config/GoldenTradeX_XAGUSD.set`** — Añadidos
  los 6 nuevos parámetros v2.20 con valores por defecto recomendados.

---

## [2.10] — 2026-07-30

### Added — MQL5
- **`FibonacciEngine.mqh`** — Fibonacci confluence module (score 0-20):
  Detects swing high/low (3-bar fractal, lookback=100), calculates 7 levels
  (23.6%, 38.2%, 50%, 61.8%, 78.6%, 127.2%, 161.8%), identifies Premium/Discount
  zones, finds nearest level within ATR×0.5. `FibScore(ctx, isBuy)` awards
  38.2%/61.8%=20, 50%=15, 23.6%/78.6%=10, extensions=5; halved if price
  is in the wrong zone for the trade direction.
- **`TestSessionFilter.mq5`** — 22 unit tests for `CSessionFilter`:
  disabled filter (4 cases), standard session boundaries, weekend blocks,
  friday close logic, `MustCloseAll()`, closeFriday=false, edge hours,
  full weekday coverage. Testable subclass with injected datetime.

### Added — Python
- **`scripts/correlation_engine.py`** — Macro correlation analysis (requires yfinance):
  Downloads XAUUSD, DXY, VIX, US10Y, SP500; calculates full-period Pearson and
  rolling Pearson (default 30d window); DXY-regime breakdown; actionable signals
  (inverse DXY threshold, risk-off VIX, stagflation regime); CSV cache for offline.
- **`scripts/optimize_confidence.py`** — Grid search for optimal `InpMinConfidence`:
  Evaluates threshold 0-90 (step=5) by PF, Sharpe, Net P/L, Max DD; balanced
  recommendation at PF≥1.5 AND kept≥40%; `--metric` flag; CSV output.
- **`scripts/fomc_calendar.py`** — FOMC calendar updater:
  Hardcoded 2025-2027 dates; optional live scrape from federalreserve.gov
  (requires requests, beautifulsoup4); upcoming meetings with countdown;
  generates ready-to-paste MQL5 `IsFomcDay()` code block.

### Changed — Python
- **`scripts/backtest_analysis.py`** — Added `--html-output` flag:
  Generates a self-contained HTML report (no CDN) with SVG equity curve,
  SVG walk-forward bar chart, KPI grid, Monte Carlo grid, institutional
  targets checklist. Pure stdlib, no external dependencies.

### Changed — Infrastructure
- **`.github/workflows/ci.yml`** — Python syntax check extended to cover
  `correlation_engine.py`, `optimize_confidence.py`, `fomc_calendar.py`;
  structure-check extended to cover `FibonacciEngine.mqh`,
  `TestSessionFilter.mq5`, `TestFibonacci.mq5`, and all 3 new Python scripts.

### Changed — ConfidenceEngine (arquitectura)
- **`ConfidenceEngine.mqh`** — `atrBonus` (calidad ATR, 0-5) reemplazado por
  `fibBonus` (confluencia Fibonacci, 0-5). Score total sigue siendo 0-100.
  Mapeo: FibScore 0-20 → fibBonus 0-5 (÷4). `atrPeriod` eliminado de `Init()`.
- **`GoldenTradeX.mq5`** — incluye `FibonacciEngine.mqh`, instancia
  `CFibonacciEngine fibEngine`, llama `Analyze()` + `FibScore()` en cada señal
  y pasa el resultado a `confEngine.Compute()` como 5to parámetro.
- **`TestFibonacci.mq5`** — 21 unit tests: Init, contexto inválido, scores
  por nivel, penalización Premium/Discount, cap en 20, simetría 38.2%↔61.8%.

---

## [2.00] — 2026-06-15

### Added — MQL5
- **`MarketRegimeEngine.mqh`** — Motor de detección automática de régimen de mercado.
  7 estados: `TRENDING_BULL`, `TRENDING_BEAR`, `RANGING`, `VOLATILE`, `ACCUMULATION`,
  `DISTRIBUTION`, `UNKNOWN`. Basado en ADX, ATR ratio, Bollinger Band Width y slope de EMA.
  `RegimeScore(isBuy)` retorna 0-25 según alineación con la dirección de la operación.
  Bloqueo automático en `VOLATILE`.
- **`SmartMoneyEngine.mqh`** — Smart Money Concepts completo:
  - **BOS** (Break of Structure): detecta ruptura de swing high/low previo
  - **CHOCH** (Change of Character): cambio de estructura de mercado
  - **FVG** (Fair Value Gap): gap de 3 velas alcista y bajista
  - **Order Blocks**: última vela contratendencia antes del BOS
  - **Liquidity Sweeps**: barrido de swing con reversión intrabar
  - `SmcScore(ctx, isBuy)` retorna 0-30 según confluencia con la dirección
- **`ConfidenceEngine.mqh`** — Ensemble Confidence Score 0-100:
  `BaseSignal(25) + RegimeBonus(25) + SmcBonus(30) + HtfBonus(15) + AtrBonus(5)`
  Solo se ejecuta la operación si `score >= InpMinConfidence`.
- **`TestMarketRegime.mq5`** — Tests unitarios para los 3 nuevos módulos:
  `RegimeToString`, inicialización, `Compute()` sin señal base = 0,
  `SmcScore()` con contextos neutro/máximo/bull/sell.
- **`docs/ARCHITECTURE.md`** — Diagrama de arquitectura completo, flujo de decisión,
  desglose del Confidence Score, lógica SMC y roadmap a producción.

### Added — Python
- **`scripts/regime_analysis.py`** — Análisis estadístico por régimen de mercado.
  Lee el campo `Comment` del CSV (formato `GTX|Conf=N|Reg=X`), agrupa trades por
  régimen y confidence band, genera stress test (sin top-N trades).
- **`scripts/ml_pipeline.py`** — Pipeline completo de Machine Learning (XGBoost).
  15 features de ingeniería: confidence score, régimen, hora cíclica, día/mes cíclico,
  R anterior, racha, win rate 10 trades. Split temporal (no aleatorio). Evaluación con
  Accuracy, Precision, Recall, AUC-ROC. Feature importance. Export del modelo a JSON.
- **`dashboard/index.html`** — Dashboard web estático (sin servidor):
  equity curve, 8 KPIs, P/L por régimen, win rate por confidence band,
  P/L mensual, checklist institucional, tabla de últimos 30 trades.
  Carga CSV via drag-and-drop o selector. Chart.js CDN.

### Changed — MQL5
- **`GoldenTradeX.mq5`** v1.42 → **v2.00**: integra `MarketRegimeEngine`,
  `SmartMoneyEngine` y `ConfidenceEngine`. Nuevos inputs:
  `InpUseRegimeFilter`, `InpUseSmcFilter`, `InpMinConfidence`.
  El comentario de cada trade incluye `|Conf=N|Reg=REGIME` para trazabilidad.
- **`RiskManager.mqh`** — Añadidos:
  - Circuit Breaker mensual (`InpMaxMonthlyDD`, persiste con GlobalVariable)
  - Kill Switch de emergencia (`SetKillSwitch(bool)`)
  - Capital Preservation Mode (activa riesgo 25% cuando DD diario ≥ `InpCpThresholdPct`)
  - `PrintStatus()` para diagnóstico en Journal

### Changed — Infraestructura
- **`config/GoldenTradeX.set`** y **`GoldenTradeX_XAGUSD.set`** — nuevos parámetros v2.00
- **`scripts/validate_set.py`** — validación de los 5 nuevos parámetros v2.00
- **`.github/workflows/ci.yml`** — 5 jobs: +syntax check para nuevos scripts,
  +estructura para nuevos archivos requeridos, +dashboard validation job
- **`requirements.txt`** — añadidos `xgboost>=2.0.0`, `scikit-learn>=1.4.0`

---

## [1.42] — 2026-06-12

### Added
- **`scripts/backtest_analysis.py`** — herramienta de análisis estadístico post-backtest
  (stdlib puro, sin numpy/pandas). Lee los CSV de TradeLogger y calcula:
  - Métricas core: win rate, profit factor, Sharpe anualizado, max drawdown, R-múltiplo
    promedio, ganancia/pérdida media, ratio R:R realizado, recovery factor, pérdidas
    consecutivas máximas.
  - **Monte Carlo** (default 1 000 simulaciones, seed configurable): shufflea la secuencia de
    trades N veces y reporta distribución del max DD (P5/P25/P50/P75/P95) y probabilidad
    de ruina (DD ≥ 40 %).
  - **Walk-forward por trimestre**: métricas por ventana temporal (N, WR%, PF, Net P/L,
    AvgR, Sharpe).
  - **Checklist institucional**: PF ≥ 1.8, Sharpe ≥ 1.5, WR ≥ 45 %, Max DD ≤ 15 %,
    MC DD P95 ≤ 25 %, MC ruina < 5 %, recovery factor ≥ 3, pérd. consec. ≤ 5.
  - Opción `--output report.csv` para exportar tabla walk-forward.
  - Auto-descubre archivos `GoldenTradeX_*.csv` en el directorio actual.
- **`config/GoldenTradeX_XAGUSD.set`** — preset para operar en XAGUSD (Plata) M15.
  Magic number `920261` (permite instancia simultánea con XAUUSD), spread máximo
  500 pts (ajustar al broker). El cálculo de lote usa el ATR del símbolo, adaptándose
  automáticamente a la mayor volatilidad de la plata.

---

## [1.41] — 2026-06-12

### Added
- **Alertas Telegram en `monitor.py`** (`TelegramNotifier`): envía mensajes HTML al bot
  configurado vía `--telegram-token` / `GTX_TG_TOKEN` y `--telegram-chat-id` / `GTX_TG_CHAT_ID`.
  Eventos cubiertos:
  - Monitor iniciado, detenido y reconectado.
  - Posición abierta: lado, volumen, símbolo, precio de entrada, SL y TP.
  - Posición cerrada: P/L en moneda y porcentaje sobre balance.
  - Caída de equity ≥ `--alert-dd-pct` (default 2 %); se auto-resetea al recuperar la mitad.
- `MonitorState` dataclass: rastrea snapshots anteriores de posiciones y referencias
  de equity/balance para detectar cambios entre ciclos.
- Arg `--alert-dd-pct` / env `GTX_ALERT_DD_PCT`.
- `requirements.txt` — añadido `requests>=2.31.0`.

### Changed
- `monitor.py` refactorizado: funciones `_snap()`, `snapshot()` reciben `state` y `notifier`
  para permitir pruebas unitarias sin efectos secundarios.

---

## [1.40] — 2026-06-12

### Added
- **TradeLogger.mqh** — escribe una fila CSV por cada posición cerrada en
  `<Terminal_Files>/GoldenTradeX_{login}_{symbol}_{year}.csv` (archivo compartido `FILE_COMMON`).
  Columnas: `CloseDate`, `CloseTime`, `PositionID`, `Symbol`, `Type`, `Lots`,
  `OpenPrice`, `InitialSL`, `InitialTP`, `ClosePrice`, `ProfitLoss`, `Commission`, `RMultiple`.
  R-múltiplo calculado internamente; fichero por cuenta/símbolo/año para evitar archivos gigantes.
- **TestNewsFilter.mq5** (`MQL5/Scripts/Tests/`) — 18 asserts que cubren:
  NFP (primer viernes de mes), FOMC 2025/2026, CPI proxy (mar/mié días 10–15),
  filtro desactivado.
- **TestRiskManager.mq5** (`MQL5/Scripts/Tests/`) — tests de caja blanca:
  contador de pérdidas consecutivas, multiplicador 0.75 al llegar a ≥ 2 pérdidas,
  `IsConsecutiveLossLimitReached()`.
- `NewsFilter.mqh` — nuevo método `IsNewsBlockedAt(datetime t)` (evalúa una datetime
  arbitraria) y `SetServerOffset(int offset)` (inyección de offset UTC para tests).
- Input `InpEnableTradeLog` (default `true`) en el EA principal.
- **CI/CD GitHub Actions** (`.github/workflows/ci.yml`): Python lint (flake8),
  validación de config `.set`, verificación de estructura del repositorio,
  consistencia de versión EA ↔ CHANGELOG.
- `scripts/validate_set.py` — valida presencia y rangos de todos los parámetros del preset.
- `requirements.txt` — `MetaTrader5>=5.0.45`.

### Changed
- `GoldenTradeX.mq5` v1.30 → v1.40: incluye `TradeLogger.mqh`, instancia `CTradeLogger`,
  llama `tradeLogger.LogTrade(dealTicket)` en `OnTradeTransaction`.

---

## [1.30] — 2026-06-11

### Added
- **NewsFilter.mqh** — filtro automático de calendario: NFP (primer viernes de mes,
  13:30 UTC), FOMC 2025/2026 (fechas hardcodeadas, 19:00 UTC), CPI proxy
  (mar/mié días 10–15, 13:30 UTC). Offset UTC → servidor auto-detectado.
  `PrintStatus()` imprime diagnóstico en el Journal al inicializar.
- Input `InpUseNewsFilter`, `InpNewsBufferBefore` (30 min), `InpNewsBufferAfter` (90 min),
  `InpPauseForNews` (override manual).
- **Break-even automático** — `InpUseBreakEven` (default `true`), `InpBreakEvenR = 0.5`:
  mueve el SL al precio de apertura cuando la posición alcanza +0.5R de flotante.
  Lógica en `ManageTrailing()` con `continue` para evitar doble modificación en el mismo tick.

### Changed
- `GoldenTradeX.mq5` v1.20 → v1.30.

---

## [1.20] — 2026-06-10

### Added
- **ADX regime filter** — `InpAdxMinLevel = 25.0`: bloquea entradas en mercados laterales.
  Indicador `iADX(symbol, tf, 14)`, lee barra 1 (confirmada).
- **ATR max ratio** — `InpAtrMaxRatio = 3.0`: bloquea entradas durante spikes de noticias
  (ATR actual > 3× ATR_SMA). Complementa el filtro mínimo ya existente.
- **Drawdown semanal** — `InpMaxWeeklyDD = 8.0 %` con persistencia via GlobalVariable
  (`GTX_{login}_{magic}_Week` / `_WeekEquity`). Índice semana = `year*100 + dayOfYear/7`.
- **Límite de pérdidas consecutivas** — `InpMaxConsecLosses = 3`: pausa el EA hasta nueva semana.
  `GetPositionSizeMultiplier()` reduce tamaño al 75 % desde la 2ª pérdida consecutiva.
- **H4 HTF trend filter** — `InpUseHtfFilter = true`, `InpHtfEmaPeriod = 50`:
  precio H4 debe estar por encima/debajo de EMA50-H4 para longs/shorts.
- Caché de ATR por barra (`m_cachedAtr`, `m_cachedAtrBar`) — evita recalcular en cada tick.
- Confirmación de cruce EMA en barra 0 (verifica que el cruce no se haya revertido).

### Fixed
- `CalculateLotSize` devuelve 0 si el lote calculado es menor que el mínimo del broker
  (antes se forzaba al mínimo causando sobreapalancamiento en cuentas pequeñas).
- Precisión dinámica de decimales de lote según `lotStep` del broker.

---

## [1.10] — 2026-06-09

### Fixed
- `IsDailyDrawdownExceeded()` — corregido reset de equity base cuando el índice de día
  cambia (antes podía comparar contra equity de un día anterior).
- `ManageTrailing()` — condición `sl == 0` añadida para posiciones SELL sin SL inicial
  explícito (evitaba que el trailing se activara).
- `GetEntryData()` en `RiskManager` — ahora itera sobre todos los deals de la posición
  con `HistorySelectByPosition` en lugar de asumir que el primer deal es siempre de entrada.
- `OnTradeTransaction` — guard añadido para `DEAL_ENTRY_INOUT` además de `DEAL_ENTRY_OUT`.

---

## [1.00] — 2026-06-08

### Added
- Arquitectura inicial del EA: `GoldenTradeX.mq5`, `SignalEngine.mqh`,
  `RiskManager.mqh`, `SessionFilter.mqh`.
- Estrategia: cruce EMA21/55 + RSI momentum (45–70 longs / 30–55 shorts) en M15.
- Gestión de riesgo: lote por % de equity (1 %), SL = ATR×2, TP = ATR×3.
- Drawdown diario máximo (4 %) persistido con GlobalVariable.
- Trailing stop ATR×1.5 activado desde +1R.
- Filtro de sesión Londres–NY (07–20 h servidor), cierre de viernes a las 19 h.
- Monitor externo en Python (`scripts/monitor.py`) con reconexión automática y logging.
- Preset inicial `config/GoldenTradeX.set`.
- Documentación de estrategia `docs/STRATEGY.md`.
