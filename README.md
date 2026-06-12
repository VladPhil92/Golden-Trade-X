# Golden Trade X

Expert Advisor (EA) para **MetaTrader 5** especializado en **Oro (XAUUSD)**, desarrollado bajo el portafolio tecnológico de **CTG One Technology S.A.S.**

> ⚠️ **Advertencia de riesgo.** El trading apalancado en metales conlleva un riesgo elevado de pérdida de capital. Este software se entrega "tal cual", con fines educativos y de desarrollo. Pruébelo siempre en **cuenta demo** y con backtesting exhaustivo antes de considerar capital real. Nada en este repositorio constituye asesoría financiera.

---

## Arquitectura

```
golden-trade-x/
├── MQL5/
│   ├── Experts/GoldenTradeX/
│   │   └── GoldenTradeX.mq5        ← EA principal (orquestador)
│   ├── Include/GoldenTradeX/
│   │   ├── SignalEngine.mqh        ← Motor de señales (EMA + RSI + ADX + ATR + H4)
│   │   ├── RiskManager.mqh         ← Gestión de riesgo y capital
│   │   ├── SessionFilter.mqh       ← Filtro de sesiones y fin de semana
│   │   ├── NewsFilter.mqh          ← Filtro NFP / FOMC / CPI
│   │   └── TradeLogger.mqh         ← Registro CSV por operación cerrada
│   └── Scripts/Tests/
│       ├── TestNewsFilter.mq5      ← Tests unitarios NewsFilter
│       └── TestRiskManager.mq5     ← Tests unitarios RiskManager
├── scripts/
│   ├── monitor.py                  ← Monitor en Python (MetaTrader5) con alertas Telegram
│   ├── backtest_analysis.py        ← Monte Carlo + walk-forward sobre CSV de TradeLogger
│   └── validate_set.py             ← Validador de parámetros (usado por CI)
├── config/
│   ├── GoldenTradeX.set            ← Preset XAUUSD para el Strategy Tester
│   └── GoldenTradeX_XAGUSD.set     ← Preset XAGUSD (Plata, magic 920261)
├── requirements.txt                ← Dependencias Python
├── CHANGELOG.md                    ← Historial de versiones
└── docs/
    └── STRATEGY.md                 ← Documento de estrategia y plan de pruebas
```

### Flujo de decisión (cada vela cerrada M15)

```
Nueva vela → ¿Sesión permitida? → ¿Spread aceptable? → ¿DD diario OK? (persistido)
          → ¿Posiciones < máx? → ¿Terminal conectado?
          → SignalEngine: ¿ATR ≥ ATR_SMA×0.8? → ¿Tendencia H4 acompaña?
          → Cruce EMA21/55 + RSI momentum (45–70 longs / 30–55 shorts)
          → RiskManager calcula lote (retorna 0 si lote < mínimo broker)
          → Orden con SL/TP automáticos
          → Trailing stop ATR×1.5 activado solo desde +1R
```

### Módulos

| Módulo | Responsabilidad |
|---|---|
| **GoldenTradeX.mq5** | Orquestación, trailing con activación 1R, cierre de viernes con verificación, persistencia de estado, integración TradeLogger |
| **SignalEngine** | Cruce EMA21/55 confirmado + continuación en barra 0 · RSI como momentum · filtro ATR mínimo · tendencia H4 · caché ATR por barra |
| **RiskManager** | Lote por % de equity, rechaza lote < mínimo broker, drawdown diario persistido con GlobalVariable, precisión de decimales dinámica |
| **SessionFilter** | Ventana Londres–NY (07–20 h servidor), cierre forzoso viernes 19 h |
| **monitor.py** | Observabilidad externa: equity, flotante, posiciones · reconexión automática · logging a archivo · alertas Telegram · configurable por argparse/envvar |

### Gestión de riesgo por defecto

- Riesgo por operación: **1 % del equity**
- Stop Loss: **ATR(14) × 2** · Take Profit: **ATR(14) × 3** (R:R 1:1.5)
- Trailing stop: **ATR × 1.5** (activo solo desde +1R para evitar stops prematuros)
- Drawdown diario máximo: **4 %** — persiste entre reinicios del EA via GlobalVariable
- Si lote calculado < lote mínimo del broker: la posición no se abre (sin sobreapalancamiento)
- Spread máximo: **350 puntos** (ajústelo a su broker)
- 1 posición simultánea, identificada por magic number `920260`

---

## Instalación

