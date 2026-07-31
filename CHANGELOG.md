# Changelog

All notable changes to Golden Trade X are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.61] — 2026-07-31

Auditoría crítica multidimensión (seguridad, riesgo, automatización, datos,
indicadores, fundamental) — barrido completo P0+P1+P2.

### Fixed — Crítico (operación desatendida)
- **Fuga de presupuesto en el Portfolio Risk Cap** (`RiskManager.mqh`):
  si una posición se cerraba con el terminal apagado (SL/TP se ejecutan en
  el servidor del broker), `OnTradeTransaction` no se re-dispara al
  reiniciar → la reserva de riesgo quedaba huérfana en la GlobalVariable
  para siempre, llenando el presupuesto de posiciones fantasma hasta
  bloquear trades legítimos. Nueva `ReconcilePortfolioRisk()` en el
  arranque: enumera las reservas `GTX_<login>_PR_*`, elimina las de
  tickets inexistentes y reconstruye el total desde las supervivientes.

### Fixed — Análisis fundamental
- **`NewsFilter.mqh` cubre FOMC 2027** (8 fechas proyectadas, sincronizadas
  con `fomc_calendar.py` — el dato ya existía en el repo y el EA no lo
  usaba). `FOMC_LAST_YEAR` → 2027. Verificar contra federalreserve.gov
  cuando la Fed publique el calendario oficial.
- **`fomc_calendar.py` genera el bloque MQL5 con la firma real** de
  `NewsFilter.IsFomcDay(int, int, int)` — antes generaba
  `IsFomcDay(datetime)`, que no compilaba al pegarlo. Incluye ahora el
  aviso de cobertura y recuerda actualizar `FOMC_LAST_YEAR`.

### Fixed — Seguridad
- **Token de Telegram redactado en logs** (`monitor.py`, `live_monitor.py`):
  las excepciones de red incluyen la URL completa — que contiene el token —
  y se escribían en texto plano en `monitor.log`/stdout.
- **SRI (Subresource Integrity) en el dashboard**: el `<script>` del CDN de
  Chart.js lleva hash `sha384` + `crossorigin` — un CDN comprometido ya no
  puede inyectar JS (el navegador rechaza el archivo y se muestra el aviso
  de "CDN no cargó").
- `.env.example` y `--help` advierten no pasar el token por CLI (queda en
  historial de shell y lista de procesos).

### Fixed — Indicadores / análisis técnico
- **Períodos de indicadores propagados a todos los motores**: `InpAtrPeriod`
  ahora gobierna el ATR de `MarketRegimeEngine`, `SmartMoneyEngine`,
  `FibonacciEngine` y `HealthMonitor` (antes 14 fijo — cambiar el input
  dejaba al EA operando con dos ATRs distintos en silencio). Nuevo
  `InpAdxPeriod` (default 14) para `SignalEngine` y `MarketRegimeEngine`.
  Bollinger (20, 2.0) sigue fijo: interno a la clasificación de régimen.

### Fixed — Automatización / análisis de datos
- **Variables de entorno unificadas**: `monitor.py` acepta las canónicas
  de `.env.example` (`GTX_TELEGRAM_*`, las mismas de `live_monitor.py`)
  además de las legacy (`GTX_TG_*`) — antes configurar el `.env` según la
  plantilla dejaba a `monitor.py` sin alertas, sin error visible.
- `.env.example` documenta la ruta real de los CSV desde v2.51
  (`Common\Files` del terminal) y añade la sección de `monitor.py`.
- **`walk_forward_optimizer.py` excluye los trades sin confidence** del
  barrido (CSVs de TradeLogger < v2.50) con aviso — el default anterior
  (conf=100) los hacía pasar todos los umbrales, sesgando la optimización
  hacia umbrales altos.

### Fixed — Documentación / herramientas
- `docs/STRATEGY.md` reescrito: describía solo la estrategia v1.x (9
  filtros); ahora documenta las 3 capas (guardianes, señal base,
  Confluence Score), salidas, gestión de capital completa (Kelly,
  Portfolio Cap, Equity Filter), plan de validación alineado con las
  herramientas reales y riesgos conocidos honestos.
- Dashboard: badge de versión estático "v2.00" eliminado (etiqueta neutra)
  y "Objetivos Institucionales" → "Objetivos internos de calidad".
- Tests MQL5: casos nuevos de reconciliación implícita vía
  register/release en `TestRiskManager.mq5` (de v2.60) siguen válidos.

---

