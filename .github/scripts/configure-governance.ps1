param(
    [string]$Repository = "VladPhil92/Golden-Trade-X",
    [string]$Branch = "main",
    [ValidateRange(0, 6)]
    [int]$RequiredApprovals = 0
)

$ErrorActionPreference = "Stop"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found. Install GitHub CLI and authenticate with 'gh auth login'."
    }
}

Require-Command "gh"

$null = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run 'gh auth login' with an owner/admin account for $Repository."
}

# These aggregate jobs are the only checks that belong in branch protection.
# Each one fails closed when any of its underlying jobs fails.
$requiredChecks = @(
    "CI required gate",
    "Security required gate",
    "MQL5 required gate",
    "Reproducibility required gate"
)

$reviewProtection = @{
    dismiss_stale_reviews           = $true
    require_code_owner_reviews      = ($RequiredApprovals -gt 0)
    required_approving_review_count = $RequiredApprovals
    require_last_push_approval      = $false
}

$payload = @{
    required_status_checks = @{
        strict   = $true
        contexts = $requiredChecks
    }
    enforce_admins                 = $true
    required_pull_request_reviews  = $reviewProtection
    restrictions                   = $null
    required_linear_history        = $false
    allow_force_pushes             = $false
    allow_deletions                = $false
    block_creations                = $false
    required_conversation_resolution = $true
    lock_branch                    = $false
    allow_fork_syncing             = $true
} | ConvertTo-Json -Depth 8

Write-Host "Applying branch protection to $Repository:$Branch ..."
$payload | gh api `
    --method PUT `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2026-03-10" `
    "repos/$Repository/branches/$Branch/protection" `
    --input - | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "GitHub rejected the branch-protection update. The authenticated account/token must have Administration: write permission."
}

$branchInfo = gh api `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2026-03-10" `
    "repos/$Repository/branches/$Branch" | ConvertFrom-Json

if (-not $branchInfo.protected) {
    throw "Verification failed: $Branch is still not reported as protected."
}

$protection = gh api `
    -H "Accept: application/vnd.github+json" `
    -H "X-GitHub-Api-Version: 2026-03-10" `
    "repos/$Repository/branches/$Branch/protection" | ConvertFrom-Json

if (-not $protection.required_status_checks.strict) {
    throw "Verification failed: required status checks are not strict/up-to-date."
}

$actualContexts = @($protection.required_status_checks.contexts)
foreach ($check in $requiredChecks) {
    if ($actualContexts -notcontains $check) {
        throw "Verification failed: required check '$check' is not enforced."
    }
}

if ($protection.allow_force_pushes.enabled) {
    throw "Verification failed: force pushes are still allowed."
}
if ($protection.allow_deletions.enabled) {
    throw "Verification failed: branch deletion is still allowed."
}
if (-not $protection.required_conversation_resolution.enabled) {
    throw "Verification failed: conversation resolution is not required."
}

Write-Host "GOVERNANCE PASS"
Write-Host "- Protected branch: $Branch"
Write-Host "- Pull requests required"
Write-Host "- Branch must be up to date before merge"
Write-Host "- Required checks: $($requiredChecks -join ', ')"
Write-Host "- Force pushes blocked"
Write-Host "- Branch deletion blocked"
Write-Host "- Conversation resolution required"
Write-Host "- Required approvals: $RequiredApprovals"

if ($RequiredApprovals -eq 0) {
    Write-Host "Note: approval count is 0 to avoid deadlocking a single-maintainer repository. Code-owner and last-push approval are disabled in this mode. Set -RequiredApprovals 1 when an independent reviewer is available."
}
