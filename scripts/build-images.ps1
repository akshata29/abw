#requires -Version 7
<#
.SYNOPSIS
  Builds container images in ACR Tasks - no local Docker needed.

.DESCRIPTION
  -Target mcp  (default)  the single MCP server image (abw-mcp). One image, six behaviours: the MCP_SERVER env var
                          (research | wall | actions | private | legacy | vendor) selects the tool set and the
                          authorization posture at start-up (see src\mcp\README.md). Writes infra\generated\images.json.
  -Target seed            the in-VNet seeding job image (abw-seed). Writes infra\generated\images-seed.json.

.EXAMPLE
  .\scripts\build-images.ps1
  .\scripts\build-images.ps1 -Target seed
#>
[CmdletBinding()]
param(
  [ValidateSet('mcp', 'seed')]
  [string]$Target = 'mcp',
  [string]$Tag = (Get-Date -Format 'yyyyMMdd-HHmmss')
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$cfg   = Get-AbwConfig
$names = Get-AbwNames $cfg
$repo  = if ($Target -eq 'seed') { 'abw-seed' } else { 'abw-mcp' }
$src   = Join-Path $script:RepoRoot ($(if ($Target -eq 'seed') { 'src\seed' } else { 'src\mcp' }))
$out   = if ($Target -eq 'seed') { 'images-seed.json' } else { 'images.json' }

Write-Step "ACR build ${repo}:$Tag in $($names.acr)"
# Windows az CLI can crash while streaming pip progress (cp1252); the cloud build is unaffected, so verify the run itself.
$env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
& az acr build -r $names.acr -t "${repo}:$Tag" --platform linux/amd64 --only-show-errors --no-logs $src
if ($LASTEXITCODE -ne 0) {
  Write-Warn2 'az acr build returned non-zero; checking the ACR run status'
  $run = & az acr task list-runs -r $names.acr --top 1 --query '[0].{s:status,t:outputImages[0].tag}' -o json | ConvertFrom-Json
  if ($run.t -ne $Tag -or $run.s -ne 'Succeeded') { throw "az acr build failed (latest run: $($run.s) / $($run.t))" }
}

$login = & az acr show -n $names.acr --query loginServer -o tsv
Save-Json (Join-Path $script:GenDir $out) ([ordered]@{ tag = $Tag; image = "$login/${repo}:$Tag"; builtAt = (Get-Date).ToString('o') })
Write-Ok "$login/${repo}:$Tag"
