param(
    [Parameter(Mandatory = $false)]
    [string]$CampaignConfig = "config/official_validation_campaign.xm_gold.json",

    [Parameter(Mandatory = $false)]
    [int]$TimeoutSeconds = 3600,

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
    throw "Python 3.12+ is required."
}

function Invoke-PythonChecked {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Write-Host ""
    Write-Host "== $Label ==" -ForegroundColor Cyan
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path ".git")) {
    throw "Run this script from the Golden-Trade-X repository root."
}

if ($TimeoutSeconds -lt 60 -or $TimeoutSeconds -gt 7200) {
    throw "TimeoutSeconds must be in [60, 7200]."
}

$repo = (Resolve-Path ".").Path
$campaignPath = [System.IO.Path]::GetFullPath((Join-Path $repo $CampaignConfig))
if (-not (Test-Path -LiteralPath $campaignPath -PathType Leaf)) {
    throw "Campaign config not found: $campaignPath"
}

& git diff --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Tracked repository files have local changes. Commit/stash/revert them before official execution."
}
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    throw "The Git index has staged changes. Commit/stash them before official execution."
}

$gitSha = (& git rev-parse HEAD).Trim().ToLowerInvariant()
if ($gitSha -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve a full Git commit SHA."
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
$campaign = Get-Content -Raw -LiteralPath $campaignPath | ConvertFrom-Json
$configRoot = Split-Path $campaignPath -Parent

$environmentPath = [System.IO.Path]::GetFullPath(
    (Join-Path $configRoot ([string]$campaign.execution_environment_path))
)
$runtimeLock = [System.IO.Path]::GetFullPath(
    (Join-Path $configRoot ([string]$campaign.python_runtime_lock_path))
)
if (-not (Test-Path -LiteralPath $environmentPath -PathType Leaf)) {
    throw "Execution environment contract not found: $environmentPath"
}
if (-not (Test-Path -LiteralPath $runtimeLock -PathType Leaf)) {
    throw "Campaign runtime lock not found: $runtimeLock"
}

$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$campaignId = [string]$campaign.campaign_id
$runRoot = Join-Path $repo ("data\research\official_campaign-local\{0}-{1}" -f $campaignId, $stamp)
$freezeDir = Join-Path $runRoot "freeze"
$executionDir = Join-Path $runRoot "execution"
$runsDir = Join-Path $runRoot "runs"
$registry = Join-Path $runRoot "experiments.sqlite"
$readiness = Join-Path $runRoot "pre_campaign_readiness.json"
$runtimeContext = Join-Path $runRoot "runtime_context.json"
$attestation = Join-Path $runRoot "environment_attestation.json"
$l4Completion = Join-Path $runRoot "l4_completion.json"
$compileLog = Join-Path $runRoot "GoldenTradeX-local-compile.log"
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

Write-Host "Golden Trade X — LOCAL OFFICIAL XM CAMPAIGN" -ForegroundColor Green
Write-Host "Campaign: $campaignId"
Write-Host "Git SHA:  $gitSha"
Write-Host "Terminal: $TerminalPath"
Write-Host "Output:   $runRoot"
Write-Host ""
Write-Host "This runner reuses the DEMO account already logged into MT5." -ForegroundColor Cyan
Write-Host "It does not request or write your MT5 password or account login." -ForegroundColor Cyan

Invoke-PythonChecked $python @(
    "scripts/pre_campaign_readiness.py",
    "--campaign", $campaignPath,
    "--calendar-include", "MQL5/Include/GoldenTradeX/EconomicCalendarData.mqh",
    "--output", $readiness
) "Pre-campaign readiness"

if (-not (Test-Path -LiteralPath $readiness -PathType Leaf)) {
    throw "Pre-campaign readiness did not create its JSON output: $readiness"
}

$readinessResult = Get-Content -Raw -LiteralPath $readiness | ConvertFrom-Json
if ($null -eq $readinessResult) {
    throw "Pre-campaign readiness JSON is empty or invalid."
}

$readinessProperties = @($readinessResult.PSObject.Properties.Name)
if ($readinessProperties -notcontains "decision" -or $readinessProperties -notcontains "ready") {
    throw "Pre-campaign readiness JSON is missing decision/ready fields."
}

if ([string]$readinessResult.decision -ne "READY_TO_FREEZE" -or -not [bool]$readinessResult.ready) {
    throw "Pre-campaign readiness did not return READY_TO_FREEZE."
}

Invoke-PythonChecked $python @(
    "scripts/official_campaign_freeze.py",
    "--config", $campaignPath,
    "--output-dir", $freezeDir,
    "--build-id", $gitSha
) "Freeze official campaign"

$campaignLock = Join-Path $freezeDir "campaign_lock.json"
$lock = Get-Content -Raw -LiteralPath $campaignLock | ConvertFrom-Json
if ($lock.status -ne "OFFICIAL_CAMPAIGN_FROZEN") {
    throw "Campaign freeze did not produce OFFICIAL_CAMPAIGN_FROZEN."
}

Write-Host ""
Write-Host "== Install frozen Python runtime ==" -ForegroundColor Cyan
& $python -m pip install --disable-pip-version-check -r $runtimeLock
if ($LASTEXITCODE -ne 0) {
    throw "Frozen Python runtime installation failed."
}

Invoke-PythonChecked $python @(
    "scripts/local_mt5_runtime_context.py",
    "--terminal", $TerminalPath,
    "--output", $runtimeContext
) "Inspect existing local MT5 DEMO session"

$ctx = Get-Content -Raw -LiteralPath $runtimeContext | ConvertFrom-Json
if ($ctx.trade_mode -ne "DEMO" -or -not [bool]$ctx.terminal_connected) {
    throw "Local MT5 runtime is not a connected DEMO session."
}

$dataPath = [string]$ctx.data_path
$portableMode = [bool]$ctx.portable_mode
$portableText = $portableMode.ToString().ToLowerInvariant()
$mql5Root = Join-Path $dataPath "MQL5"
$standardTrade = Join-Path $mql5Root "Include\Trade\Trade.mqh"
if (-not (Test-Path -LiteralPath $standardTrade -PathType Leaf)) {
    throw "MT5 standard library not found under local data path: $standardTrade"
}

$installDir = Split-Path $TerminalPath -Parent
$metaEditor = @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe"),
    (Join-Path $installDir "MetaEditor.exe")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $metaEditor) {
    throw "MetaEditor was not found beside the running MT5 terminal: $installDir"
}

