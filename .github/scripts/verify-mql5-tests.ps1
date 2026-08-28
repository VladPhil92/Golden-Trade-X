$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installDir = Join-Path $env:RUNNER_TEMP "MetaTrader5"
$repoMql5 = Join-Path $env:GITHUB_WORKSPACE "MQL5"
$evidenceDir = Join-Path $env:RUNNER_TEMP "mql5-test-evidence"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
"GTX_MQL5_TEST_EVIDENCE=$evidenceDir" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append

function Resolve-Executable {
    param([string[]]$Candidates, [string]$Label)
    $found = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $found) { throw "$Label executable not found" }
    return $found
}

function Resolve-Mql5Root {
    $portableTrade = Join-Path $installDir "MQL5\Include\Trade\Trade.mqh"
    if (Test-Path $portableTrade) { return (Join-Path $installDir "MQL5") }

    $terminalDataRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    if (Test-Path $terminalDataRoot) {
        foreach ($directory in Get-ChildItem -Path $terminalDataRoot -Directory -ErrorAction SilentlyContinue) {
            $candidate = Join-Path $directory.FullName "MQL5\Include\Trade\Trade.mqh"
            if (Test-Path $candidate) { return (Join-Path $directory.FullName "MQL5") }
        }
    }
    throw "Initialized MetaTrader MQL5 tree not found"
}

function Stop-MetaTraderProcesses {
    $names = @("terminal64", "terminal", "metaeditor64", "metaeditor", "metatester64", "metatester")
    $running = @(Get-Process -Name $names -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        $ids = @($running | ForEach-Object { $_.Id })
        $running | Stop-Process -Force -ErrorAction SilentlyContinue
        foreach ($id in $ids) {
            try { Wait-Process -Id $id -Timeout 10 -ErrorAction SilentlyContinue } catch { }
        }
    }

    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        $left = @(Get-Process -Name $names -ErrorAction SilentlyContinue)
        if ($left.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    }

    $left = @(Get-Process -Name $names -ErrorAction SilentlyContinue)
    if ($left.Count -gt 0) {
        throw "MetaTrader/MetaEditor processes did not terminate cleanly: $($left.Name -join ', ')"
    }

    # MetaTrader uses a single-instance/data-directory lock. Give Windows a
    # bounded grace interval so the next /config startup cannot inherit the
    # previous test process or stale profile lock.
    Start-Sleep -Milliseconds 750
}

function Assert-CompileLog {
    param([string]$LogPath, [string]$Label)
    if (-not (Test-Path $LogPath)) { throw "$Label did not produce a MetaEditor log" }
    $text = Get-Content $LogPath -Raw
    if ($text -match "(?im)(^|\s)([1-9][0-9]*)\s+errors?\b") {
        throw "$Label compilation failed — see $LogPath"
    }
    if ($text -notmatch "(?im)\b0\s+errors?\b") {
        throw "$Label compile log has no explicit 0 errors result"
    }
}

function Read-TestJournal {
    param([string[]]$LogRoots)
    $parts = @()
    foreach ($root in $LogRoots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($file in Get-ChildItem -Path $root -Filter "*.log" -File -ErrorAction SilentlyContinue) {
            try { $parts += Get-Content $file.FullName -Raw -ErrorAction Stop } catch { }
        }
    }
    return ($parts -join "`n")
}

function Get-TestSummary {
    param([string]$Journal, [string]$Base)

    # Canonical v2.63 format: === TestX END | PASS=N FAIL=N ===
    $canonical = [regex]::Match(
        $Journal,
        "===\s+" + [regex]::Escape($Base) + "\s+END\s+\|\s+PASS=(\d+)\s+FAIL=(\d+)\s+==="
    )
    if ($canonical.Success) {
        return [pscustomobject]@{
            Pass = [int]$canonical.Groups[1].Value
            Fail = [int]$canonical.Groups[2].Value
        }
    }

    # v2.62 counted format: TestX: N tests | P PASS | F FAIL
    $counted = [regex]::Match(
        $Journal,
        [regex]::Escape($Base) + ":\s+\d+\s+tests\s+\|\s+(\d+)\s+PASS\s+\|\s+(\d+)\s+FAIL"
    )
    if ($counted.Success) {
        return [pscustomobject]@{
            Pass = [int]$counted.Groups[1].Value
            Fail = [int]$counted.Groups[2].Value
        }
    }

    # Older suite format retained during migration:
    # PASS: P / FAIL: F / TOTAL: N
    $legacy = [regex]::Match(
        $Journal,
        "PASS:\s*(\d+)\s*/\s*FAIL:\s*(\d+)\s*/\s*TOTAL:\s*(\d+)"
    )
    if ($legacy.Success) {
        return [pscustomobject]@{
            Pass = [int]$legacy.Groups[1].Value
            Fail = [int]$legacy.Groups[2].Value
        }
    }

    return $null
}

$metaEditor = Resolve-Executable -Candidates @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe"),
    (Join-Path $installDir "MetaEditor.exe")
) -Label "MetaEditor"

$terminal = Resolve-Executable -Candidates @(
    (Join-Path $installDir "terminal64.exe"),
    (Join-Path $installDir "terminal.exe")
) -Label "MetaTrader"

$mql5Root = Resolve-Mql5Root
$portableMode = $mql5Root.StartsWith($installDir, [System.StringComparison]::OrdinalIgnoreCase)
$includeDst = Join-Path $mql5Root "Include\GoldenTradeX"
$testsDst = Join-Path $mql5Root "Scripts\Tests"

