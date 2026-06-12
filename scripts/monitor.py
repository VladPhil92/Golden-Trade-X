"""
Golden Trade X — Monitor de cuenta y posiciones (Python + MetaTrader5).

Observabilidad externa: equity, posiciones del EA por magic number,
con reconexión automática y logging persistente.

Uso:
    python monitor.py [--symbol XAUUSD] [--magic 920260] [--refresh 30]
    GTX_SYMBOL=GOLD python monitor.py   # también acepta variables de entorno
"""

import argparse
import logging
import os
import time

import MetaTrader5 as mt5

DEFAULT_MAGIC   = 920260
DEFAULT_SYMBOL  = "XAUUSD"
DEFAULT_REFRESH = 30
MAX_RETRIES     = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def connect(attempt: int = 0) -> bool:
    if mt5.initialize():
        info = mt5.account_info()
        if info is not None:
            log.info(
                "Conectado | Cuenta %d (%s) | Balance %.2f %s",
                info.login, info.server, info.balance, info.currency,
            )
            return True
        log.warning("MT5 activo pero sin cuenta conectada.")
    else:
        log.error("mt5.initialize() falló: %s", mt5.last_error())

    if attempt < MAX_RETRIES:
        wait = 2 ** attempt
        log.info("Reintento %d/%d en %ds…", attempt + 1, MAX_RETRIES, wait)
        time.sleep(wait)
        mt5.shutdown()
        return connect(attempt + 1)

    return False


def snapshot(symbol: str, magic: int) -> None:
    info = mt5.account_info()
    if info is None:
        log.warning("account_info() = None (terminal desconectado?)")
        return

    positions = mt5.positions_get(symbol=symbol) or []
    ea_pos    = [p for p in positions if p.magic == magic]
    floating  = sum(p.profit for p in ea_pos)

    log.info(
        "Equity %.2f | Flotante GTX %.2f | Posiciones GTX %d",
        info.equity, floating, len(ea_pos),
    )
    for p in ea_pos:
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"
        log.info(
            "  #%d %s %.2f %s @ %.5f | SL %.5f TP %.5f | P/L %.2f",
            p.ticket, side, p.volume, p.symbol,
            p.price_open, p.sl, p.tp, p.profit,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Trade X — Monitor MT5")
    parser.add_argument(
        "--symbol",
        default=os.getenv("GTX_SYMBOL", DEFAULT_SYMBOL),
        help="Nombre del símbolo en el broker (ej: XAUUSD, GOLD, XAUUSD.)",
    )
    parser.add_argument(
        "--magic",
        type=int,
        default=int(os.getenv("GTX_MAGIC", str(DEFAULT_MAGIC))),
        help="Magic number del EA",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH,
        help="Intervalo de refresco en segundos",
    )
    args = parser.parse_args()

    log.info("Monitor iniciado | Symbol=%s Magic=%d Refresh=%ds",
             args.symbol, args.magic, args.refresh)

    if not connect():
        log.error("No se pudo conectar a MT5. Abortando.")
        return

    try:
        while True:
            # Detectar desconexión y reconectar antes de cada snapshot
            if mt5.terminal_info() is None:
                log.warning("Terminal desconectado. Reconectando…")
                mt5.shutdown()
                if not connect():
                    log.error("Reconexión fallida. Deteniendo monitor.")
                    break

            snapshot(args.symbol, args.magic)
            time.sleep(args.refresh)

    except KeyboardInterrupt:
        log.info("Monitor detenido por el usuario.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
