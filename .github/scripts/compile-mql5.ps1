$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installDir = Join-Path $env:RUNNER_TEMP "MetaTrader5"
$installer = Join-Path $env:RUNNER_TEMP "mt5setup.exe"
$installerUrl = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
$source = Join-Path $env:GITHUB_WORKSPACE "MQL5\Experts\GoldenTradeX\GoldenTradeX.mq5"
$includeRoot = Join-Path $env:GITHUB_WORKSPACE "MQL5"
$compileLog = Join-Path $env:RUNNER_TEMP "GoldenTradeX-compile.log"

Write-Host "Downloading official MetaTrader 5 installer..."
Invoke-WebRequest -Uri $installerUrl -OutFile $installer -UseBasicParsing

Write-Host "Installing MetaTrader 5 in automated mode: $installDir"
$install = Start-Process -FilePath $installer -ArgumentList @(
    "/auto",
    "/path:`"$installDir`""
) -PassThru -Wait
if ($install.ExitCode -ne 0) {
    throw "MetaTrader 5 installer exited with code $($install.ExitCode)"
}

# The installer may launch the terminal after setup. CI only needs MetaEditor.
Get-Process terminal64, terminal -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$metaEditorCandidates = @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe"),
    (Join-Path $installDir "MetaEditor.exe")
)
$metaEditor = $metaEditorCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $metaEditor) {
    $found = Get-ChildItem -Path $installDir -Filter "MetaEditor*.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $metaEditor = $found.FullName }
}
if (-not $metaEditor) {
    throw "MetaEditor executable was not found under $installDir"
}

if (-not (Test-Path $source)) {
    throw "EA source not found: $source"
}

Write-Host "MetaEditor: $metaEditor"
Write-Host "Source:     $source"
Write-Host "Include:    $includeRoot"
Write-Host "Log:        $compileLog"

# MetaEditor documents /compile, /include and /log as its command-line build interface.
$arguments = @(
    "/compile:$source",
    "/include:$includeRoot",
    "/log:$compileLog"
)
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
"GTX_COMPILE_LOG=$compileLog" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