Write-Host "MQL5 automated verification"
Write-Host "MQL5 root: $mql5Root"
Write-Host "Portable:  $portableMode"

New-Item -ItemType Directory -Force -Path $includeDst | Out-Null
New-Item -ItemType Directory -Force -Path $testsDst | Out-Null
Copy-Item -Path (Join-Path $repoMql5 "Include\GoldenTradeX\*") -Destination $includeDst -Recurse -Force
Copy-Item -Path (Join-Path $repoMql5 "Scripts\Tests\*") -Destination $testsDst -Recurse -Force

$testSources = @(Get-ChildItem -Path $testsDst -Filter "Test*.mq5" -File | Sort-Object Name)
if ($testSources.Count -eq 0) { throw "No MQL5 test scripts found" }

Stop-MetaTraderProcesses

# Gate 1: every test source must compile with MetaEditor.
foreach ($source in $testSources) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($source.Name)
    $compileLog = Join-Path $evidenceDir "$base-compile.log"
    $args = @(
        "/compile:$($source.FullName)",
        "/include:$mql5Root",
        "/log:$compileLog"
    )
    if ($portableMode) { $args += "/portable" }

    Write-Host "Compiling $($source.Name)..."
    $proc = Start-Process -FilePath $metaEditor -ArgumentList $args -PassThru -Wait
    Write-Host "MetaEditor exit code ($base): $($proc.ExitCode)"
    Assert-CompileLog -LogPath $compileLog -Label $base

    $ex5 = [System.IO.Path]::ChangeExtension($source.FullName, ".ex5")
    if (-not (Test-Path $ex5)) { throw "$base compiled without producing EX5" }
    Copy-Item $ex5 (Join-Path $evidenceDir "$base.ex5") -Force
}

Write-Host "MQL5 TEST COMPILE PASS — $($testSources.Count) scripts, 0 errors"

# Gate 2: execute every script through the documented [StartUp] configuration
# interface. Assertions are never retried: FAIL>0 fails immediately. A single
# clean retry is allowed only when MetaTrader fails to emit any recognizable
# summary, which is treated as terminal-startup infrastructure flakiness. Two
# missing summaries remain a hard failure.
$journalRoots = @(
    (Join-Path $installDir "Logs"),
    (Join-Path $mql5Root "Logs")
)
$maxStartupAttempts = 2
$runtimeTimeoutSeconds = 45

foreach ($source in $testSources) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($source.Name)
    $summary = $null

    for ($attempt = 1; $attempt -le $maxStartupAttempts; $attempt++) {
        Stop-MetaTraderProcesses

        foreach ($root in $journalRoots) {
            if (Test-Path $root) {
                Get-ChildItem -Path $root -Filter "*.log" -File -ErrorAction SilentlyContinue |
                    Remove-Item -Force -ErrorAction SilentlyContinue
            }
        }

        $configPath = Join-Path $evidenceDir "$base-attempt$attempt.ini"
        @"
[Charts]
ProfileLast=default
MaxBars=50000
TradeHistory=1
TradeLevels=1

[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1

[StartUp]
Script=Tests\$base
Symbol=EURUSD
Period=M1
Template=default.tpl
"@ | Set-Content -Path $configPath -Encoding ascii

        $args = @("/config:$configPath")
        if ($portableMode) { $args += "/portable" }

        Write-Host "Running $base through MetaTrader [StartUp] (attempt $attempt/$maxStartupAttempts)..."
        $terminalProc = Start-Process -FilePath $terminal -ArgumentList $args -PassThru
        $deadline = (Get-Date).AddSeconds($runtimeTimeoutSeconds)
        $journal = ""
        $attemptSummary = $null

        try {
            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
                $journal = Read-TestJournal -LogRoots $journalRoots
                $attemptSummary = Get-TestSummary -Journal $journal -Base $base
                if ($null -ne $attemptSummary) { break }

                if ($terminalProc.HasExited) {
                    # Give MetaTrader one bounded flush interval before deciding
                    # that this startup produced no usable test evidence.
                    Start-Sleep -Seconds 1
                    $journal = Read-TestJournal -LogRoots $journalRoots
                    $attemptSummary = Get-TestSummary -Journal $journal -Base $base
                    break
                }
            }
        }
        finally {
            if ($terminalProc -and -not $terminalProc.HasExited) {
                Stop-Process -Id $terminalProc.Id -Force -ErrorAction SilentlyContinue
            }
            Stop-MetaTraderProcesses
        }

        $journalPath = Join-Path $evidenceDir "$base-runtime-attempt$attempt.log"
        $journal | Set-Content -Path $journalPath -Encoding utf8

        if ($null -ne $attemptSummary) {
            Write-Host "$base runtime result: PASS=$($attemptSummary.Pass) FAIL=$($attemptSummary.Fail)"
            if ($attemptSummary.Fail -ne 0) {
                throw "$base reported $($attemptSummary.Fail) failed assertion(s)"
            }
            if ($attemptSummary.Pass -le 0) {
                throw "$base reported no passing assertions"
            }
            $summary = $attemptSummary
            break
        }

        if ($attempt -lt $maxStartupAttempts) {
            Write-Warning "$base emitted no recognized summary on attempt $attempt; performing one clean MetaTrader startup retry. Evidence: $journalPath"
            Start-Sleep -Seconds 2
        }
    }

    if ($null -eq $summary) {
        throw "$base did not emit a recognized test summary after $maxStartupAttempts clean startup attempts"
    }
}

Write-Host "MQL5 AUTOMATED TESTS PASS — $($testSources.Count) scripts compiled and executed"
