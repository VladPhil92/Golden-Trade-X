# Estrategia Golden Trade X v1.0

## Tesis
El oro en M15 presenta tendencias intradía aprovechables durante el solape
Londres–Nueva York, donde la liquidez es máxima y el spread mínimo.

## Reglas de entrada
- COMPRA: EMA21 cruza por encima de EMA55 en vela cerrada, con RSI(14) < 70.
- VENTA: EMA21 cruza por debajo de EMA55 en vela cerrada, con RSI(14) > 30.
- Solo dentro de la ventana horaria configurada y con spread aceptable.

## Reglas de salida
- SL inicial: ATR(14) × 2. TP: ATR(14) × 3.
- Trailing stop: ATR × 1.5 a favor de la posición.
- Cierre forzoso los viernes a la hora configurada (riesgo de gap de fin de semana).

## Gestión de capital
- 1 % del equity por operación; lote calculado por distancia real al SL.
- Freno de drawdown diario del 4 %: el EA deja de abrir hasta el día siguiente.

## Plan de validación
1. Backtest 2023–2026, ticks reales, spread variable.
2. Walk-forward: optimizar 12 meses, validar 3 meses fuera de muestra.
3. Demo en vivo mínimo 4–8 semanas.
4. Métricas mínimas aceptables: Profit Factor > 1.3, DD máx < 15 %,
   al menos 100 operaciones en la muestra.

## Riesgos conocidos
- Mercados laterales generan cruces falsos (whipsaw): el filtro de sesión
  y el RSI mitigan, no eliminan.
- Noticias de alto impacto (NFP, FOMC, CPI): pendiente filtro de calendario.
- Dependencia del símbolo y condiciones del broker (spread, swap, slippage).
