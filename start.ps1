[CmdletBinding()]
param(
    [string]$UpstreamRepo = $env:UPSTREAM_REPO,
    [string]$BranchId = $env:UPSTREAM_REF
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bash = Get-Command bash -ErrorAction SilentlyContinue

if (-not $bash) {
    throw 'bash is required. On Windows use Git Bash, MSYS2, WSL, or run this inside GitHub Actions.'
}

$argsList = @()
if ($UpstreamRepo) { $argsList += $UpstreamRepo }
if ($BranchId) { $argsList += $BranchId }

& $bash.Source (Join-Path $root 'start') @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
