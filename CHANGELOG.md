# Changelog

All notable changes to Golden Trade X are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
