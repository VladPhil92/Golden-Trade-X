# Estrategia Golden Trade X

> La versión vigente es la indicada por `#property version` en `GoldenTradeX.mq5` y la primera entrada de `CHANGELOG.md`.

## Estado de la tesis

Golden Trade X investiga si determinados movimientos tendenciales intradía de XAUUSD M15 pueden explotarse sistemáticamente combinando una señal EMA, filtros de momentum/volatilidad, contexto H4, régimen, estructura y una capa estricta de riesgo/ejecución.

**Esta tesis todavía NO está demostrada.** No existe todavía un conjunto completo de backtests auditables, walk-forward MT5 independiente y forward test prolongado que permita afirmar que el sistema posee un edge rentable y estable.

## Principios de research

1. Correctness antes de optimization.
2. No añadir indicadores sin hipótesis falsable.
3. No optimizar todos los parámetros simultáneamente.
4. OOS y forward tienen prioridad sobre el mejor backtest IS.
5. Un resultado negativo se conserva: no se oculta ni se reetiqueta como éxito.
6. Kelly permanece desactivado hasta disponer de evidencia suficiente.

## Capa 1 — Guardianes

Antes de evaluar una entrada:

| Guard | Default / comportamiento |
|---|---|
| Kill switch | fail closed, persistente |
| Conexión | terminal conectado |
| Sesión | `InpStartHour ≤ server hour < InpEndHour`, pendiente migración UTC-native |
| Spread | `≤ InpMaxSpreadPoints` |
| Daily DD | < 4 % |
| Weekly DD | < 8 % |
| Monthly DD | < 15 % |
| Consecutive losses | < 3 |
| News | FOMC exacto 2025–2027 + proxies NFP/CPI |
| Max positions | 1 por símbolo/magic por defecto |
| Netting ownership | no mezclar posición de otro magic/manual |

## Capa 2 — Señal base

| Componente | Regla de referencia |
|---|---|
| EMA | cruce EMA21/EMA55 confirmado |
| RSI | long 45–70; short 30–55 |
| ATR mínimo | ATR ≥ SMA(ATR,20) × 0.8 |
| ATR máximo | ATR ≤ SMA(ATR,20) × 3.0 |
| ADX | ≥25 |
| H4 | precio alineado con EMA50 H4 |
| Tick volume | ≥ mínimo configurado |

Los valores son defaults de investigación, no parámetros demostrados como óptimos.

## Capa 3 — Confluence Score

Score heurístico, no probabilidad calibrada:

| Componente | Peso default |
|---|---:|
| Base | 25 |
| Regime | 25 |
| SMC | 30 |
| HTF | 15 |
| Fibonacci | 5 |

`InpMinConfidence=55` es un valor de referencia. Debe someterse a ablation, sensitivity y monotonicity tests antes de promoverse como configuración estable.

## Initial R — definición oficial

Desde v2.62 la estrategia utiliza una definición única e inmutable:

```text
Initial Risk Price = abs(entry price - initial SL)

Initial Monetary Risk = pérdida monetaria estimada al Initial SL
                        usando OrderCalcProfit()

Realized R = Total Net P/L / Initial Monetary Risk
```

`Initial SL`, `Initial TP`, volumen inicial y riesgo inicial se persisten por `POSITION_IDENTIFIER` y no cambian cuando el EA mueve el SL por break-even o trailing.

### Consecuencias

- Partial TP usa Initial R, nunca distancia al SL actual.
- Break-even usa `InpBreakEvenR × InitialRiskPrice`.
- `RMultiple` usa net P/L completo / Initial Monetary Risk.
- MFE/MAE se expresan respecto del Initial R.
- reiniciar el EA no debe cambiar la definición de riesgo.

## Stops y reward/risk inicial

SL base:

```text
ATR × InpAtrSlMultiplier
```

TP base:

```text
ATR × InpAtrTpMultiplier
```

Fibonacci puede ampliar el stop al swing estructural. Después de establecer el SL definitivo se calcula:

```text
Initial RR = reward distance / risk distance
```

`InpMinInitialRR=0.0` por defecto significa **guard desactivado**. No se ha elegido un mínimo óptimo sin evidencia. El parámetro existe para research OOS posterior.

## Salidas

### Break-even

Default:

```text
+0.5 Initial R
```

El SL se mueve con buffer de `0.1×ATR` para intentar cubrir fricciones. El valor 0.5R debe someterse a exit research; no se considera óptimo.

### Partial TP

Default:

```text
50 % @ +1 Initial R
```