## [2.60] — 2026-07-31

Plan de trabajo ejecutado a partir de una revisión crítica externa (evaluación
cuantitativa independiente del repositorio). Se implementó todo lo accionable
por código; lo que requiere datos reales o infraestructura externa (backtest
limpio, 300+ trades para Kelly, runner Windows para compilar en CI) queda
documentado como pendiente, no simulado.

### Added — Portfolio Risk Cap
- **`RiskManager.mqh`**: límite de riesgo agregado entre TODAS las instancias
  del EA en la misma cuenta (p.ej. XAUUSD + XAGUSD en paralelo, que están
  correlacionados y antes gestionaban su drawdown de forma completamente
  aislada). `RegisterOpenRisk`/`ReleaseOpenRisk`/`GetPortfolioRiskUsed` vía
  GlobalVariable compartida por cuenta (no por magic number).
  `CalculateLotSize` reduce u omite el trade si excede el presupuesto.
- **`OrderManager.mqh`**: `GetLastPositionTicket()` para conocer el ticket
  de la posición recién confirmada.
- Nuevos inputs: `InpUsePortfolioCap` (OFF por defecto), `InpMaxPortfolioRiskPct`.
- Tests unitarios para Register/Release/GetUsed/GetAvailable en `TestRiskManager.mq5`.

### Changed — Confluence Score (antes "Ensemble")
- **`ConfidenceEngine.mqh`** renombrado de "Ensemble Score" a **"Confluence
  Score" heurístico** en toda la documentación — es un puntaje por
  confluencia de filtros con pesos elegidos a mano, no un ensemble
  estadístico calibrado con datos.
- Los 5 pesos del score (`InpConfWeightBase/Regime/Smc/Htf/Fib`) ahora son
  **inputs del EA**, para que puedan optimizarse con datos reales via
  Strategy Tester. Los defaults (25/25/30/15/5) preservan exactamente el
  comportamiento de versiones anteriores (factor de escala 1.0).

### Added — Métricas de riesgo estadísticamente honestas
- **`scripts/backtest_analysis.py`**:
  - Sharpe/Sortino sobre **retornos % diarios** (no P&L absoluto) — evita
    distorsión cuando el equity o el lote cambian durante el test (Kelly,
    Equity Curve Filter).
  - Nuevas métricas: Sortino ratio, Calmar ratio (CAGR/MaxDD), Ulcer Index,
    Expected Shortfall (CVaR 95%).
  - **Probabilistic Sharpe Ratio (PSR)** y **Deflated Sharpe Ratio (DSR)**
    (Bailey & López de Prado): probabilidad de que el Sharpe real sea
    positivo, corregida por sesgo de selección con `--trials N`.
  - Monte Carlo con **block bootstrap** (`--block-size N`): preserva
    autocorrelación/rachas que el bootstrap IID de trade individual (aún
    el default, `--block-size 1`, sin cambios de comportamiento) ignora.
  - Sección renombrada de "OBJETIVOS INSTITUCIONALES" a "OBJETIVOS
    INTERNOS DE CALIDAD" — son umbrales propios del proyecto, no una
    certificación institucional externa. Se agregó el check PSR ≥ 95%.
  - Reporte HTML incluye las nuevas métricas de riesgo.
- **28 tests nuevos** en `tests/test_backtest_analysis.py` (69 en total).

### Fixed — Observabilidad
- **`SessionFilter.mqh`**: detecta y advierte en el Journal cuando el
  offset servidor-UTC cambia entre inicializaciones (cambio de DST) —
  antes el desfase horario de la sesión Londres-NY pasaba en silencio.
  No cambia el comportamiento de trading (sigue en hora de servidor por
  diseño), solo alerta para que el operador revise `InpStartHour/EndHour`.

### Fixed — Documentación
- **`README.md`** reescrito por completo: describía la arquitectura de
  v1.x (solo 5 módulos) mientras el código ya tenía 14. Ahora refleja
  v2.60, incluye advertencias metodológicas explícitas (Confluence Score
  heurístico, walk-forward real vs. desglose trimestral, bootstrap IID
  vs. block) y elimina el ejemplo de backtest sin evidencia detrás.

---

## [2.51] — 2026-07-30

Autoauditoría post-v2.50 + evaluación continua de desempeño.

