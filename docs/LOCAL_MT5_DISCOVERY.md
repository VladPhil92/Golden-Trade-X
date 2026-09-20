# Local MT5 DEMO Discovery

GitHub-hosted Windows runners can fail to establish MetaTrader 5 IPC even when the
terminal installs and compiles correctly. When that happens, discover the environment
from the user's own Windows desktop where MT5 is already open and connected.

## Requirements

- Windows
- MetaTrader 5 already open
- the intended broker account already logged in
- the account must be DEMO
- Python 3.12+ available as `py` or `python`

## One-command discovery

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/discover-local-mt5.ps1 -Symbol GOLD
```

The helper:

1. detects the running `terminal64.exe`;
2. installs the pinned MetaTrader5 Python package;
3. attaches to the already authenticated local MT5 session;
4. verifies the account is DEMO;
5. selects the requested symbol;
6. captures broker/server/currency/leverage/build and exact symbol contract metadata;
7. emits credential-free candidate and audit JSON files.

It never asks for or writes the trading-account password.

Outputs:

```text
data/research/environment-discovery-local/<SYMBOL>/
  execution_environment.candidate.json
  execution_environment.discovery.json
```

## XM examples

GOLD:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/discover-local-mt5.ps1 -Symbol GOLD
```

BTCUSD:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/discover-local-mt5.ps1 -Symbol BTCUSD
```

If more than one MT5 terminal is open, either close the extras or specify:

```powershell
-TerminalPath "C:\...\terminal64.exe"
```

## Safety

The discovery fails closed on REAL or CONTEST accounts and keeps:

```text
approved=false
live_trading_authorized=false
real_capital_authorized=false
```

The generated files contain no password and no account login identifier.
