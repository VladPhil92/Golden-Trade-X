"""
Golden Trade X — Monitor de cuenta y posiciones (Python + MetaTrader5).

Observabilidad externa: equity, posiciones del EA por magic number,
con reconexión automática, logging persistente y alertas Telegram.

Uso:
    python monitor.py [--symbol XAUUSD] [--magic 920260] [--refresh 30]
    python monitor.py --telegram-token <TOKEN> --telegram-chat-id <CHAT_ID>

Variables de entorno equivalentes:
    GTX_SYMBOL, GTX_MAGIC, GTX_TG_TOKEN, GTX_TG_CHAT_ID, GTX_ALERT_DD_PCT

Alertas enviadas:
    - Monitor iniciado / detenido / reconectado
    - Posición abierta (símbolo, lado, precio entrada, SL, TP)
    - Posición cerrada (P/L en moneda y %)
    - Caída de equity >= GTX_ALERT_DD_PCT (default 2%)
"""

import argparse
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import MetaTrader5 as mt5

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

DEFAULT_MAGIC        = 920260
DEFAULT_SYMBOL       = "XAUUSD"
DEFAULT_REFRESH      = 30
DEFAULT_ALERT_DD_PCT = 2.0
MAX_RETRIES          = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── Telegram notifier ──────────────────────────────────────────────────────────

