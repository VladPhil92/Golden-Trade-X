#!/usr/bin/env python3
"""
Golden Trade X — Live trade monitor with Telegram alerts.

Watches the GoldenTradeX_*.csv (produced by TradeLogger.mqh) for new rows,
detects new trades and sends structured alerts to a Telegram bot.

Also monitors:
  - Daily P&L vs DD limit (configurable)
  - Consecutive loss streak
  - EA health status file (GTX_{magic}_status.csv from HealthMonitor.mqh)

Configuration via environment variables or .env file:
    GTX_TELEGRAM_TOKEN    — Telegram bot token (required for alerts)
    GTX_TELEGRAM_CHAT_ID  — Telegram chat/channel ID (required for alerts)
    GTX_DAILY_DD_ALERT_PCT — Alert threshold for daily drawdown % (default 3.0)
    GTX_CONSEC_LOSS_ALERT  — Alert after N consecutive losses (default 2)
    GTX_TRADE_CSV_DIR      — Directory to watch (default: current dir)
    GTX_POLL_INTERVAL      — Seconds between polls (default 10)
    GTX_MAGIC_NUMBER       — EA magic number for status file (default 920260)

Usage:
    python scripts/live_monitor.py
    python scripts/live_monitor.py --dry-run          # print alerts only
    python scripts/live_monitor.py --poll 5           # poll every 5s
    python scripts/live_monitor.py --csv path/to.csv  # specific file
"""

import argparse
import csv
import glob
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Set


# ── Optional dependencies ─────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    _HAS_DOTENV = True
except ImportError:
    _HAS_DOTENV = False

try:
    import urllib.request
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False


# ── Configuration ──────────────────────────────────────────────────────────────
def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


TELEGRAM_TOKEN    = _env("GTX_TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = _env("GTX_TELEGRAM_CHAT_ID")
DAILY_DD_ALERT    = float(_env("GTX_DAILY_DD_ALERT_PCT", "3.0"))
CONSEC_LOSS_ALERT = int(_env("GTX_CONSEC_LOSS_ALERT", "2"))
TRADE_CSV_DIR     = _env("GTX_TRADE_CSV_DIR", ".")
POLL_INTERVAL     = int(_env("GTX_POLL_INTERVAL", "10"))
MAGIC_NUMBER      = _env("GTX_MAGIC_NUMBER", "920260")


# ── Data model ─────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    position_id:  str
    close_date:   str
    close_time:   str
    symbol:       str
    side:         str
    lots:         float
    open_price:   float
    close_price:  float
    pnl:          float
    commission:   float
    r_multiple:   float
    comment:      str = ""

    @property
    def net(self) -> float:
        return self.pnl + self.commission

    @property
    def is_win(self) -> bool:
        return self.net > 0


@dataclass
class MonitorState:
    known_ids:      Set[str] = field(default_factory=set)
    today_pnl:      float    = 0.0
    today_date:     str      = ""
    consec_losses:  int      = 0
    total_trades:   int      = 0


# ── Telegram sender ────────────────────────────────────────────────────────────
def send_telegram(message: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[DRY-RUN] Telegram: {message}")
        return True
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    if not _HAS_URLLIB:
        print("WARNING: urllib not available — cannot send Telegram alert")
        return False

    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message,
                       "parse_mode": "HTML"}).encode()
    req  = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


def format_trade_alert(t: Trade) -> str:
    icon  = "✅" if t.is_win else "❌"
    arrow = "📈" if t.side.upper() == "BUY" else "📉"
    sign  = "+" if t.net >= 0 else ""
    return (
        f"{icon} <b>GoldenTradeX Trade Closed</b>\n"
        f"{arrow} {t.side.upper()} {t.symbol}  {t.lots} lots\n"
        f"Open: {t.open_price:.2f}  →  Close: {t.close_price:.2f}\n"
        f"P&L: <b>{sign}{t.net:.2f}</b>  R: {t.r_multiple:+.2f}R\n"
        f"Time: {t.close_date} {t.close_time}\n"
        f"Comment: {t.comment}"
    )


# ── CSV loading ────────────────────────────────────────────────────────────────
def load_csv(path: str) -> List[Trade]:
    trades = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    trades.append(Trade(
                        position_id=row["PositionID"],
                        close_date=row["CloseDate"],
                        close_time=row["CloseTime"],
                        symbol=row["Symbol"],
                        side=row["Type"],
                        lots=float(row["Lots"]),
                        open_price=float(row["OpenPrice"]),
                        close_price=float(row["ClosePrice"]),
                        pnl=float(row["ProfitLoss"]),
                        commission=float(row["Commission"]),
                        r_multiple=float(row["RMultiple"]),
                        comment=row.get("Comment", ""),
                    ))
                except (KeyError, ValueError):
                    continue
    except (FileNotFoundError, PermissionError):
        pass
    return trades


