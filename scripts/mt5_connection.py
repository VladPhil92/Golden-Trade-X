#!/usr/bin/env python3
"""Shared MT5 terminal bootstrap and credential login helper.

GitHub-hosted Windows runners install a fresh terminal for every job. The first
terminal startup can take long enough that calling MetaTrader5.initialize(...)
with credentials immediately may fail with IPC timeout (-10005). This module
separates terminal bootstrap from account login, retries only boundedly and
never writes credentials to logs or artifacts.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

try:
    from scripts.experiment_registry import RegistryValidationError
except ModuleNotFoundError:
    from experiment_registry import RegistryValidationError


IPC_TIMEOUT_CODE = -10005


def _last_error(mt5: Any) -> tuple[int, str]:
    value = mt5.last_error()
    if isinstance(value, tuple) and len(value) >= 2:
        return int(value[0]), str(value[1])
    return 0, str(value)


def _safe_shutdown(mt5: Any) -> None:
    try:
        mt5.shutdown()
    except Exception:
        pass


def _launch_terminal(terminal: Path, portable: bool) -> subprocess.Popen[Any]:
    args = [str(terminal)]
    if portable:
        args.append("/portable")
    return subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def connect_mt5(
    mt5: Any,
    *,
    terminal_path: str | Path,
    login: int,
    password: str,
    server: str,
    portable: bool,
    attempts: int = 3,
    bootstrap_wait_seconds: float = 8.0,
    retry_wait_seconds: float = 5.0,
    initialize_timeout_ms: int = 60000,
    login_timeout_ms: int = 60000,
) -> subprocess.Popen[Any] | None:
    """Bootstrap terminal IPC then authenticate the requested account.

    Returns the explicitly launched terminal process when one was needed. The
    caller owns cleanup of that process after mt5.shutdown().
    """

    terminal = Path(terminal_path).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")
    if attempts < 1:
        raise RegistryValidationError("MT5 connection attempts must be >= 1")
    if not isinstance(login, int) or login <= 0:
        raise RegistryValidationError("MT5 login must be a positive integer")
    if not password:
        raise RegistryValidationError("MT5 password is required")
    if not server or not server.strip():
        raise RegistryValidationError("MT5 server is required")

    launched: subprocess.Popen[Any] | None = None
    errors: list[str] = []

    for attempt in range(1, attempts + 1):
        _safe_shutdown(mt5)

        if launched is None or launched.poll() is not None:
            launched = _launch_terminal(terminal, portable)
            time.sleep(max(0.0, bootstrap_wait_seconds))

        initialized = mt5.initialize(
            str(terminal),
            portable=bool(portable),
            timeout=int(initialize_timeout_ms),
        )
        if not initialized:
            code, message = _last_error(mt5)
            errors.append(f"attempt {attempt}: initialize code={code}, message={message}")
            if code != IPC_TIMEOUT_CODE and attempt >= attempts:
                break
            time.sleep(max(0.0, retry_wait_seconds * attempt))
            continue

        logged_in = mt5.login(
            int(login),
            password=password,
            server=server.strip(),
            timeout=int(login_timeout_ms),
        )
        if logged_in:
            return launched

        code, message = _last_error(mt5)
        errors.append(f"attempt {attempt}: login code={code}, message={message}")
        _safe_shutdown(mt5)
        time.sleep(max(0.0, retry_wait_seconds * attempt))

    if launched is not None and launched.poll() is None:
        try:
            launched.terminate()
        except Exception:
            pass

    detail = "; ".join(errors[-attempts:]) if errors else "no MT5 error details"
    raise RegistryValidationError(
        f"MetaTrader5 connection failed after {attempts} attempts: {detail}"
    )



def connect_existing_mt5_session(
    mt5: Any,
    *,
    terminal_path: str | Path,
    portable: bool = false,
    initialize_timeout_ms: int = 60000,
) -> None:
    """Attach Python to an MT5 terminal/session already running on this Windows user desktop.

    No account credentials are required. The selected account remains whatever is
    currently authenticated in the terminal. Callers must independently verify DEMO
    trade mode and any expected broker/server constraints before trusting the session.
    """

    terminal = Path(terminal_path).resolve()
    if not terminal.is_file():
        raise RegistryValidationError(f"MetaTrader terminal not found: {terminal}")

    _safe_shutdown(mt5)
    initialized = mt5.initialize(
        str(terminal),
        portable=bool(portable),
        timeout=int(initialize_timeout_ms),
    )
    if not initialized:
        code, message = _last_error(mt5)
        raise RegistryValidationError(
            "MetaTrader5 could not attach to the existing local terminal session: "
            f"code={code}, message={message}"
        )

    if mt5.terminal_info() is None:
        _safe_shutdown(mt5)
        raise RegistryValidationError(
            "MetaTrader5 attached but terminal_info() returned no data"
        )
    if mt5.account_info() is None:
        _safe_shutdown(mt5)
        raise RegistryValidationError(
            "MetaTrader5 attached but account_info() returned no data"
        )

def stop_bootstrap_process(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