Solo se marca como ejecutado después de confirmación server-side. Si el volumen no puede dividirse respetando `SYMBOL_VOLUME_MIN/STEP`, se omite el parcial.

### Trailing

ATR trailing default `1.5×ATR`, activado desde aproximadamente +1 ATR. Trailing, Partial TP y Break-Even son funciones independientes: desactivar trailing no desactiva las otras dos.

### Friday close

Cierre completo a la hora configurada para limitar gap de fin de semana.

## Position State

`PositionStateManager` mantiene por `POSITION_IDENTIFIER`:

- entry;
- Initial SL/TP;
- Initial Risk Price;
- Initial Risk Money;
- Initial Volume;
- entry timestamp;
- confidence/regime;
- MFE/MAE.

Al reiniciar, intenta reconstruir el estado desde el historial. Si no puede demostrar ownership o Initial R, la gestión R-based falla cerrada y puede activar el kill switch.

## Ejecución

`OrderManager` diferencia:

```text
local/basic request acceptance
≠
server-confirmed execution
```

La lógica no trata `CTrade::PositionOpen()==true` como éxito suficiente. Utiliza retcodes y resultados server-side y conserva por separado:

- order ticket;
- deal ticket;
- `POSITION_IDENTIFIER` / `DEAL_POSITION_ID`;
- current position ticket.

## Gestión de capital

- fixed risk default: 1 % equity;
- Capital Preservation reduce sizing;
- 0.75 multiplier tras racha definida;
- margin guard usa `OrderCalcMargin()`;
- lot sizing/risk usa `OrderCalcProfit()`;
- Portfolio Risk Cap opcional y persistido por `POSITION_IDENTIFIER`;
- Equity Curve Filter reduce tamaño al 50 % bajo EMA equity;
- Kelly opcional y OFF.

Ninguno de estos mecanismos demuestra que la estrategia subyacente sea rentable.

## News Filter

### FOMC

Fechas de decisión 2025–2027 sincronizadas con el calendario publicado por la Federal Reserve. El statement se modela a 14:00 US Eastern, convertido dinámicamente según DST.

### NFP / CPI

La hora se modela a 08:30 US Eastern y usa DST. **La fecha sigue siendo un proxy**, por lo que este filtro no debe considerarse una reconstrucción histórica exacta para backtests oficiales.

### Coverage policy

`InpNewsCalendarPolicy`:

```text
0 WARN
1 FAIL_CLOSED
2 FAIL_OPEN
```

Una fase posterior sustituirá proxies/hardcoded dates por un calendar cache verificable.

## Validación oficial requerida

### L1 — Unit tests

Funciones deterministas de riesgo, fechas, estados y clasificación.

### L2 — Integration tests

EA + terminal + identidad + ejecución + persistencia.

### L3 — Strategy Tester

Backtest histórico completo bajo configuración y datos documentados.

### Exploración

`1 minute OHLC` puede usarse para búsqueda preliminar.

### Evidencia final

`Every tick based on real ticks`, costes realistas, hashes y manifest de experimento.

## Walk-forward

El actual `scripts/walk_forward_optimizer.py` filtra retrospectivamente un CSV ya producido. Es útil como diagnóstico de threshold pero **NO es el walk-forward oficial** porque al retirar trades cambia la trayectoria de equity, drawdown, sizing, rachas y estados.

El protocolo oficial pendiente es:

```text
IS Strategy Tester optimization
→ select/freeze
→ independent OOS Strategy Tester run
→ roll forward
```

Matrices objetivo:

- 12m IS → 3m OOS
- 18m IS → 3m OOS
- 24m IS → 6m OOS

## Gates orientativos antes de capital real

No son garantías ni certificaciones:

- OOS expectancy > 0;
- OOS PF aproximadamente >1.25–1.30;
- Max DD <15 %;
- PSR ≥95 %;
- DSR >0;
- parameter stability;
- walk-forward robustness;
- realistic cost stress;
- multi-broker robustness;
- forward demo suficiente;
- operación/recovery verificados.

## Riesgos de research pendientes

- redundancia ADX ↔ Regime;
- hard HTF ↔ HTF score;
- ATR filter ↔ volatility regime;
- utilidad incremental de SMC/Fibonacci no demostrada;
- Confluence Score no calibrado;
- sesión todavía basada en server time;
- news NFP/CPI date proxies;
- broker dependency de tick volume/spread;
- exit stack pendiente de MFE/MAE research;
- XAGUSD no validado independientemente.