### Fixed — Autoauditoría
- **Neto de la posición completa en `OnTradeTransaction`**: al cerrar un
  trade que tuvo cierre parcial, `RegisterTradeResult` ahora recibe la suma
  de TODOS los deals de salida de la posición (parcial + final). Antes, un
  trade con parcial de +0.5R que cerraba el resto en break-even se contaba
  como pérdida para el contador de pérdidas consecutivas.
- **`TradeLogger` registra totales de la POSICIÓN**: `Lots` = volumen de
  entrada, `ProfitLoss`/`Commission` = suma de todos los deals de salida
  (incluye swap). Antes el CSV solo veía el deal final — un trade con
  parcial ocultaba la mitad de su P/L a toda la capa analítica.
- **Chequeo de margen libre en `CalculateLotSize`** (`OrderCalcMargin`,
  tope 80% del margen libre): reduce el lote u omite el trade con log.
  Antes, una cuenta justa de margen recibía `10019 NO_MONEY` — clasificado
  como error fatal — y el Kill Switch detenía el EA.
- **`PartialTP` marca como resuelto los lotes no divisibles** (p.ej. 0.01
  con minLot 0.01) con un aviso único en el Journal, en vez de re-evaluar
  la misma posición imposible de partir en cada tick.

### Added — Evaluación continua de desempeño
- **`scripts/performance_report.py`** — monitor de desempeño recurrente
  sobre los CSV del TradeLogger:
  - Ventana reciente (últimos N trades) vs baseline histórico → alertas de
    DEGRADACIÓN (caída de win rate, expectancy negativa, PF < 1).
  - Drawdown ACTUAL desde el pico (no solo el máximo histórico).
  - Racha de pérdidas abierta.
  - Breakdown por régimen de mercado y banda de confianza (columna
    `Comment` v2.50) — muestra qué filtros aportan y cuáles restan.
  - Breakdown por hora y día de APERTURA.
  - `--watch N`: re-evaluación automática cada N segundos (modo monitor).
  - `--json`: export para el dashboard u otras herramientas.
  - Exit code 1 con alertas → integrable en cron/Task Scheduler.
- **`tests/test_performance_report.py`** — 13 tests (parsing de Comment,
  métricas de bloque, detección de degradación, breakdowns). Total: 41.
- CI `structure-check` incluye los scripts y tests nuevos.

---

## [2.50] — 2026-07-30

Revisión crítica integral: 20+ correcciones de correctitud, ejecución,
calidad de datos y tooling. Sin cambios de estrategia de entrada.

### Fixed — Crítico (comportamiento en vivo)
- **Cascada de cierres parciales** (`GoldenTradeX.mq5` / OnTradeTransaction):
  un cierre parcial genera un deal `DEAL_ENTRY_OUT` igual que un cierre total.
  El EA lo trataba como trade cerrado: borraba el flag del Partial TP
  (reactivándolo en cascada hasta agotar el lote), contaba el parcial como
  trade ganador (desarmando el contador de pérdidas consecutivas e inflando
  el win rate de Kelly) y lo registraba en el CSV. Ahora, si la posición
  sigue viva tras el deal, no se procesa como cierre.
- **Kelly agregado por posición** (`RiskManager.mqh`): W y R se calculan
  agrupando deals por `POSITION_ID` — un trade con parciales cuenta una vez
  con su neto total. Sin pérdidas (o sin ganancias) en la ventana → fallback
  a riesgo fijo en vez de inventar un ratio con `avgL=1`.
- **`SYMBOL_TRADE_STOPS_LEVEL` respetado** (`OrderManager.mqh`): SL/TP se
  ajustan a la distancia mínima del broker antes de enviar (open y modify).
  Antes, stops demasiado cercanos devolvían `10016 INVALID_STOPS`
  (no-reintenable) y la orden/modificación se descartaba en silencio.
- **Break-even con buffer** (`GoldenTradeX.mq5`): el BE ahora mueve el SL a
  `openPrice ± 0.1×ATR` en vez de exactamente `openPrice` — BE exacto dejaba
  pérdida neta (spread + comisión) al saltar.
- **Índice de semana estable en cambio de año** (`RiskManager.mqh`): semana
  absoluta desde epoch alineada a lunes. La fórmula anterior partía la misma
  semana operativa en dos al cruzar el año (reset espurio del DD semanal).
- **Resultado neto en pérdidas consecutivas** (`GoldenTradeX.mq5`):
  `RegisterTradeResult` ahora recibe profit+comisión+swap — la misma
  definición de "ganador" que usa Kelly.

