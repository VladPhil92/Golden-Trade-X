param(
  [string]$Python = "python",
  [int]$StartYear = 2021,
  [int]$EndYear = 2025,
  [string]$SourceDir = "data/research/calendar-sources/v1",
  [string]$ReviewDir = "data/research/calendar-review"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
  param([string]$Label, [scriptblock]$Command)
  Write-Host "[GTX] $Label..." -ForegroundColor Cyan
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
  Invoke-Checked "Checking Python" { & $Python --version }

  Invoke-Checked "Capturing official BLS/Federal Reserve source snapshots" {
    & $Python scripts/capture_official_calendar_sources.py `
      --start-year $StartYear `
      --end-year $EndYear `
      --output-dir $SourceDir
  }

  $manifest = Join-Path $SourceDir "source_manifest.json"
  if (-not (Test-Path $manifest -PathType Leaf)) {
    throw "Capture completed without source_manifest.json: $manifest"
  }

  New-Item -ItemType Directory -Force -Path $ReviewDir | Out-Null
  $calendar = Join-Path $ReviewDir "economic_calendar.generated.json"
  $audit = Join-Path $ReviewDir "economic_calendar.audit.json"
  $include = Join-Path $ReviewDir "EconomicCalendarData.generated.mqh"

  Invoke-Checked "Materializing calendar from verified immutable snapshots" {
    & $Python scripts/materialize_verified_official_calendar.py `
      --start-year $StartYear `
      --end-year $EndYear `
      --source-dir $SourceDir `
      --output $calendar `
      --audit-output $audit
  }

  Invoke-Checked "Validating generated economic-calendar contract" {
    & $Python scripts/economic_calendar_contract.py `
      --contract $calendar `
      --generate-mql5 $include
  }

  Invoke-Checked "Verifying generated MQL5 include" {
    & $Python scripts/economic_calendar_contract.py `
      --contract $calendar `
      --verify-mql5 $include
  }

  $calendarDoc = Get-Content $calendar -Raw | ConvertFrom-Json
  if ($calendarDoc.approved -ne $false) {
    throw "Generated review calendar must remain approved=false"
  }

  $auditDoc = Get-Content $audit -Raw | ConvertFrom-Json
  if ($auditDoc.source_manifest_verified -ne $true) {
    throw "Calendar audit does not confirm verified source manifest"
  }
  if ($auditDoc.live_trading_authorized -ne $false -or $auditDoc.real_capital_authorized -ne $false) {
    throw "Calendar review artifact must deny live and real-capital trading"
  }

  Write-Host ""
  Write-Host "[GTX] OFFICIAL CALENDAR SOURCE CAPTURE READY FOR REVIEW" -ForegroundColor Green
  Write-Host "  Sources : $SourceDir"
  Write-Host "  Manifest: $manifest"
  Write-Host "  Calendar: $calendar"
  Write-Host "  Audit   : $audit"
  Write-Host "  MQL5    : $include"
  Write-Host ""
  Write-Host "No approval was granted. Do not edit these files before review/freeze." -ForegroundColor Yellow
}
finally {
  Pop-Location
}
