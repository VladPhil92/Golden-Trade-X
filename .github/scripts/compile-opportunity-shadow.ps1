$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $env:GTX_EX5) {
    throw "GTX_EX5 from primary EA compilation is required"
}

$primaryEx5 = $env:GTX_EX5
$expertDir = Split-Path $primaryEx5 -Parent
$source = Join-Path $expertDir "GoldenTradeXOpportunityShadow.mq5"
$expertsRoot = Split-Path $expertDir -Parent
$mql5Root = Split-Path $expertsRoot -Parent
$installDir = Join-Path $env:RUNNER_TEMP "MetaTrader5"
$compileLog = Join-Path $env:RUNNER_TEMP "GoldenTradeXOpportunityShadow-compile.log"

$metaEditorCandidates = @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe"),
    (Join-Path $installDir "MetaEditor.exe")
)
$metaEditor = $metaEditorCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $metaEditor) { throw "MetaEditor executable not found under $installDir" }
if (-not (Test-Path $source)) { throw "Shadow expert source not staged: $source" }

Write-Host "Compiling research-only v3.1 opportunity shadow expert"
Write-Host "Source:  $source"
Write-Host "Include: $mql5Root"
Write-Host "Log:     $compileLog"

$arguments = @(
    "/compile:$source",
    "/include:$mql5Root",
    "/log:$compileLog"
)
if ($primaryEx5 -like "$installDir*") {
    $arguments += "/portable"
}

$compile = Start-Process -FilePath $metaEditor -ArgumentList $arguments -PassThru -Wait
Write-Host "MetaEditor process exit code: $($compile.ExitCode)"
if (-not (Test-Path $compileLog)) {
    throw "MetaEditor did not produce shadow compile log: $compileLog"
}
Get-Content $compileLog
$logText = Get-Content $compileLog -Raw
if ($logText -match "(?im)(^|\s)([1-9][0-9]*)\s+errors?\b") {
    throw "Shadow expert compilation reported one or more errors"
}
if ($logText -notmatch "(?im)\b0\s+errors?\b") {
    throw "Shadow compile log lacks explicit '0 errors' result"
}

$ex5 = [System.IO.Path]::ChangeExtension($source, ".ex5")
if (-not (Test-Path $ex5)) {
    throw "Shadow compilation reported success but EX5 was not created: $ex5"
}
$sha256 = (Get-FileHash -Algorithm SHA256 $ex5).Hash.ToLowerInvariant()
Write-Host "V3.1 SHADOW COMPILE PASS — 0 errors"
Write-Host "EX5:    $ex5"
Write-Host "SHA256: $sha256"

"GTX_SHADOW_EX5=$ex5" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"GTX_SHADOW_COMPILE_LOG=$compileLog" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
