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
    Get-Process terminal64, terminal, metaeditor64, metaeditor -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
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

# Gate 2: execute every script through MetaTrader [StartUp]. Some fresh hosted
# runners intermittently load a startup script while the terminal performs its
# own full recompilation, but never dispatch OnStart(). That condition is a
# launcher race, not a passing test. We retry a missing-summary launch up to
# three times while preserving every attempt's journal. Any emitted FAIL>0 is
# never retried and remains an immediate hard failure.
$journalRoots = @(
    (Join-Path $installDir "Logs"),
    (Join-Path $mql5Root "Logs")
)
$maxLaunchAttempts = 3

foreach ($source in $testSources) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($source.Name)
    $configPath = Join-Path $evidenceDir "$base.ini"
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

    $summary = $null
    $attemptEvidence = @()

    for ($attempt = 1; $attempt -le $maxLaunchAttempts; $attempt++) {
        Stop-MetaTraderProcesses
        Start-Sleep -Milliseconds 500

        foreach ($root in $journalRoots) {
            if (Test-Path $root) {
                Get-ChildItem -Path $root -Filter "*.log" -File -ErrorAction SilentlyContinue |
                    Remove-Item -Force -ErrorAction SilentlyContinue
            }
        }

        Write-Host "Running $base through MetaTrader [StartUp] (attempt $attempt/$maxLaunchAttempts)..."
        $terminalProc = Start-Process -FilePath $terminal -ArgumentList $args -PassThru
        $deadline = (Get-Date).AddSeconds(45)
        $journal = ""
        $exitedAt = $null

        try {
            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Milliseconds 500
                $journal = Read-TestJournal -LogRoots $journalRoots
                $summary = Get-TestSummary -Journal $journal -Base $base
                if ($null -ne $summary) { break }

                if ($terminalProc.HasExited) {
                    if ($null -eq $exitedAt) { $exitedAt = Get-Date }
                    if (((Get-Date) - $exitedAt).TotalSeconds -ge 3) { break }
                }
            }
        }
        finally {
            if ($terminalProc -and -not $terminalProc.HasExited) {
                Stop-Process -Id $terminalProc.Id -Force -ErrorAction SilentlyContinue
            }
            Stop-MetaTraderProcesses
        }

        $attemptEvidence += "===== $base attempt $attempt/$maxLaunchAttempts =====`n$journal"

        if ($null -ne $summary) {
            if ($summary.Fail -ne 0) {
                $journalPath = Join-Path $evidenceDir "$base-runtime.log"
                ($attemptEvidence -join "`n") | Set-Content -Path $journalPath -Encoding utf8
                throw "$base reported $($summary.Fail) failed assertion(s)"
            }
            if ($summary.Pass -le 0) {
                $journalPath = Join-Path $evidenceDir "$base-runtime.log"
                ($attemptEvidence -join "`n") | Set-Content -Path $journalPath -Encoding utf8
                throw "$base reported no passing assertions"
            }
            break
        }

        $loadedWithoutSummary = $journal -match (
            "(?im)script\s+" + [regex]::Escape($base) + ".*loaded successfully"
        )
        if ($loadedWithoutSummary -and $attempt -lt $maxLaunchAttempts) {
            Write-Warning "$base loaded but OnStart summary was not emitted; retrying clean terminal launch."
        }
        elseif ($attempt -lt $maxLaunchAttempts) {
            Write-Warning "$base produced no recognized summary; retrying clean terminal launch."
        }
    }

    $journalPath = Join-Path $evidenceDir "$base-runtime.log"
    ($attemptEvidence -join "`n") | Set-Content -Path $journalPath -Encoding utf8

    if ($null -eq $summary) {
        throw "$base did not emit a recognized test summary after $maxLaunchAttempts clean launch attempts — see $journalPath"
    }

    Write-Host "$base runtime result: PASS=$($summary.Pass) FAIL=$($summary.Fail)"
}

Write-Host "MQL5 AUTOMATED TESTS PASS — $($testSources.Count) scripts compiled and executed"
