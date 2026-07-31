# Estrategia Golden Trade X

> La versión vigente del EA es la del `#property version` de `GoldenTradeX.mq5`
> y la primera entrada de `CHANGELOG.md` — este documento no fija versión.

## Tesis
El oro en M15 presenta tendencias intradía aprovechables durante el solape
Londres–Nueva York, donde la liquidez es máxima y el spread mínimo.
La señal en M15 se filtra con la tendencia en H4 para reducir operaciones
contra-tendencia, principal fuente de pérdidas en mercados con dirección.

> **Estado de validación:** esta tesis y sus reglas NO cuentan todavía con
> evidencia empírica reproducible (backtest completo publicado, forward test).
> Trátese como hipótesis de trabajo, no como estrategia demostrada.

## Capa 1 — Guardianes (bloquean el ciclo antes de evaluar señal)

| Filtro | Condición |
|---|---|
| Kill switch | Inactivo (se activa solo ante errores fatales del broker; persiste entre reinicios) |
| Sesión | Hora del servidor entre StartHour y EndHour, no fin de semana |
| Spread | ≤ MaxSpreadPoints |
| Drawdown diario | < 4 % desde el inicio del día (persistido entre reinicios) |
| Drawdown semanal | < 8 % (semana absoluta alineada a lunes, estable en cambio de año) |
| Circuit breaker mensual | < 15 % |
| Pérdidas consecutivas | < 3 (con neto de posición completa, parciales incluidos) |
| Noticias | Fuera de ventana NFP / FOMC (fechas 2025–2027) / CPI-proxy |
| Posiciones | < 1 simultánea por instancia |
| Conexión | Terminal conectado al servidor |

## Capa 2 — Señal base (SignalEngine)

| Filtro | Condición |
|---|---|
| ATR mínimo | ATR(periodo) ≥ ATR_SMA(20) × 0.8 (mercado con volatilidad activa) |
| ATR máximo | ATR ≤ ATR_SMA(20) × 3.0 (evita picos de noticias) |
| ADX | ≥ 25 (solo mercados con tendencia; período configurable) |
| Tendencia H4 | Precio H4 > EMA(50) H4 para compras; < EMA(50) H4 para ventas |
| Cruce EMA | EMA21 cruza EMA55 en vela [1] y se mantiene en barra en curso [0] |
| RSI momentum | COMPRA: RSI entre 45 y 70; VENTA: RSI entre 30 y 55 |
| Volumen ticks | ≥ mínimo configurado en la vela cerrada (dependiente del broker) |

## Capa 3 — Confluence Score (heurístico, 0–100)

La señal base solo se ejecuta si el puntaje total de confluencia alcanza
`InpMinConfidence` (default 55). Componentes y pesos por defecto
(**configurables via `InpConfWeight*` — elegidos a mano, no calibrados
con datos; ver advertencia en `ConfidenceEngine.mqh`**):

| Componente | Peso máx. | Fuente |
|---|---|---|
| Señal base EMA+RSI | 25 | Capa 2 |
| Régimen de mercado | 25 | MarketRegimeEngine (ADX/ATR/BB; VOLATILE bloquea) |
| Smart Money Concepts | 30 | BOS/CHOCH/FVG/Order Blocks/Liquidity Sweep (barras cerradas) |
| Alineación H4 | 15 | Graduado 0/8/15 según pendiente de la EMA H4 |
| Confluencia Fibonacci | 5 | Proximidad a retrocesos 38.2/50/61.8 (swing en barras cerradas) |

## Reglas de salida
- SL inicial: ATR × 2 (con anclaje estructural al swing Fibonacci si existe).
  TP: ATR × 3.
- El OrderManager ajusta SL/TP a la distancia mínima del broker
  (`SYMBOL_TRADE_STOPS_LEVEL`) y reintenta errores temporales.
- Break-even a +0.5R con buffer de 0.1×ATR (cubre spread + comisión).
- Partial TP: cierra 50 % del lote a +1R (si el lote es divisible).
- Trailing stop ATR × 1.5 **activado solo desde +1 ATR de flotante**.
- Cierre forzoso los viernes a la hora configurada (gap de fin de semana).

## Gestión de capital
- 1 % del equity por operación (default; Kelly fraccional opcional y
  desactivado hasta tener ≥300 trades de historial real).
- Multiplicador 0.75 tras 2 pérdidas consecutivas; Capital Preservation
  Mode (riesgo × 0.25) si el DD diario supera el umbral.
- **Portfolio Risk Cap (opcional):** presupuesto de riesgo agregado entre
  todas las instancias de la cuenta (XAUUSD+XAGUSD correlacionados), con
  reconciliación de reservas huérfanas al reiniciar.
- Validación de margen libre (máx. 80 %) antes de enviar la orden.
- Si el lote calculado es menor al mínimo del broker, **no se abre la
  posición** (forzar el mínimo violaría el riesgo configurado).
- Equity Curve Filter: lote al 50 % cuando la equity < su EMA(20) por barra.
- Todos los límites de drawdown persisten entre reinicios via GlobalVariable.

## Plan de validación
1. Backtest con el máximo histórico del broker; primero `1 minute OHLC`
   (exploración), luego ticks reales (resultado final).
2. `scripts/backtest_analysis.py` con `--block-size 5` (rachas) y
   `--trials N` (nº de configuraciones probadas → Deflated Sharpe honesto).
3. Walk-forward real con `scripts/walk_forward_optimizer.py` (ventanas
   IS/OOS deslizantes sobre `InpMinConfidence`).
4. Demo en vivo mínimo 3–6 meses con `performance_report.py --watch`
   (alertas de degradación) y alertas Telegram.
5. Métricas mínimas antes de capital real: PF > 1.3, DD máx < 15 %,
   PSR ≥ 95 %, al menos 100 operaciones — y riesgo inicial reducido
   (0.25–0.5 %) aunque se cumplan.

## Nota sobre DST (horario de verano)
`StartHour`/`EndHour` están en hora del servidor del broker. La mayoría de
brokers usa EET: GMT+2 en invierno, GMT+3 en verano. Desde v2.60 el EA
**detecta el cambio de offset servidor-UTC entre reinicios y lo avisa en el
Journal** — al ver ese aviso, revise que la ventana siga cubriendo el solape
Londres–NY deseado.

## Riesgos conocidos
- El Confluence Score es heurístico: sus pesos y el umbral 55 no están
  calibrados con datos. Redundancia parcial ADX↔régimen y HTF duro↔bonus HTF
  pendiente de ablation test.
- La señal EMA 21/55 es rezagada por naturaleza; con todos los filtros
  encima, las entradas pueden llegar tarde en el movimiento (medir MFE/MAE
  con datos reales).
- El volumen de ticks y el spread son dependientes del broker: una
  configuración optimizada en un broker no es directamente transferible.
- Fechas FOMC 2027 son PROYECTADAS — verificar contra federalreserve.gov
  cuando la Fed publique el calendario oficial.
- Mercados en rango prolongado: los filtros reducen entradas pero no
  eliminan completamente las pérdidas en lateralización profunda.