$customIncludeDst = Join-Path $mql5Root "Include\GoldenTradeX"
$expertDst = Join-Path $mql5Root "Experts\GoldenTradeX"
New-Item -ItemType Directory -Force -Path $customIncludeDst | Out-Null
New-Item -ItemType Directory -Force -Path $expertDst | Out-Null
Copy-Item -Path (Join-Path $repo "MQL5\Include\GoldenTradeX\*") -Destination $customIncludeDst -Recurse -Force
Copy-Item -Path (Join-Path $repo "MQL5\Experts\GoldenTradeX\*") -Destination $expertDst -Recurse -Force

$source = Join-Path $expertDst "GoldenTradeX.mq5"
$ex5 = [System.IO.Path]::ChangeExtension($source, ".ex5")
Write-Host ""
Write-Host "== Compile exact local Git build in XM MT5 data tree ==" -ForegroundColor Cyan
$quotedSource = '"' + $source + '"'
$quotedInclude = '"' + $mql5Root + '"'
$quotedLog = '"' + $compileLog + '"'
$arguments = @(
    "/compile:$quotedSource",
    "/include:$quotedInclude",
    "/log:$quotedLog"
)
if ($portableMode) {
    $arguments += "/portable"
}
$compile = Start-Process -FilePath $metaEditor -ArgumentList $arguments -PassThru -Wait
Write-Host "MetaEditor exit code: $($compile.ExitCode)"
if (-not (Test-Path -LiteralPath $compileLog -PathType Leaf)) {
    throw "MetaEditor did not create compile log: $compileLog"
}
$compileText = Get-Content -Raw -LiteralPath $compileLog
if ($compileText -match '(?im)(^|\s)([1-9][0-9]*)\s+errors?\b') {
    throw "MQL5 compilation reported errors. See $compileLog"
}
if ($compileText -notmatch '(?im)\b0\s+errors?\b') {
    throw "Compile log lacks explicit 0 errors result."
}
if (-not (Test-Path -LiteralPath $ex5 -PathType Leaf)) {
    throw "Compilation passed but EX5 was not created: $ex5"
}
Write-Host "MQL5 LOCAL COMPILE PASS — 0 errors" -ForegroundColor Green

$testerProfiles = Join-Path $mql5Root "Profiles\Tester"
New-Item -ItemType Directory -Force -Path $testerProfiles | Out-Null

Invoke-PythonChecked $python @(
    "scripts/mt5_environment_probe.py",
    "--contract", $environmentPath,
    "--terminal", $TerminalPath,
    "--reuse-existing-session",
    "--runtime-portable-mode", $portableText,
    "--output", $attestation
) "Attest exact XM DEMO environment from existing session"

Invoke-PythonChecked $python @(
    "scripts/official_campaign_runner.py",
    "--campaign-lock", $campaignLock,
    "--attestation", $attestation,
    "--config-root", $configRoot,
    "--output-dir", $executionDir,
    "--actual-git-sha", $gitSha,
    "--terminal", $TerminalPath,
    "--tester-profiles-dir", $testerProfiles,
    "--runtime-portable-mode", $portableText,
    "--registry", $registry,
    "--runs-dir", $runsDir,
    "--timeout-seconds", ([string]$TimeoutSeconds)
) "Execute rolling IS to frozen OOS"

Invoke-PythonChecked $python @(
    "scripts/official_campaign_evidence_check.py",
    "--readiness", $readiness,
    "--campaign-lock", $campaignLock,
    "--attestation", $attestation,
    "--execution-manifest", (Join-Path $executionDir "campaign_execution_manifest.json"),
    "--oos-evidence", (Join-Path $executionDir "oos_evidence_manifest.json"),
    "--oos-summary", (Join-Path $executionDir "oos_summary.json"),
    "--promotion-decision", (Join-Path $executionDir "oos_promotion_decision.json"),
    "--output", $l4Completion
) "Validate completed L4 OOS evidence"

$result = Get-Content -Raw -LiteralPath $l4Completion | ConvertFrom-Json
$zipPath = "${runRoot}.zip"
Compress-Archive -Path (Join-Path $runRoot "*") -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "LOCAL OFFICIAL CAMPAIGN COMPLETE" -ForegroundColor Green
Write-Host "Integrity: $($result.status)"
Write-Host "OOS result: $($result.oos_terminal_status)"
Write-Host "Next stage: $($result.next_stage)"
Write-Host "Evidence ZIP: $zipPath"
Write-Host ""
Write-Host "Live trading authorized: false"
Write-Host "Real capital authorized: false"
