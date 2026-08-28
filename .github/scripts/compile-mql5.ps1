$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installDir = Join-Path $env:RUNNER_TEMP "MetaTrader5"
$installer = Join-Path $env:RUNNER_TEMP "mt5setup.exe"
$installerUrl = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
$repoMql5 = Join-Path $env:GITHUB_WORKSPACE "MQL5"
$compileLog = Join-Path $env:RUNNER_TEMP "GoldenTradeX-compile.log"

# Export evidence path before any operation so failures can still upload logs.
"GTX_COMPILE_LOG=$compileLog" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

function Wait-ForPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $Path) { return $true }
        Start-Sleep -Seconds 2
    }
    return (Test-Path $Path)
}

function Find-UserDataTradeLibrary {
    $terminalDataRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    if (-not (Test-Path $terminalDataRoot)) { return $null }

    foreach ($directory in Get-ChildItem -Path $terminalDataRoot -Directory -ErrorAction SilentlyContinue) {
        $candidate = Join-Path $directory.FullName "MQL5\Include\Trade\Trade.mqh"
        if (Test-Path $candidate) { return Get-Item $candidate }
    }
    return $null
}

Write-Host "Downloading official MetaTrader 5 installer..."
Invoke-WebRequest -Uri $installerUrl -OutFile $installer -UseBasicParsing

Write-Host "Installing MetaTrader 5 in automated mode: $installDir"
$install = Start-Process -FilePath $installer -ArgumentList @(
    "/auto",
    "/path:`"$installDir`""
) -PassThru -Wait
Write-Host "MetaTrader installer process exit code: $($install.ExitCode)"
if ($install.ExitCode -ne 0) {
    Write-Warning "Installer returned non-zero. The gate verifies installed files instead of trusting the installer exit code."
}

$metaEditorCandidates = @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe"),
    (Join-Path $installDir "MetaEditor.exe")
)
$metaEditor = $metaEditorCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $metaEditor) {
    throw "MetaEditor executable was not found under $installDir after automated installation (installer exit code $($install.ExitCode))"
}

$terminalCandidates = @(
    (Join-Path $installDir "terminal64.exe"),
    (Join-Path $installDir "terminal.exe")
)
$terminal = $terminalCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $terminal) {
    throw "MetaTrader terminal executable was not found under $installDir"
}

# The bootstrap installer can create the binaries before the MQL5 data tree has
# been materialized. MetaQuotes documents /portable specifically to force the
# terminal/MetaEditor data directory into the installation folder. Initialize
# that deterministic tree before looking for the standard library.
Get-Process terminal64, terminal, metaeditor64, metaeditor -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue

$portableTradePath = Join-Path $installDir "MQL5\Include\Trade\Trade.mqh"
if (-not (Test-Path $portableTradePath)) {
    Write-Host "Initializing MetaTrader 5 portable data directory..."
    $terminalProcess = Start-Process -FilePath $terminal -ArgumentList "/portable" -PassThru
    try {
        [void](Wait-ForPath -Path $portableTradePath -TimeoutSeconds 75)
    }
    finally {
        if ($terminalProcess -and -not $terminalProcess.HasExited) {
            Stop-Process -Id $terminalProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Get-Process terminal64, terminal -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

# Some builds materialize the editor-side data tree only when MetaEditor starts.
# Give it one bounded initialization attempt before falling back to the normal
# per-user MetaQuotes data directory.
if (-not (Test-Path $portableTradePath)) {
    Write-Host "Portable Trade.mqh not present yet; initializing MetaEditor portable data..."
    $editorProcess = Start-Process -FilePath $metaEditor -ArgumentList "/portable" -PassThru
    try {
        [void](Wait-ForPath -Path $portableTradePath -TimeoutSeconds 45)
    }
    finally {
        if ($editorProcess -and -not $editorProcess.HasExited) {
            Stop-Process -Id $editorProcess.Id -Force -ErrorAction SilentlyContinue
        }
        Get-Process metaeditor64, metaeditor -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

$standardTrade = $null
$portableMode = $false
if (Test-Path $portableTradePath) {
    $standardTrade = Get-Item $portableTradePath
    $portableMode = $true
} else {
    # Normal mode stores data under %APPDATA%\MetaQuotes\Terminal\<instance>.
    # Search only those known instance roots; never recurse through Program Files.
    $standardTrade = Find-UserDataTradeLibrary
}

if (-not $standardTrade) {
    $knownPortable = Join-Path $installDir "MQL5"
    $knownUser = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    throw "MetaQuotes standard MQL5 library was not initialized. Missing Include\Trade\Trade.mqh under '$knownPortable' and '$knownUser'."
}

# Trade.mqh -> Trade -> Include -> MQL5
$installedMql5 = $standardTrade.Directory.Parent.Parent.FullName
$installedInclude = Join-Path $installedMql5 "Include"
$installedExperts = Join-Path $installedMql5 "Experts"
$customIncludeDst = Join-Path $installedInclude "GoldenTradeX"
$expertDst = Join-Path $installedExperts "GoldenTradeX"

Write-Host "MetaEditor:          $metaEditor"
Write-Host "Installed MQL5 root: $installedMql5"
Write-Host "Standard Trade.mqh:  $($standardTrade.FullName)"
Write-Host "Portable mode:       $portableMode"

New-Item -ItemType Directory -Force -Path $customIncludeDst | Out-Null
New-Item -ItemType Directory -Force -Path $expertDst | Out-Null
Copy-Item -Path (Join-Path $repoMql5 "Include\GoldenTradeX\*") -Destination $customIncludeDst -Recurse -Force
Copy-Item -Path (Join-Path $repoMql5 "Experts\GoldenTradeX\*") -Destination $expertDst -Recurse -Force

$source = Join-Path $expertDst "GoldenTradeX.mq5"
$includeRoot = $installedMql5
if (-not (Test-Path $source)) {
    throw "EA source was not staged into initialized MQL5 tree: $source"
}

Write-Host "Source:  $source"
Write-Host "Include: $includeRoot"
Write-Host "Log:     $compileLog"

# MetaEditor documents /compile, /include and /log as its command-line build interface.
$arguments = @(
    "/compile:$source",
    "/include:$includeRoot",
    "/log:$compileLog"
)
if ($portableMode) {
    $arguments += "/portable"
}

$compile = Start-Process -FilePath $metaEditor -ArgumentList $arguments -PassThru -Wait
Write-Host "MetaEditor process exit code: $($compile.ExitCode)"

if (Test-Path $compileLog) {
    Write-Host "---- MetaEditor compile log ----"
    Get-Content $compileLog
    Write-Host "--------------------------------"
} else {
    throw "MetaEditor did not produce the requested compile log: $compileLog"
}

$logText = Get-Content $compileLog -Raw
if ($logText -match "(?im)(^|\s)([1-9][0-9]*)\s+errors?\b") {
    throw "MQL5 compilation reported one or more errors"
}
if ($logText -notmatch "(?im)\b0\s+errors?\b") {
    throw "Compile log does not contain an explicit '0 errors' result; refusing to mark the gate green"
}

$ex5 = [System.IO.Path]::ChangeExtension($source, ".ex5")
if (-not (Test-Path $ex5)) {
    throw "Compilation reported success but EX5 artifact was not created: $ex5"
}

$sha256 = (Get-FileHash -Algorithm SHA256 $ex5).Hash.ToLowerInvariant()
Write-Host "MQL5 COMPILE PASS — 0 errors"
Write-Host "EX5:    $ex5"
Write-Host "SHA256: $sha256"

"GTX_EX5=$ex5" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
