$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installDir = Join-Path $env:RUNNER_TEMP "MetaTrader5"
$repoMql5 = Join-Path $env:GITHUB_WORKSPACE "MQL5"
$evidenceDir = Join-Path $env:RUNNER_TEMP "mql5-test-evidence"
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
"GTX_MQL5_TEST_EVIDENCE=$evidenceDir" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append

function Stop-MT {
    Get-Process terminal64, terminal, metaeditor64, metaeditor, metatester64, metatester -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 750
}

function Read-Journal([string[]]$roots) {
    $text = @()
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($f in Get-ChildItem $root -Filter "*.log" -File -ErrorAction SilentlyContinue) {
            try { $text += Get-Content $f.FullName -Raw -ErrorAction Stop } catch { }
        }
    }
    return ($text -join "`n")
}

function Clear-Journal([string[]]$roots) {
    foreach ($root in $roots) {
        if (Test-Path $root) {
            Get-ChildItem $root -Filter "*.log" -File -ErrorAction SilentlyContinue |
                Remove-Item -Force -ErrorAction SilentlyContinue
        }
    }
}

function Get-Summary([string]$journal, [string]$base) {
    $m = [regex]::Match($journal,
        "===\s+" + [regex]::Escape($base) + "\s+END\s+\|\s+PASS=(\d+)\s+FAIL=(\d+)\s+===")
    if (-not $m.Success) {
        $m = [regex]::Match($journal,
            [regex]::Escape($base) + ":\s+\d+\s+tests\s+\|\s+(\d+)\s+PASS\s+\|\s+(\d+)\s+FAIL")
    }
    if (-not $m.Success) {
        $m = [regex]::Match($journal, "PASS:\s*(\d+)\s*/\s*FAIL:\s*(\d+)\s*/\s*TOTAL:\s*\d+")
    }
    if (-not $m.Success) { return $null }
    return [pscustomobject]@{ Pass = [int]$m.Groups[1].Value; Fail = [int]$m.Groups[2].Value }
}