### Fixed — Indicadores y contexto
- **Handles ATR cacheados** en `FibonacciEngine`, `SmartMoneyEngine` y
  `HealthMonitor` (creados en `Init()`, liberados en `Release()`). El patrón
  anterior (crear handle + CopyBuffer + release por barra) puede devolver 0
  si el indicador no calculó aún → caía a fallbacks silenciosos.
- **`HealthMonitor` usa el timeframe del EA** (antes: `PERIOD_M15` fijo).
- **Swings solo sobre barras cerradas** (`SmartMoneyEngine`,
  `FibonacciEngine`): la barra 0 en formación quedaba incluida en la
  detección → el contexto SMC/Fib cambiaba intra-barra con cada tick.
- **`EquityCurveFilter` muestreado por barra** (`Sample()` en cada barra
  nueva + `GetMultiplier()` al abrir). Antes la "EMA(20) de equity" se
  actualizaba solo antes de cada apertura → medía las últimas 20 aperturas,
  no la curva de equity.
- **`ConfidenceEngine`: bonus HTF graduado** (0/8/15 según alineación y
  pendiente de la EMA H4). Con el filtro HTF duro activo, el bonus fijo de
  15 era una constante sin poder discriminante.
- **`NewsFilter`: aviso de cobertura FOMC agotada** — a partir de 2027 el
  EA imprime una alerta única en el Journal en vez de fallar en silencio.

### Fixed — Capa de datos y análisis
- **`TradeLogger` añade columnas `OpenDate`, `OpenTime`, `Comment`**: el
  Confidence Score y el régimen viajan ahora al CSV (antes `ml_pipeline.py`
  leía una columna inexistente → confidence=50 y regime=UNKNOWN constantes).
- **`ml_pipeline.py`: features temporales sin leakage** — hora/día/mes se
  toman de la APERTURA (con fallback a cierre para CSVs antiguos, avisando).
  Eliminado `use_label_encoder` (removido en XGBoost 2.0).
- **`HealthMonitor` escribe el status CSV en `Common\Files`** (FILE_COMMON),
  la misma carpeta que TradeLogger — `live_monitor.py` encuentra ambos
  archivos en un único directorio.

### Added — Tooling y CI
- **`scripts/mql5_lint.py`** — linter estático MQL5 para CI: detecta las
  clases de error que causaron los 77 errores de compilación de v2.30
  (indicadores con firma MQL4, `->`, `ArraySetAsSeries` sobre arrays
  estáticos, `ResultRetcodeDescription`). Nuevo job `mql5-lint`.
- **CI migrado de flake8 a ruff** y Python 3.11 → 3.12.
- **`.github/dependabot.yml`** — actualizaciones semanales de pip y actions.
- **`requirements.txt` acotado con `~=`** para builds reproducibles.
- **Dashboard: aviso visible si el CDN de Chart.js no carga** (uso offline).

### Fixed — Configuración
- `GoldenTradeX_XAGUSD.set` — añadidos parámetros Kelly (faltaban → CI en
  rojo desde v2.40) y sección Order Manager.
- `GoldenTradeX.set` — añadida sección Order Manager
  (`InpOrderMaxRetries`, `InpOrderRetryDelay`, `InpMinMarginLevel`).
- `validate_set.py` valida los 3 parámetros de Order Manager en ambos presets.
- `docs/ARCHITECTURE.md` y `docs/STRATEGY.md` ya no fijan versión en el
  título (quedaban desactualizados en cada release).

---

## [2.40] — 2026-07-31

### Added — Kelly Criterion Fraccional
- **`RiskManager.mqh`** — Kelly Criterion fraccional dinámico:
  - Calcula W (win rate) y R (avg win / avg loss) desde historial real de trades
    del EA (últimos 90 días, filtrado por magic number).
  - Fórmula: `f* = W − (1−W)/R` (Kelly completo), luego aplicada la fracción.
  - `InpKellyFraction=0.25` por defecto (Quarter-Kelly — máxima seguridad).
  - `InpKellyMinTrades=30` — fallback a riesgo fijo si historial insuficiente.
  - Techo de seguridad: Kelly nunca supera `InpRiskPercent × 2`.
  - Capital Preservation Mode reduce Kelly al 25% igual que riesgo fijo.
  - Sin edge detectado (f*≤0): reduce riesgo al 50% automáticamente.
  - Log en Journal: `W%`, `R`, `f*`, riesgo efectivo en cada apertura.
- **Inputs nuevos:** `InpUseKelly`, `InpKellyFraction`, `InpKellyMinTrades`
- `config/GoldenTradeX.set` actualizado con parámetros Kelly (off por defecto)
- `scripts/validate_set.py` valida los 3 nuevos parámetros

