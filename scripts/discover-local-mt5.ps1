param(
    [Parameter(Mandatory = $false)]
    [string]$Symbol = "GOLD",

    [Parameter(Mandatory = $false)]
    [string]$Timeframe = "M15",

    [Parameter(Mandatory = $false)]
    [double]$Deposit = 10000,

    [Parameter(Mandatory = $false)]
    [string]$TerminalPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-Python {
    foreach ($candidate in @("py", "python")) {
        try {
            $cmd = Get-Command $candidate -ErrorAction Stop
            return $cmd.Source
        } catch {}
    }
    throw "Python 3.12+ is required. Install Python, then rerun this script."
}

if ([string]::IsNullOrWhiteSpace($TerminalPath)) {
    $running = Get-Process terminal64, terminal -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and (Test-Path -LiteralPath $_.Path) } |
        Select-Object -ExpandProperty Path -Unique

    if (-not $running) {
        throw "No running MetaTrader terminal was found. Open your XM MT5 DEMO account first."
    }
    if (@($running).Count -ne 1) {
        Write-Host "Detected multiple running MT5 terminals:" -ForegroundColor Yellow
        @($running) | ForEach-Object { Write-Host "  $_" }
        throw "Close extra MT5 terminals or rerun with -TerminalPath '<exact terminal64.exe path>'."
    }
    $TerminalPath = [string]@($running)[0]
}

if (-not (Test-Path -LiteralPath $TerminalPath -PathType Leaf)) {
    throw "MetaTrader terminal not found: $TerminalPath"
}

$python = Resolve-Python
Write-Host "Python:   $python"
Write-Host "Terminal: $TerminalPath"
Write-Host "Symbol:   $Symbol"
Write-Host "TF:       $Timeframe"
Write-Host ""
Write-Host "This discovery reuses the account already logged into MT5." -ForegroundColor Cyan
Write-Host "No MT5 password is requested or written to disk." -ForegroundColor Cyan

& $python -m pip install --disable-pip-version-check "MetaTrader5==5.0.6147"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install MetaTrader5 Python package."
}

$slug = ($Symbol -replace '[^A-Za-z0-9._-]', '_')
$outDir = Join-Path "data/research/environment-discovery-local" $slug
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$contract = Join-Path $outDir "execution_environment.candidate.json"
$audit = Join-Path $outDir "execution_environment.discovery.json"

$args = @(
    "scripts/mt5_environment_discovery.py",
    "--terminal", $TerminalPath,
    "--symbol", $Symbol,
    "--timeframe", $Timeframe,
    "--deposit", ([string]::Format([Globalization.CultureInfo]::InvariantCulture, "{0}", $Deposit)),
    "--no-portable-mode",
    "--reuse-existing-session",
    "--output-contract", $contract,
    "--output-audit", $audit
)

& $python @args
if ($LASTEXITCODE -ne 0) {
    throw "Local MT5 discovery failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "LOCAL MT5 DISCOVERY PASS" -ForegroundColor Green
Write-Host "Candidate: $contract"
Write-Host "Audit:     $audit"
Write-Host ""
Write-Host "These files contain no password or account login identifier."
