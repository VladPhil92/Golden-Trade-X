from __future__ import annotations

from pathlib import Path

import pytest

from scripts.experiment_registry import RegistryValidationError
from scripts import mt5_connection


class _Process:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _Mt5:
    def __init__(self, init_results, login_results=None, errors=None) -> None:
        self.init_results = list(init_results)
        self.login_results = list(login_results or [True])
        self.errors = list(errors or [(-10005, "IPC timeout")])
        self.init_calls = 0
        self.login_calls = 0
        self.shutdown_calls = 0

    def initialize(self, *args, **kwargs):
        self.init_calls += 1
        return self.init_results.pop(0)

    def login(self, *args, **kwargs):
        self.login_calls += 1
        return self.login_results.pop(0)

    def shutdown(self):
        self.shutdown_calls += 1

    def last_error(self):
        if len(self.errors) > 1:
            return self.errors.pop(0)
        return self.errors[0]


def _terminal(tmp_path: Path) -> Path:
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"test")
    return terminal


def test_connect_retries_ipc_timeout_then_logs_in(tmp_path: Path, monkeypatch) -> None:
    process = _Process()
    monkeypatch.setattr(mt5_connection, "_launch_terminal", lambda *_: process)
    monkeypatch.setattr(mt5_connection.time, "sleep", lambda *_: None)
    mt5 = _Mt5(
        [False, True],
        [True],
        [(-10005, "IPC timeout")],
    )

    returned = mt5_connection.connect_mt5(
        mt5,
        terminal_path=_terminal(tmp_path),
        login=123456,
        password="secret",
        server="XMGlobal-MT5 2",
        portable=True,
        attempts=3,
        bootstrap_wait_seconds=0,
        retry_wait_seconds=0,
    )

    assert returned is process
    assert mt5.init_calls == 2
    assert mt5.login_calls == 1
    assert mt5.shutdown_calls >= 2


def test_connect_separates_initialize_from_login_credentials(tmp_path: Path, monkeypatch) -> None:
    process = _Process()
    monkeypatch.setattr(mt5_connection, "_launch_terminal", lambda *_: process)
    monkeypatch.setattr(mt5_connection.time, "sleep", lambda *_: None)

    captured_init = {}
    captured_login = {}

    class CapturingMt5(_Mt5):
        def initialize(self, *args, **kwargs):
            captured_init.update(kwargs)
            return True

        def login(self, *args, **kwargs):
            captured_login["args"] = args
            captured_login.update(kwargs)
            return True

    mt5 = CapturingMt5([True], [True])
    mt5_connection.connect_mt5(
        mt5,
        terminal_path=_terminal(tmp_path),
        login=169059595,
        password="never-log-me",
        server="XMGlobal-MT5 2",
        portable=True,
        bootstrap_wait_seconds=0,
        retry_wait_seconds=0,
    )

    assert "login" not in captured_init
    assert "password" not in captured_init
    assert "server" not in captured_init
    assert captured_login["args"] == (169059595,)
    assert captured_login["server"] == "XMGlobal-MT5 2"


def test_connect_fails_closed_after_bounded_retries(tmp_path: Path, monkeypatch) -> None:
    process = _Process()
    monkeypatch.setattr(mt5_connection, "_launch_terminal", lambda *_: process)
    monkeypatch.setattr(mt5_connection.time, "sleep", lambda *_: None)
    mt5 = _Mt5(
        [False, False, False],
        errors=[(-10005, "IPC timeout")],
    )

    with pytest.raises(RegistryValidationError, match="after 3 attempts"):
        mt5_connection.connect_mt5(
            mt5,
            terminal_path=_terminal(tmp_path),
            login=123456,
            password="secret",
            server="XMGlobal-MT5 2",
            portable=True,
            attempts=3,
            bootstrap_wait_seconds=0,
            retry_wait_seconds=0,
        )

    assert process.terminated is True


def test_connect_rejects_missing_terminal(tmp_path: Path) -> None:
    mt5 = _Mt5([True])

    with pytest.raises(RegistryValidationError, match="terminal not found"):
        mt5_connection.connect_mt5(
            mt5,
            terminal_path=tmp_path / "missing.exe",
            login=123456,
            password="secret",
            server="XMGlobal-MT5 2",
            portable=True,
        )
