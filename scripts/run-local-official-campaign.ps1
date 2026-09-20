param(
    [Parameter(Mandatory = $false)]
    [string]$CampaignConfig = "config/official_validation_campaign.xm_gold.json",

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSeconds = 3600,

    [Parameter(Mandatory = $false)]
    [string]$TerminalPath = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".git")) {
    throw "Run this script from the Golden-Trade-X repository root."
}

if ([string]::IsNullOrWhiteSpace($TerminalPath)) {
    $running = @(
        Get-Process terminal64, terminal -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and (Test-Path -LiteralPath $_.Path) } |
            Select-Object -ExpandProperty Path -Unique
    )

    if ($running.Count -eq 0) {
        throw "No running MetaTrader terminal was found. Open your XM MT5 DEMO account first."
    }

    if ($running.Count -gt 1) {
        Write-Host "Detected multiple running MT5 terminals:" -ForegroundColor Yellow
        $running | ForEach-Object { Write-Host "  $_" }
        throw "Close extra MT5 terminals or rerun with -TerminalPath '<exact terminal64.exe path>'."
    }

    $TerminalPath = [string]$running[0]
}

if (-not (Test-Path -LiteralPath $TerminalPath -PathType Leaf)) {
    throw "MetaTrader terminal not found: $TerminalPath"
}

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source -3.12 ".\scripts\local_official_campaign.py" `
        --campaign-config $CampaignConfig `
        --terminal $TerminalPath `
        --timeout-seconds $TimeoutSeconds
    exit $LASTEXITCODE
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python 3.12+ is required."
}

& $python.Source ".\scripts\local_official_campaign.py" `
    --campaign-config $CampaignConfig `
    --terminal $TerminalPath `
    --timeout-seconds $TimeoutSeconds
exit $LASTEXITCODE