$metaEditor = @(
    (Join-Path $installDir "metaeditor64.exe"),
    (Join-Path $installDir "MetaEditor64.exe"),
    (Join-Path $installDir "metaeditor.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$terminal = @(
    (Join-Path $installDir "terminal64.exe"),
    (Join-Path $installDir "terminal.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $metaEditor -or -not $terminal) { throw "MetaTrader executables not found" }

$mql5Root = Join-Path $installDir "MQL5"
if (-not (Test-Path (Join-Path $mql5Root "Include\Trade\Trade.mqh"))) {
    throw "Portable MQL5 data tree was not initialized"
}
$portable = $true
$includeDst = Join-Path $mql5Root "Include\GoldenTradeX"
$testsDst = Join-Path $mql5Root "Scripts\Tests"
$journalRoots = @((Join-Path $installDir "Logs"), (Join-Path $mql5Root "Logs"))

New-Item -ItemType Directory -Force $includeDst, $testsDst | Out-Null
Copy-Item (Join-Path $repoMql5 "Include\GoldenTradeX\*") $includeDst -Recurse -Force
Copy-Item (Join-Path $repoMql5 "Scripts\Tests\*") $testsDst -Recurse -Force
$tests = @(Get-ChildItem $testsDst -Filter "Test*.mq5" -File | Sort-Object Name)
if ($tests.Count -eq 0) { throw "No MQL5 tests found" }

Stop-MT
foreach ($source in $tests) {
    $base = [IO.Path]::GetFileNameWithoutExtension($source.Name)
    $log = Join-Path $evidenceDir "$base-compile.log"
    $compileArgs = @("/compile:$($source.FullName)", "/include:$mql5Root", "/log:$log", "/portable")
    Write-Host "Compiling $($source.Name)..."
    $p = Start-Process $metaEditor -ArgumentList $compileArgs -PassThru -Wait
    Write-Host "MetaEditor exit code ($base): $($p.ExitCode)"
    if (-not (Test-Path $log)) { throw "$base produced no compile log" }
    $compileText = Get-Content $log -Raw
    if ($compileText -notmatch "(?im)\b0\s+errors?\b" -or
        $compileText -match "(?im)(^|\s)[1-9][0-9]*\s+errors?\b") {
        throw "$base compilation failed"
    }
    $ex5 = [IO.Path]::ChangeExtension($source.FullName, ".ex5")
    if (-not (Test-Path $ex5)) { throw "$base produced no EX5" }
    Copy-Item $ex5 (Join-Path $evidenceDir "$base.ex5") -Force
}
Write-Host "MQL5 TEST COMPILE PASS — $($tests.Count) scripts, 0 errors"

# Runtime uses only already-compiled binaries. Removing source/project files from
# the ephemeral terminal tree prevents its first-start background compiler from
# racing the [StartUp] script dispatcher. Repository sources remain untouched.
Get-ChildItem $mql5Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in @(".mq5", ".mqproj") } |
    Remove-Item -Force -ErrorAction Stop
Write-Host "Runtime tree prepared: source recompilation disabled; verified EX5 files retained."

foreach ($source in $tests) {
    $base = [IO.Path]::GetFileNameWithoutExtension($source.Name)
    $summary = $null
    $evidence = @()

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        Stop-MT
        Clear-Journal $journalRoots
        $ini = Join-Path $evidenceDir "$base-attempt$attempt.ini"
        @"
[Charts]
ProfileLast=default
MaxBars=50000

[Experts]
AllowLiveTrading=0
AllowDllImport=0
Enabled=1

[StartUp]
Script=Tests\$base
Symbol=EURUSD
Period=M1
ShutdownTerminal=1
"@ | Set-Content $ini -Encoding ascii

        Write-Host "Running $base (attempt $attempt/3)..."
        $proc = Start-Process $terminal -ArgumentList @("/config:$ini", "/portable") -PassThru
        $absoluteDeadline = (Get-Date).AddSeconds(35)
        $loadedAt = $null
        $executionAt = $null
        $journal = ""

        try {
            while ((Get-Date) -lt $absoluteDeadline) {
                Start-Sleep -Milliseconds 500
                $now = Get-Date
                $journal = Read-Journal $journalRoots
                $summary = Get-Summary $journal $base
                if ($null -ne $summary) { break }

                if ($null -eq $loadedAt -and
                    $journal -match ("(?im)script\s+" + [regex]::Escape($base) + ".*loaded successfully")) {
                    $loadedAt = $now
                }
                if ($null -eq $executionAt -and
                    $journal -match ("(?m)\t" + [regex]::Escape($base) + "\s+\([^\r\n]*\)\t")) {
                    $executionAt = $now
                }

                if ($null -ne $executionAt -and ($now - $executionAt).TotalSeconds -ge 20) {
                    break
                }
                if ($null -eq $executionAt -and $null -ne $loadedAt -and
                    ($now - $loadedAt).TotalSeconds -ge 6) {
                    break
                }
                if ($proc.HasExited) {
                    Start-Sleep -Seconds 1
                    $journal = Read-Journal $journalRoots
                    $summary = Get-Summary $journal $base
                    break
                }
            }
        }
        finally {
            if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
            Stop-MT
        }

        $evidence += "===== $base attempt $attempt/3 =====`n$journal"
        if ($null -ne $summary) {
            if ($summary.Fail -ne 0) { throw "$base reported $($summary.Fail) failed assertion(s)" }
            if ($summary.Pass -le 0) { throw "$base reported no passing assertions" }
            Write-Host "$base runtime result: PASS=$($summary.Pass) FAIL=$($summary.Fail)"
            break
        }

        if ($null -ne $executionAt) {
            throw "$base entered execution but emitted no recognized summary — real runtime failure"
        }
        if ($attempt -lt 3) { Write-Warning "$base was loaded but OnStart was not dispatched; retrying clean startup." }
    }

    $runtimeLog = Join-Path $evidenceDir "$base-runtime.log"
    ($evidence -join "`n") | Set-Content $runtimeLog -Encoding utf8
    if ($null -eq $summary) { throw "$base did not enter OnStart after 3 clean launches — see $runtimeLog" }
}

Write-Host "MQL5 AUTOMATED TESTS PASS — $($tests.Count) scripts compiled and executed"