---

## [2.30] — 2026-07-30

### Added — MQL5 (Production-Grade Execution)
- **`OrderManager.mqh`** — Gestor de órdenes production-grade (`COrderManager`):
  - Retry automático hasta `InpOrderMaxRetries` veces con delay configurable.
  - Clasificación de errores: retryable (requote, price_changed, price_off,
    too_many_requests, connection), fatal (no_money, trade_disabled, frozen).
  - Errores fatales activan automáticamente el Kill Switch.
  - Validación obligatoria SL≠0 y TP≠0 antes de enviar cualquier orden.
  - Validación de dirección SL/TP (BUY: SL<price y TP>price; SELL: inverso).
  - Seguimiento de slippage: último y promedio (en puntos).
  - Estadísticas de ejecución: intentos totales, éxitos, fallos.
- **`HealthMonitor.mqh`** — Monitor de salud periódico (`CHealthMonitor`):
  - Llamado desde `OnTimer()` cada 60 segundos.
  - Detección y corrección automática de posiciones huérfanas (SL=0):
    aplica SL de emergencia a 3×ATR por encima/debajo del precio de apertura.
  - Verificación de nivel de margen: alerta si margin_level < umbral configurable.
  - Verificación de conexión al broker.
  - Escritura de archivo de estado CSV (`GTX_{magic}_status.csv`) en la carpeta
    Files del terminal para lectura por `scripts/live_monitor.py`.
- **`GoldenTradeX.mq5`** — v2.30:
  - Integra `COrderManager` en todas las operaciones (open, modify, close).
  - Integra `CHealthMonitor` vía `OnTimer()`.
  - Añade `OnTimer()` con período de 60 segundos.
  - Validación de cuenta en `OnInit()`: modo DEMO/REAL, trading permitido,
    MQL_TRADE_ALLOWED. El EA imprime el tipo de cuenta al arrancar.
  - Activación automática del Kill Switch ante errores fatales del broker.
  - Nuevos inputs: `InpOrderMaxRetries` (3), `InpOrderRetryDelay` (500ms),
    `InpMinMarginLevel` (200%).

### Added — MQL5 Tests
- **`TestOrderManager.mq5`** — 19 unit tests para `COrderManager`:
  clasificación retryable/fatal/success de 7 códigos de retorno MQL5,
  validación SL/TP con 10 casos (BUY y SELL con SL/TP válidos e inválidos),
  estadísticas iniciales (success=0, fail=0, slippage=0).

### Added — Python
- **`scripts/live_monitor.py`** — Monitor en tiempo real con alertas Telegram:
  - Detecta nuevos trades en `GoldenTradeX_*.csv` (polling configurable, default 10s).
  - Envía alertas Telegram estructuradas (HTML) por cada trade cerrado.
  - Alerta de racha de pérdidas consecutivas (umbral configurable).
  - Lee archivo de estado del EA (`GTX_{magic}_status.csv`) y alerta sobre
    condiciones de salud (margen bajo, desconexión, SL huérfano).
  - Configuración completa via variables de entorno / `.env`.
  - Modo `--dry-run` para probar alertas sin enviar al Telegram.
- **`tests/test_backtest_analysis.py`** — 28 tests pytest para funciones críticas:
  `equity_curve` (4), `max_drawdown` (4), `profit_factor` (4), `daily_sharpe`
  (4 incluyendo agregación diaria y √252), `monte_carlo` (4 incluyendo bootstrap),
  `max_consec_losses` (4), `Trade.net` y `Trade.is_win` (4).
- **`.env.example`** — Plantilla de configuración completa para `live_monitor.py`:
  `GTX_TELEGRAM_TOKEN`, `GTX_TELEGRAM_CHAT_ID`, thresholds y rutas.

### Changed — Infrastructure
- **`requirements.txt`** — Añadidos `yfinance>=0.2.36`, `python-dotenv>=1.0.0`,
  `pytest>=8.0.0`, `pytest-cov>=5.0.0`.
- **`.github/workflows/ci.yml`** — Nuevo job `python-tests` (pytest sobre `tests/`);
  flake8 extendido a `tests/`; structure-check extendido a `OrderManager.mqh`,
  `HealthMonitor.mqh`, `TestOrderManager.mq5`, `live_monitor.py`,
  `tests/test_backtest_analysis.py`, `.env.example`.

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
