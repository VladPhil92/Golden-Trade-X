"""
Golden Trade X — Monitor de cuenta y posiciones (Python + MetaTrader5).

Capa opcional de observabilidad: se conecta al terminal MT5 local,
lee equity, posiciones abiertas del EA (por magic number) e imprime
un resumen periódico. Punto de partida para dashboards, alertas
(Telegram, email) o registro en base de datos.

Requisitos:
    pip install MetaTrader5 pandas

Uso:
    python monitor.py
"""

import time
from datetime import datetime

import MetaTrader5 as mt5

MAGIC_NUMBER = 920260
SYMBOL = "XAUUSD"
REFRESH_SECONDS = 30


def connect() -> bool:
    if not mt5.initialize():
        print(f"Error inicializando MT5: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info is None:
        print("No hay cuenta conectada en el terminal MT5.")
        return False
    print(f"Conectado a cuenta {info.login} ({info.server}) | "
          f"Balance: {info.balance:.2f} {info.currency}")
    return True


def snapshot() -> None:
    info = mt5.account_info()
    positions = mt5.positions_get(symbol=SYMBOL) or []
    ea_positions = [p for p in positions if p.magic == MAGIC_NUMBER]

    floating = sum(p.profit for p in ea_positions)
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] "
          f"Equity: {info.equity:.2f} | Flotante GTX: {floating:.2f} | "
          f"Posiciones GTX: {len(ea_positions)}")

    for p in ea_positions:
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        print(f"  #{p.ticket} {side} {p.volume} {p.symbol} @ {p.price_open} "
              f"| SL {p.sl} TP {p.tp} | P/L {p.profit:.2f}")


def main() -> None:
    if not connect():
        return
    try:
        while True:
            snapshot()
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\nMonitor detenido.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
