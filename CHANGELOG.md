# Changelog

All notable changes to Golden Trade X are documented in this file.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
