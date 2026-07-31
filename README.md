# Golden Trade X

Expert Advisor (EA) para **MetaTrader 5** especializado en **Oro (XAUUSD)**, desarrollado bajo el portafolio tecnológico de **CTG One Technology S.A.S.**

> ⚠️ **Advertencia de riesgo.** El trading apalancado en metales conlleva un riesgo elevado de pérdida de capital. Este software se entrega "tal cual", con fines educativos y de desarrollo. Pruébelo siempre en **cuenta demo** y con backtesting exhaustivo antes de considerar capital real. Nada en este repositorio constituye asesoría financiera.
>
> **Estado del proyecto:** sistema experimental en etapa de validación. La arquitectura de software está madura, pero **no existe todavía evidencia empírica reproducible** (backtest completo, forward test, historial real) de que la estrategia tenga una ventaja estadística rentable. Ver `CHANGELOG.md` para el detalle de cada versión.

---

## Arquitectura

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
│   │   ├── SessionFilter.mqh         ← Filtro de sesiones y fin de semana
│   │   ├── NewsFilter.mqh            ← Filtro NFP / FOMC / CPI
│   │   └── TradeLogger.mqh           ← Registro CSV por operación cerrada
│   └── Scripts/Tests/                ← Tests unitarios MQL5 (ejecución manual en MT5)
├── scripts/
│   ├── backtest_analysis.py          ← Estadísticas, Monte Carlo, métricas ajustadas por riesgo
│   ├── performance_report.py         ← Evaluación CONTINUA de desempeño (alertas de degradación)
│   ├── walk_forward_optimizer.py     ← Walk-forward real (ventanas IS/OOS deslizantes)
│   ├── ml_pipeline.py                ← Pipeline XGBoost sobre el historial de trades
│   ├── mql5_lint.py                  ← Linter heurístico de MQL4-ismos (usado por CI)
│   ├── validate_set.py               ← Validador de parámetros .set (usado por CI)
│   └── live_monitor.py               ← Monitor en vivo con alertas Telegram
├── config/
│   ├── GoldenTradeX.set              ← Preset XAUUSD para el Strategy Tester
│   └── GoldenTradeX_XAGUSD.set       ← Preset XAGUSD (Plata, magic 920261)
├── requirements.txt                  ← Dependencias Python
├── CHANGELOG.md                      ← Historial de versiones (fuente de verdad de qué existe)
└── docs/
    ├── STRATEGY.md                   ← Documento de estrategia
    └── ARCHITECTURE.md               ← Arquitectura detallada
```

### Flujo de decisión (cada vela cerrada, timeframe configurable)

```
Nueva vela → Kill switch / sesión / spread / DD diario-semanal-mensual /
             pérdidas consecutivas / noticias → OK
          → SignalEngine: EMA21/55 + RSI + ADX + ATR + tendencia H4
          → Régimen de mercado (bloquea entradas si VOLATILE)
          → Confluence Score: base + régimen + SMC + HTF + Fibonacci ≥ InpMinConfidence
          → RiskManager: lote por %riesgo, Kelly opcional, Portfolio Risk Cap opcional,
             validación de margen libre
          → OrderManager: orden con SL/TP, respeta stops_level del broker, retry automático
          → Trailing (ATR×mult desde +1 ATR) + Break-even (con buffer) + Partial TP