class TelegramNotifier:
    """Sends HTML messages to a Telegram chat via Bot API. No-op when unconfigured."""

    _URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: Optional[str], chat_id: Optional[str]) -> None:
        self._token   = token or ""
        self._chat_id = chat_id or ""
        self._enabled = bool(self._token and self._chat_id and _REQUESTS_OK)
        if self._token and self._chat_id and not _REQUESTS_OK:
            log.warning("Telegram: el paquete 'requests' no está instalado — alertas desactivadas.")

    def _redact(self, text: str) -> str:
        """v2.61: las excepciones de requests incluyen la URL completa — que
        contiene el token del bot. Sin esta redacción, un fallo de red
        escribiría el token en texto plano en monitor.log."""
        return text.replace(self._token, "***TOKEN***") if self._token else text

    def send(self, text: str) -> None:
        if not self._enabled:
            return
        try:
            resp = _requests.post(
                self._URL.format(token=self._token),
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            if not resp.ok:
                log.warning("Telegram: HTTP %d — %s", resp.status_code,
                            self._redact(resp.text[:120]))
        except Exception as exc:
            log.warning("Telegram: fallo al enviar — %s", self._redact(str(exc)))


# ── State tracking ─────────────────────────────────────────────────────────────

@dataclass
class _PositionSnap:
    ticket:     int
    side:       str
    volume:     float
    symbol:     str
    open_price: float
    sl:         float
    tp:         float
    profit:     float


@dataclass
class MonitorState:
    positions:      Dict[int, _PositionSnap] = field(default_factory=dict)
    equity_ref:     float = 0.0
    balance_ref:    float = 0.0
    dd_alert_fired: bool  = False


def _snap(p) -> _PositionSnap:
    return _PositionSnap(
        ticket=p.ticket,
        side="BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        volume=p.volume,
        symbol=p.symbol,
        open_price=p.price_open,
        sl=p.sl,
        tp=p.tp,
        profit=p.profit,
    )


# ── Core loop helpers ──────────────────────────────────────────────────────────

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


def snapshot(
    symbol: str,
    magic: int,
    state: MonitorState,
    notifier: TelegramNotifier,
    alert_dd_pct: float,
) -> None:
    info = mt5.account_info()
    if info is None:
        log.warning("account_info() = None (terminal desconectado?)")
        return

    positions = mt5.positions_get(symbol=symbol) or []
    ea_pos    = [p for p in positions if p.magic == magic]
    floating  = sum(p.profit for p in ea_pos)
    current   = {p.ticket: _snap(p) for p in ea_pos}

    # Inicializar referencias de equity en el primer snapshot
    if state.equity_ref == 0.0:
        state.equity_ref  = info.equity
        state.balance_ref = info.balance

    # ── Log periódico ──────────────────────────────────────────────────
    log.info(
        "Equity %.2f | Balance %.2f | Flotante GTX %.2f | Posiciones GTX %d",
        info.equity, info.balance, floating, len(ea_pos),
    )
    for p in ea_pos:
        log.info(
            "  #%d %s %.2f %s @ %.5f | SL %.5f TP %.5f | P/L %.2f",
            p.ticket, p.side, p.volume, p.symbol,
            p.open_price, p.sl, p.tp, p.profit,
        )

    prev = state.positions

    # ── Alerta: posición abierta ───────────────────────────────────────
    for ticket, s in current.items():
        if ticket not in prev:
            log.info("ALERT open  #%d %s %s @ %.5f", ticket, s.side, s.symbol, s.open_price)
            notifier.send(
                f"📈 <b>Posición abierta</b>\n"
                f"#{ticket} {s.side} {s.volume} {s.symbol}\n"
                f"Entrada: {s.open_price:.5f}  SL: {s.sl:.5f}  TP: {s.tp:.5f}\n"
                f"Equity: {info.equity:.2f} {info.currency}"
            )

    # ── Alerta: posición cerrada ───────────────────────────────────────
    for ticket, s in prev.items():
        if ticket not in current:
            pnl_pct = s.profit / info.balance * 100 if info.balance > 0 else 0.0
            icon    = "✅" if s.profit >= 0 else "❌"
            log.info("ALERT close #%d P/L %.2f (%.2f%%)", ticket, s.profit, pnl_pct)
            notifier.send(
                f"{icon} <b>Posición cerrada</b>\n"
                f"#{ticket} {s.side} {s.volume} {s.symbol}\n"
                f"Entrada: {s.open_price:.5f}  P/L: {s.profit:+.2f} {info.currency} "
                f"({pnl_pct:+.2f}%)\n"
                f"Equity: {info.equity:.2f} {info.currency}"
            )
            # Resetear referencia tras cierre
            state.equity_ref     = info.equity
            state.balance_ref    = info.balance
            state.dd_alert_fired = False

    # ── Alerta: drawdown de equity ─────────────────────────────────────
    if state.equity_ref > 0:
        drop_pct = (state.equity_ref - info.equity) / state.equity_ref * 100
        if drop_pct >= alert_dd_pct and not state.dd_alert_fired:
            log.warning("ALERT DD %.1f%%  (ref %.2f → %.2f)", drop_pct,
                        state.equity_ref, info.equity)
            notifier.send(
                f"⚠️ <b>Alerta de drawdown</b>\n"
                f"Caída: {drop_pct:.1f}%\n"
                f"Equity ref: {state.equity_ref:.2f} → actual: {info.equity:.2f} "
                f"{info.currency}"
            )
            state.dd_alert_fired = True
        elif drop_pct < alert_dd_pct / 2:
            state.dd_alert_fired = False

    state.positions = current


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Trade X — Monitor MT5")
    parser.add_argument(
        "--symbol",
        default=os.getenv("GTX_SYMBOL", DEFAULT_SYMBOL),
        help="Símbolo en el broker (ej: XAUUSD, GOLD, XAUUSD.)",
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
    # v2.61: acepta AMBOS nombres de variable — los canónicos documentados en
    # .env.example (GTX_TELEGRAM_*, los mismos de live_monitor.py) y los
    # legacy (GTX_TG_*). Antes cada monitor usaba nombres distintos y
    # configurar el .env según la plantilla dejaba este script mudo.
    parser.add_argument(
        "--telegram-token",
        default=os.getenv("GTX_TELEGRAM_TOKEN", "") or os.getenv("GTX_TG_TOKEN", ""),
        help="Token del bot de Telegram (preferir GTX_TELEGRAM_TOKEN en .env — "
             "pasarlo por CLI lo expone en el historial de shell y en la lista "
             "de procesos)",
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=os.getenv("GTX_TELEGRAM_CHAT_ID", "") or os.getenv("GTX_TG_CHAT_ID", ""),
        help="Chat ID de destino (preferir GTX_TELEGRAM_CHAT_ID en .env)",
    )
    parser.add_argument(
        "--alert-dd-pct",
        type=float,
        default=float(os.getenv("GTX_ALERT_DD_PCT", str(DEFAULT_ALERT_DD_PCT))),
        help="Caída de equity (%%) que dispara alerta de drawdown (default 2.0)",
    )
    args = parser.parse_args()

    notifier = TelegramNotifier(args.telegram_token, args.telegram_chat_id)
    state    = MonitorState()

    log.info(
        "Monitor iniciado | Symbol=%s Magic=%d Refresh=%ds Telegram=%s AlertDD=%.1f%%",
        args.symbol, args.magic, args.refresh,
        "ON" if notifier._enabled else "OFF",
        args.alert_dd_pct,
    )

    if not connect():
        log.error("No se pudo conectar a MT5. Abortando.")
        return

    notifier.send(
        f"🟢 <b>Monitor Golden Trade X iniciado</b>\n"
        f"Symbol: {args.symbol}  Magic: {args.magic}  "
        f"Alerta DD: {args.alert_dd_pct:.1f}%"
    )

    try:
        while True:
            if mt5.terminal_info() is None:
                log.warning("Terminal desconectado. Reconectando…")
                notifier.send("🔴 <b>MT5 desconectado</b> — reconectando…")
                mt5.shutdown()
                if not connect():
                    log.error("Reconexión fallida. Deteniendo monitor.")
                    notifier.send("🔴 <b>Monitor detenido</b> — no se pudo reconectar a MT5.")
                    break
                notifier.send("🟢 <b>MT5 reconectado</b>")

            snapshot(args.symbol, args.magic, state, notifier, args.alert_dd_pct)
            time.sleep(args.refresh)

    except KeyboardInterrupt:
        log.info("Monitor detenido por el usuario.")
        notifier.send("⏹ <b>Monitor detenido</b> por el usuario.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
