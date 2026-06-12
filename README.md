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
│   └── Include/GoldenTradeX/
│       ├── SignalEngine.mqh        ← Motor de señales (EMA + RSI + ATR)
│       ├── RiskManager.mqh         ← Gestión de riesgo y capital
│       └── SessionFilter.mqh       ← Filtro de sesiones y fin de semana
├── scripts/
│   └── monitor.py                  ← Monitor opcional en Python (MetaTrader5)
├── config/
│   └── GoldenTradeX.set            ← Preset de parámetros para el Strategy Tester
└── docs/
    └── STRATEGY.md                 ← Documento de estrategia y plan de pruebas
```

### Flujo de decisión (cada vela cerrada M15)

```
Nueva vela → ¿Sesión permitida? → ¿Spread aceptable? → ¿DD diario OK?
          → ¿Posiciones < máx? → SignalEngine (cruce EMA 21/55 + filtro RSI)
          → RiskManager calcula lote por % de equity y distancia al SL (ATR×2)
          → Orden con SL/TP automáticos → Trailing stop ATR×1.5 en cada tick
```

### Módulos

| Módulo | Responsabilidad |
|---|---|
| **GoldenTradeX.mq5** | Ciclo de vida del EA, orquestación, trailing, cierre de viernes |
| **SignalEngine** | Cruce EMA 21/55 confirmado en vela cerrada + filtro RSI 14 anti-extremos + ATR 14 para volatilidad |
| **RiskManager** | Lote por riesgo % de equity, freno de drawdown diario (4 %), filtro de spread, límite de posiciones |
| **SessionFilter** | Ventana Londres–Nueva York (07–20 h servidor), cierre forzoso viernes 19 h |
| **monitor.py** | Observabilidad externa: equity, flotante y posiciones del EA vía API Python de MT5 |

### Gestión de riesgo por defecto

- Riesgo por operación: **1 % del equity**
- Stop Loss: **ATR(14) × 2** · Take Profit: **ATR(14) × 3** (R:R 1:1.5)
- Trailing stop: **ATR × 1.5**
- Drawdown diario máximo: **4 %** (el EA se pausa hasta el día siguiente)
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

## Monitor en Python (opcional)

```bash
pip install MetaTrader5 pandas
python scripts/monitor.py
```

Requiere el terminal MT5 abierto en la misma máquina (Windows).

---

## Hoja de ruta

- [ ] Filtro de noticias de alto impacto (calendario económico)
- [ ] Break-even automático al alcanzar 1R
- [ ] Alertas a Telegram desde `monitor.py`
- [ ] Módulo de registro de operaciones en CSV/SQLite para auditoría
- [ ] Versión multi-símbolo (XAGUSD)

## Licencia

MIT © 2026 CTG One Technology S.A.S.