```

### Gestión de riesgo por defecto

- Riesgo por operación: **1 % del equity** (o Kelly fraccional opcional, desactivado por defecto)
- Stop Loss: **ATR(14) × 2** · Take Profit: **ATR(14) × 3**
- Drawdown diario **4 %** / semanal **8 %** / circuit breaker mensual **15 %** — todos persisten entre reinicios via GlobalVariable
- Kill switch persistente ante errores fatales del broker
- Capital Preservation Mode: reduce riesgo al 25 % si el DD diario supera el umbral
- **Portfolio Risk Cap (v2.60, opcional):** límite de riesgo agregado entre TODAS las instancias del EA en la cuenta (p.ej. XAUUSD + XAGUSD corriendo en paralelo, que están correlacionados)
- Validación de margen libre antes de enviar (máx. 80 % del margen disponible)
- Si el lote calculado < lote mínimo del broker: la posición no se abre
- 1 posición simultánea por instancia, identificada por magic number

> Estos son los valores **por defecto**, no objetivos de rendimiento validados. Ajústelos según su tolerancia al riesgo y los resultados de su propio backtest.

---

## Instalación

1. Abra MetaTrader 5 → **Archivo → Abrir carpeta de datos**.
2. Copie:
   - `MQL5/Experts/GoldenTradeX/` → carpeta `MQL5/Experts/` del terminal
   - `MQL5/Include/GoldenTradeX/` → carpeta `MQL5/Include/` del terminal
3. Abra **MetaEditor** (F4), compile `GoldenTradeX.mq5` (F7). Debe compilar con 0 errores.
4. En MT5, arrastre el EA al gráfico **XAUUSD M15** y habilite *Algo Trading*.
5. Verifique el nombre exacto del símbolo de su broker (puede ser `XAUUSD`, `GOLD`, `XAUUSD.m`, etc.).

## Backtesting (obligatorio antes de demo/real)

1. **Ver → Probador de estrategias** (Ctrl+R).
2. Símbolo `GOLD`/`XAUUSD` (el de su broker), timeframe M15.
3. En **Inputs**, use el engranaje ⚙ → **Load Settings** para cargar `config/GoldenTradeX.set`.
4. Modelo recomendado: *1 minute OHLC (fastest)* para exploración rápida; *Every tick based on real ticks* para el resultado final antes de demo/real.
5. Periodo recomendado: el máximo histórico disponible en su broker; luego walk-forward.
6. El EA genera un CSV de trades via `TradeLogger`. Analícelos con:

```bash
pip install -r requirements.txt

# Análisis estadístico completo de un backtest (Monte Carlo, Sharpe, PSR/DSR)
python scripts/backtest_analysis.py                       # auto-descubre CSVs
python scripts/backtest_analysis.py trades.csv --html-output report.html
python scripts/backtest_analysis.py --block-size 5 --trials 20

# Walk-forward REAL (ventanas in-sample/out-of-sample deslizantes)
python scripts/walk_forward_optimizer.py trades.csv

# Evaluación CONTINUA de desempeño en vivo/demo (alertas de degradación)
python scripts/performance_report.py --watch 300
```

No hay una salida de ejemplo aquí a propósito — publicarla sin datos reales detrás sería
más engañoso que útil. Genere la suya con `--html-output` y consérvela como evidencia
junto con el `.set` usado, el build de MT5, el broker y el periodo exacto.

## Multi-símbolo: XAGUSD (Plata)

El EA funciona en cualquier símbolo. Para operar XAGUSD simultáneamente con XAUUSD:

1. Abra un gráfico **XAGUSD M15** en MT5.
2. Arrastre el EA y cargue el preset `config/GoldenTradeX_XAGUSD.set`.
3. El magic number `920261` distingue las instancias (sin colisión de GlobalVariables).
4. Considere activar `InpUsePortfolioCap=true` en **ambas** instancias — XAUUSD y XAGUSD están
   correlacionados (USD, tasas reales, riesgo geopolítico), y sin este control cada instancia
   gestiona su drawdown de forma aislada aunque el riesgo económico real esté sumado.

## Monitoreo continuo

```bash
# Alertas Telegram por trade cerrado, rachas de pérdidas y salud del EA
python scripts/live_monitor.py --dry-run

# Evaluación de desempeño con alertas de degradación (ventana reciente vs. histórico)
python scripts/performance_report.py --watch 300
```

Requiere el terminal MT5 abierto en la misma máquina (Windows) para `live_monitor.py`.

---

## Advertencias metodológicas conocidas

- El **Confluence Score** (`ConfidenceEngine.mqh`) es un puntaje heurístico por confluencia
  de filtros, no un ensemble estadístico calibrado. Sus pesos son inputs del EA
  (`InpConfWeight*`) pensados para optimizarse con datos reales, no valores validados.
- El desglose trimestral de `backtest_analysis.py` es una fotografía de desempeño por
  ventana, **no** un walk-forward de entrenamiento/prueba — para eso use
  `walk_forward_optimizer.py`.
- El bootstrap de Monte Carlo por defecto (`--block-size 1`) asume independencia entre
  operaciones. Sistemas de tendencia suelen tener rachas — use `--block-size 5` o mayor
  para una estimación de riesgo más conservadora.
- Los "objetivos internos de calidad" del reporte son umbrales propios de este proyecto,
  no una certificación institucional externa.

## Hoja de ruta

Ver `CHANGELOG.md` para el detalle completo de cada versión — es la fuente de verdad
sobre qué existe hoy en el repositorio.

## Licencia

MIT © 2026 CTG One Technology S.A.S.