1. Abra MetaTrader 5 → **Archivo → Abrir carpeta de datos**.
2. Copie:
   - `MQL5/Experts/GoldenTradeX/` → carpeta `MQL5/Experts/` del terminal
   - `MQL5/Include/GoldenTradeX/` → carpeta `MQL5/Include/` del terminal
3. Abra **MetaEditor** (F4), compile `GoldenTradeX.mq5` (F7).
4. En MT5, arrastre el EA al gráfico **XAUUSD M15** y habilite *Algo Trading*.
5. Verifique el nombre exacto del símbolo de su broker (puede ser `XAUUSD`, `GOLD`, `XAUUSD.m`, etc.).

## Backtesting (obligatorio antes de demo/real)

1. **Ver → Probador de estrategias** (Ctrl+R).
2. Símbolo `XAUUSD`, timeframe M15, modelo *Every tick based on real ticks*.
3. Cargue el preset `config/GoldenTradeX.set`.
4. Periodo recomendado: mínimo 2–3 años; luego *walk-forward* y optimización solo de EMA/ATR para evitar sobreajuste.
5. El EA genera un CSV de trades via `TradeLogger`. Analícelos con:

```bash
pip install -r requirements.txt

# Análisis estadístico del CSV exportado por TradeLogger
python scripts/backtest_analysis.py                       # auto-descubre CSVs
python scripts/backtest_analysis.py trades.csv            # archivo específico
python scripts/backtest_analysis.py --mc-runs 2000 --output wf.csv
```

Salida de ejemplo:
```
  Operaciones totales              412
  Win rate                         51.7 %
  Profit factor                    1.842
  Sharpe ratio (anual.)            1.631
  Max drawdown                     1240.50  (12.4 %)
  ─────────────────────────────────────────
  MONTE CARLO  (1 000 simulaciones)
  Max DD P50 (mediana)             11.2 %
  Max DD P95 (escenario adverso)   19.8 %
  Prob. ruina (DD ≥ 40 %)          0.0 %
  ─────────────────────────────────────────
  [✓] Profit Factor ≥ 1.8          1.842
  [✓] Sharpe ≥ 1.5                 1.631
  [✓] Max DD ≤ 15 %                12.4 %
  >>> TODOS LOS OBJETIVOS SUPERADOS <<<
```

## Multi-símbolo: XAGUSD (Plata)

El EA funciona en cualquier símbolo. Para operar XAGUSD simultáneamente con XAUUSD:

1. Abra un gráfico **XAGUSD M15** en MT5.
2. Arrastre el EA y cargue el preset `config/GoldenTradeX_XAGUSD.set`.
3. El magic number `920261` distingue las instancias (sin colisión de GlobalVariables).

## Monitor en Python (opcional)

```bash
pip install -r requirements.txt

python scripts/monitor.py                              # defaults: XAUUSD, magic 920260
python scripts/monitor.py --symbol GOLD --refresh 60  # símbolo personalizado
GTX_SYMBOL=XAUUSD. python scripts/monitor.py          # vía variable de entorno

# Alertas Telegram (crear bot en @BotFather primero)
python scripts/monitor.py \
    --telegram-token  "123456:ABC-DEF..." \
    --telegram-chat-id "@mi_canal"          \
    --alert-dd-pct 2.0

# O con variables de entorno
GTX_TG_TOKEN=... GTX_TG_CHAT_ID=... python scripts/monitor.py
```

Requiere el terminal MT5 abierto en la misma máquina (Windows).  
El monitor reconecta automáticamente si MT5 se desconecta y persiste logs en `monitor.log`.  
Las alertas Telegram cubren: inicio/parada, posición abierta, posición cerrada con P/L y drawdown de equity.

---

## Hoja de ruta

- [x] Filtro de noticias de alto impacto — `NewsFilter.mqh` (NFP auto, FOMC hardcoded, CPI proxy)
- [x] Break-even automático al alcanzar 0.5R — `InpUseBreakEven` + `InpBreakEvenR`
- [x] Alertas a Telegram desde `monitor.py` — `TelegramNotifier` (posición abierta/cerrada, DD, reconexión)
- [x] Módulo de registro de operaciones en CSV para auditoría — `TradeLogger.mqh`
- [x] Tests unitarios MQL5 — `MQL5/Scripts/Tests/` (`TestNewsFilter`, `TestRiskManager`)
- [x] CI/CD GitHub Actions — validación automática en push
- [x] Backtesting walk-forward + Monte Carlo — `scripts/backtest_analysis.py` (lee CSV de TradeLogger)
- [x] Versión multi-símbolo (XAGUSD) — `config/GoldenTradeX_XAGUSD.set`

## Licencia

MIT © 2026 CTG One Technology S.A.S.
