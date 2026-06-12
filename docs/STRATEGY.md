# Estrategia Golden Trade X v1.10

## Tesis
El oro en M15 presenta tendencias intradía aprovechables durante el solape
Londres–Nueva York, donde la liquidez es máxima y el spread mínimo.
La señal en M15 se filtra con la tendencia en H4 para reducir operaciones
contra-tendencia, principal fuente de pérdidas en mercados con dirección.

## Reglas de entrada (todos los filtros deben cumplirse)

| Filtro | Condición |
|---|---|
| Sesión | Hora del servidor entre StartHour y EndHour, no fin de semana |
| Spread | ≤ MaxSpreadPoints |
| Drawdown diario | < 4 % desde el inicio del día (persistido entre reinicios) |
| Posiciones | < 1 simultánea |
| Conexión | Terminal conectado al servidor |
| ATR mínimo | ATR(14) ≥ ATR_SMA(20) × 0.8 (mercado con volatilidad activa) |
| Tendencia H4 | Precio H4 > EMA(50) H4 para compras; < EMA(50) H4 para ventas |
| Cruce EMA | EMA21 cruza EMA55 en vela [1] y se mantiene en barra en curso [0] |
| RSI momentum | COMPRA: RSI entre 45 y 70; VENTA: RSI entre 30 y 55 |

## Reglas de salida
- SL inicial: ATR(14) × 2. TP: ATR(14) × 3 (R:R 1:1.5).
- Trailing stop ATR × 1.5 **activado solo cuando la posición alcanza +1R**
  (evita stop-outs prematuros por widening de spread).
- Cierre forzoso los viernes a la hora configurada (riesgo de gap de fin de semana).
  El cierre se verifica con resultado: si falla, se registra el error.

## Gestión de capital
- 1 % del equity por operación; lote calculado por tick value/tick size.
- Si el lote calculado es menor al mínimo del broker, **no se abre la posición**
  (en cuentas pequeñas, forzar el lote mínimo viola el riesgo configurado).
- Precisión de decimales dinámica según el step del broker.
- Drawdown diario máximo del 4 % persistido con GlobalVariable: sobrevive
  a reinicios del EA durante el mismo día de trading.

## Plan de validación
1. Backtest 2023–2026, ticks reales, spread variable.
2. Walk-forward: optimizar 12 meses, validar 3 meses fuera de muestra.
3. Demo en vivo mínimo 4–8 semanas.
4. Métricas mínimas aceptables: Profit Factor > 1.3, DD máx < 15 %,
   al menos 100 operaciones en la muestra.

## Nota sobre DST (horario de verano)
`StartHour`/`EndHour` están en hora del servidor del broker. La mayoría de
brokers usa EET: GMT+2 en verano (marzo–octubre), GMT+3 en invierno. Si su
broker usa un offset fijo, ajuste los parámetros de sesión en cada transición
de horario de verano (último domingo de marzo y octubre).

## Riesgos conocidos
- Noticias de alto impacto (NFP, FOMC, CPI): pendiente filtro de calendario.
  Es el principal riesgo no mitigado; se recomienda pausar el EA manualmente
  30 min antes/después de estas publicaciones.
- Dependencia del símbolo y condiciones del broker (spread, swap, slippage).
- Mercados en rango prolongado: el filtro ATR mínimo y el HTF reducen entradas,
  pero no eliminan completamente las pérdidas en lateralización profunda.