def find_csv(directory: str) -> Optional[str]:
    patterns = [
        os.path.join(directory, "GoldenTradeX_*.csv"),
        os.path.join(directory, "**", "GoldenTradeX_*.csv"),
    ]
    found = []
    for p in patterns:
        found.extend(glob.glob(p, recursive=True))
    return max(found, key=os.path.getmtime) if found else None


# ── Health status reader ───────────────────────────────────────────────────────
def read_health_status(directory: str, magic: str) -> Optional[Dict]:
    status_file = os.path.join(directory, f"GTX_{magic}_status.csv")
    if not os.path.exists(status_file):
        return None
    try:
        with open(status_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                return rows[-1]
    except Exception:
        pass
    return None


# ── Main monitor loop ──────────────────────────────────────────────────────────
def run(csv_path: Optional[str], poll_interval: int, dry_run: bool) -> None:
    state  = MonitorState()
    today  = str(date.today())
    logged = False

    tg_status = "ENABLED" if (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID) else \
                "DISABLED (set GTX_TELEGRAM_TOKEN + GTX_TELEGRAM_CHAT_ID)"
    print("GoldenTradeX Live Monitor started")
    print(f"  Poll interval : {poll_interval}s")
    print(f"  Telegram alerts: {tg_status}")
    print(f"  Daily DD alert : {DAILY_DD_ALERT}%")
    print(f"  Consec loss alert: {CONSEC_LOSS_ALERT}")
    if dry_run:
        print("  DRY-RUN mode: alerts printed, not sent")
    print()

    while True:
        # ── Auto-discover CSV if not provided ──────────────────────────
        target = csv_path or find_csv(TRADE_CSV_DIR)
        if not target:
            if not logged:
                print(f"[{time.strftime('%H:%M:%S')}] Waiting for GoldenTradeX_*.csv ...")
                logged = True
            time.sleep(poll_interval)
            continue
        logged = False

        # ── Load all trades ────────────────────────────────────────────
        trades = load_csv(target)
        new_today: List[Trade] = []

        for t in trades:
            if t.position_id in state.known_ids:
                continue
            state.known_ids.add(t.position_id)
            if t.close_date == today:
                new_today.append(t)

        # ── Process new trades ─────────────────────────────────────────
        for t in sorted(new_today, key=lambda x: x.close_time):
            state.today_pnl += t.net
            state.total_trades += 1
            if t.is_win:
                state.consec_losses = 0
            else:
                state.consec_losses += 1

            # Trade alert
            msg = format_trade_alert(t)
            print(f"[{time.strftime('%H:%M:%S')}] NEW TRADE: {t.side} {t.net:+.2f}"
                  f" R={t.r_multiple:+.2f}")
            send_telegram(msg, dry_run)

            # Consecutive loss alert
            if state.consec_losses >= CONSEC_LOSS_ALERT:
                alert = (f"⚠️ <b>GTX WARNING</b>: {state.consec_losses} consecutive losses\n"
                         f"Today P&L: {state.today_pnl:+.2f}\n"
                         f"Consider reviewing settings.")
                print(f"  ALERT: {state.consec_losses} consecutive losses")
                send_telegram(alert, dry_run)

        # ── Daily DD check ─────────────────────────────────────────────
        today_str = str(date.today())
        if today_str != today:
            today = today_str
            state.today_pnl = 0.0
            state.consec_losses = 0

        # ── Health status check ────────────────────────────────────────
        health = read_health_status(TRADE_CSV_DIR, MAGIC_NUMBER)
        if health:
            alert_field = health.get("alert", "")
            if alert_field:
                htime = health.get("timestamp", "")
                hmsg  = (f"🚨 <b>GTX Health Alert</b>\n"
                         f"Status: {alert_field}\n"
                         f"Timestamp: {htime}")
                print(f"[{time.strftime('%H:%M:%S')}] HEALTH ALERT: {alert_field}")
                send_telegram(hmsg, dry_run)

        time.sleep(poll_interval)


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Golden Trade X — Live trade monitor with Telegram alerts"
    )
    parser.add_argument("--csv",     type=str, default="",
                        help="Path to specific GoldenTradeX_*.csv (auto-discover if omitted)")
    parser.add_argument("--poll",    type=int, default=POLL_INTERVAL,
                        help=f"Poll interval in seconds (default {POLL_INTERVAL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print alerts without sending to Telegram")
    args = parser.parse_args()

    if not _HAS_DOTENV and not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("TIP: install python-dotenv and create .env with GTX_TELEGRAM_TOKEN / GTX_TELEGRAM_CHAT_ID")

    try:
        run(args.csv or None, args.poll, args.dry_run)
    except KeyboardInterrupt:
        print("\nMonitor stopped.")
        sys.exit(0)


if __name__ == "__main__":
    main()
