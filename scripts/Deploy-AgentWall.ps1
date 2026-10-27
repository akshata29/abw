#requires -Version 7
<#
.SYNOPSIS
  One-command, resumable deployment of "Agents Behind the Wall" into your own Azure subscription and Entra tenant.

.DESCRIPTION
  Runs the repo's stage scripts in the proven order (the order of README.md "Quick start"), remembers progress in
  infra\generated\deploy-state.json so an interrupted or failed run resumes where it stopped, then verifies the result
  read-only and prints the few steps that need a human (persona MFA and Foundry consent, optional admin-portal switches,
  the jump box sign-in).

  Default scope is everything: Entra apps, groups and five persona users; network; Foundry account, project and model;
  platform (Cosmos DB, Storage, Key Vault, ACR, AI Search, private endpoints); six MCP Container Apps; API Management;
  Foundry connections and agents; the Azure Policy initiative; Sentinel rules, KQL function pack and workbook; Front Door;
  budget; the Bastion jump box and the demo console on it.

  Start with -CheckOnly. It is strictly read-only: prerequisites, sign-in, permissions, quota, names, template compile
  and the plan. (Loading the shared helpers creates the two empty git-ignored folders infra\generated and .secrets.)

  You need Windows, PowerShell 7, Azure CLI 2.61+, Python 3.11+, azd (Foundry connections), Owner on the subscription and
  Entra rights to create apps, groups and users and to grant admin consent (Global Administrator is the simplest).

  One deployment per Entra tenant and per Azure subscription: the Entra objects are tenant-wide with fixed abw-* names and
  the policy initiative abw-agent-platform-controls is per subscription. A second deployment would take them over.

  Exit codes: 0 done, 1 a required step failed or a blocking problem was found, 2 done but an optional step failed,
  3 -CheckOnly found a blocking problem.

.PARAMETER SubscriptionId
  Subscription to deploy into. Default: the current az default subscription.
.PARAMETER TenantId
  Optional guard: stop unless the subscription belongs to this tenant.
.PARAMETER Location
  Azure region for the platform (default eastus2). AI Search uses -SearchLocation (eastus when Location is eastus2).
.PARAMETER Workload
  Naming workload code, 3-5 lowercase letters or digits (default abw). EnvName and Instance complete the CAF-style names.
.PARAMETER UniqueSuffix
  4 lowercase letters or digits that make globally unique names unique. Generated (and checked for free names) when omitted.
.PARAMETER ResourceGroupName
  Override the resource group name (default rg-<workload>-<env>-<region code>-<instance>).
.PARAMETER AlertEmail
  Optional e-mail for the Sentinel/Monitor action group.
.PARAMETER PublisherEmail
  API Management publisher e-mail (default: your sign-in name).
.PARAMETER EntraWorkspaceId
  Optional resource id of a read-only Log Analytics workspace that receives Entra sign-in logs. Adds the Entra rows to AbwFullChain.
.PARAMETER TenantDomain
  Domain for the persona users (default: the tenant's initial *.onmicrosoft.com domain).
.PARAMETER ModelName
  Model deployed to the Foundry account (default gpt-5.4-mini); ModelVersion, ModelSku and ModelCapacity (K TPM) complete it.
.PARAMETER SkipJumpBox
  Do not deploy the Bastion jump box (also skips the console on it).
.PARAMETER SkipConsole
  Do not install the demo console on the jump box.
.PARAMETER SkipFrontDoor
  Do not deploy the agent front door (Act 7).
.PARAMETER SkipBudget
  Do not create the resource-group cost budget.
.PARAMETER SkipGuardrail
  Do not attach the Foundry guardrail and publish the shielded red-team agent.
.PARAMETER WithExtras
  Also run scripts\extras-defender-sentinel.ps1 and scripts\extras-agent-identity.ps1 -SkipConditionalAccess.
.PARAMETER RunProofs
  Also run demo\prove.py (about 30 minutes, calls the gateway) and demo\scoreboard.py --check.
.PARAMETER Force
  Run the selected steps again even if they are already done.
.PARAMETER ResetState
  Archive infra\generated and .secrets to _archive\state-<time>\ and start from a fresh configuration. Does not touch Azure or Entra.
.PARAMETER AdoptExistingEntra
  Allow Phase 1 to update abw-* Entra objects that already exist in the tenant but are not recorded locally.
.PARAMETER CheckOnly
  Read-only readiness check and plan (alias -DryRun).
.PARAMETER Yes
  Skip the typed confirmation (for unattended runs).
.PARAMETER InstallPrereqs
  Install missing Azure CLI, azd and Python 3.11 with winget.
.PARAMETER From
  Start at this step; earlier steps are treated as done.
.PARAMETER Only
  Run only these steps (comma separated).
.PARAMETER Until
  Stop after this step.
.PARAMETER Skip
  Skip these steps (comma separated).

.EXAMPLE
  .\scripts\Deploy-AgentWall.ps1 -CheckOnly
.EXAMPLE
  .\scripts\Deploy-AgentWall.ps1 -SubscriptionId <subscription-id> -AlertEmail me@contoso.com
.EXAMPLE
  .\scripts\Deploy-AgentWall.ps1 -From apim          # resume at a step
.EXAMPLE
  .\scripts\Deploy-AgentWall.ps1 -Only connections -Force
#>
[CmdletBinding()]
param(
  [string]$SubscriptionId,
  [string]$TenantId,
  [string]$Location = 'eastus2',
  [string]$SearchLocation,
  [ValidatePattern('(?-i)^[a-z0-9]{3,5}$')][string]$Workload = 'abw',
  [ValidatePattern('(?-i)^[a-z0-9]{2,5}$')][string]$EnvName = 'demo',
  [ValidatePattern('(?-i)^[0-9]{3}$')][string]$Instance = '001',
  [ValidatePattern('(?-i)^[a-z0-9]{4}$')][string]$UniqueSuffix,
  [string]$ResourceGroupName,
  [string]$AlertEmail,
  [string]$PublisherEmail,
  [string]$EntraWorkspaceId,
  [string]$TenantDomain,
  [string]$ModelName = 'gpt-5.4-mini',
  [string]$ModelVersion = '2026-03-17',
  [string]$ModelSku = 'GlobalStandard',
  [ValidateRange(1, 100000)][int]$ModelCapacity = 100,
  [switch]$SkipJumpBox,
  [switch]$SkipConsole,
  [switch]$SkipFrontDoor,
  [switch]$SkipBudget,
  [switch]$SkipGuardrail,
  [switch]$WithExtras,
  [switch]$RunProofs,
  [switch]$Force,
  [switch]$ResetState,
  [switch]$AdoptExistingEntra,
  [Alias('DryRun')][switch]$CheckOnly,
  [switch]$Yes,
  [switch]$InstallPrereqs,
  [string]$From,
  [string[]]$Only,
  [string]$Until,
  [string[]]$Skip
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"

$script:LogWriter = $null
$script:ExitCode = 0
$script:TransientPattern = 'OperationInProgress|AnotherOperationInProgress|ConflictingOperationInProgress|RetryableError|ServiceUnavailable|GatewayTimeout|TooManyRequests|InternalServerError'
$script:RegionCodes = @{
  eastus2 = 'eus2'; eastus = 'eus'; westus3 = 'wus3'; westus2 = 'wus2'; westus = 'wus'; centralus = 'cus'
  northcentralus = 'ncus'; southcentralus = 'scus'; westeurope = 'weu'; northeurope = 'neu'; uksouth = 'uks'
  swedencentral = 'sec'; francecentral = 'frc'; germanywestcentral = 'gwc'; canadacentral = 'cac'
  australiaeast = 'aue'; japaneast = 'jpe'; southeastasia = 'sea'
}

# ---------------------------------------------------------------------------
# Output (console + log file)
# ---------------------------------------------------------------------------
function Write-Log {
  param([string]$Text)
  if ($script:LogWriter) {
    $clean = [regex]::Replace($Text, '\x1B\[[0-9;?]*[ -/]*[@-~]', '')
    $script:LogWriter.WriteLine($clean)
  }
}
function Out-Line {
  param([string]$Text = '', [string]$Color = '')
  if ($Color) { Write-Host $Text -ForegroundColor $Color } else { Write-Host $Text }
  Write-Log $Text
}
function Write-Head { param([string]$Text) Out-Line ''; Out-Line "== $Text" 'Cyan' }
function Write-Good { param([string]$Text) Out-Line "   [ok]   $Text" 'Green' }
function Write-Bad  { param([string]$Text) Out-Line "   [FAIL] $Text" 'Red' }
function Write-Warn { param([string]$Text) Out-Line "   [warn] $Text" 'Yellow' }
function Write-Dim  { param([string]$Text) Out-Line "          $Text" 'DarkGray' }

function Hide-Guid {
  param([string]$Text)
  if (-not $Text) { return $Text }
  return [regex]::Replace($Text, '\b([0-9a-fA-F]{8})-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b', '$1-****')
}

function Format-Duration {
  param([double]$Seconds)
  $t = [TimeSpan]::FromSeconds($Seconds)
  if ($t.TotalHours -ge 1) { return ('{0}h {1:00}m' -f [int][math]::Floor($t.TotalHours), $t.Minutes) }
  if ($t.TotalMinutes -ge 1) { return ('{0}m {1:00}s' -f [int][math]::Floor($t.TotalMinutes), $t.Seconds) }
  return ('{0}s' -f [int]$t.TotalSeconds)
}

# ---------------------------------------------------------------------------
# Options, context, names
# ---------------------------------------------------------------------------
function Get-DefaultOptions {
  return @{
    SubscriptionId = ''; TenantId = ''; Location = 'eastus2'; SearchLocation = ''; Workload = 'abw'; EnvName = 'demo'; Instance = '001'
    UniqueSuffix = ''; ResourceGroupName = ''; AlertEmail = ''; PublisherEmail = ''; EntraWorkspaceId = ''; TenantDomain = ''
    ModelName = 'gpt-5.4-mini'; ModelVersion = '2026-03-17'; ModelSku = 'GlobalStandard'; ModelCapacity = 100
    SkipJumpBox = $false; SkipConsole = $false; SkipFrontDoor = $false; SkipBudget = $false; SkipGuardrail = $false
    WithExtras = $false; RunProofs = $false; Force = $false; ResetState = $false; AdoptExistingEntra = $false
    CheckOnly = $false; Yes = $false; InstallPrereqs = $false
    From = ''; Until = ''; Only = @(); Skip = @()
  }
}

function New-RunContext {
  param([Parameter(Mandatory)][hashtable]$P)
  $flat = { param($v) @($v | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
  return [pscustomobject]@{
    RepoRoot       = $script:RepoRoot
    Gen            = $script:GenDir
    Secrets        = $script:SecretsDir
    Pwsh           = (Get-Process -Id $PID).Path
    VenvPython     = (Join-Path $script:RepoRoot '.venv\Scripts\python.exe')
    Opt            = $P
    CheckOnly      = [bool]$P.CheckOnly
    Yes            = [bool]$P.Yes
    Force          = [bool]$P.Force
    ResetState     = [bool]$P.ResetState
    AdoptExistingEntra = [bool]$P.AdoptExistingEntra
    InstallPrereqs = [bool]$P.InstallPrereqs
    From           = [string]$P.From
    Until          = [string]$P.Until
    Only           = @(& $flat $P.Only)
    Skip           = @(& $flat $P.Skip)
    AssumeFresh    = $false
    GraphOk        = $true
  }
}

function Get-RegionCode {
  param([string]$Location)
  $k = $Location.ToLowerInvariant()
  if ($script:RegionCodes.ContainsKey($k)) { return [string]$script:RegionCodes[$k] }
  return $k.Substring(0, [Math]::Min(4, $k.Length))
}

function New-UniqueSuffix {
  $chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
  return (-join (1..4 | ForEach-Object { $chars[[System.Security.Cryptography.RandomNumberGenerator]::GetInt32($chars.Length)] }))
}

function Test-AbwNameRules {
  param($Cfg)
  $n = Get-AbwNames $Cfg
  $rules = @(
    @{ Key = 'storage';     Max = 24; Re = '^[a-z0-9]+$';                    What = 'storage account' }
    @{ Key = 'asvcStorage'; Max = 24; Re = '^[a-z0-9]+$';                    What = 'agent-service storage account' }
    @{ Key = 'kv';          Max = 24; Re = '^[a-z][a-z0-9-]*[a-z0-9]$';      What = 'Key Vault' }
    @{ Key = 'acr';         Max = 50; Re = '^[a-z0-9]+$';                    What = 'container registry' }
    @{ Key = 'cosmos';      Max = 44; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'Cosmos DB account' }
    @{ Key = 'asvcCosmos';  Max = 44; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'agent-service Cosmos DB account' }
    @{ Key = 'apim';        Max = 50; Re = '^[a-z][a-z0-9-]*[a-z0-9]$';      What = 'API Management service' }
    @{ Key = 'search';      Max = 60; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'AI Search service' }
    @{ Key = 'asvcSearch';  Max = 60; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'agent-service AI Search service' }
    @{ Key = 'foundry';     Max = 64; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'Foundry account' }
    @{ Key = 'project';     Max = 64; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'Foundry project' }
    @{ Key = 'jumpVm';      Max = 64; Re = '^[a-z0-9][a-z0-9-]*[a-z0-9]$';   What = 'jump box VM' }
    @{ Key = 'rg';          Max = 90; Re = '^[A-Za-z0-9._()-]*[A-Za-z0-9_()-]$'; What = 'resource group' }
  )
  $problems = New-Object System.Collections.Generic.List[string]
  foreach ($r in $rules) {
    $v = [string]$n[$r.Key]
    if (-not $v) { continue }
    if ($v.Length -gt $r.Max) { $problems.Add("$($r.What) name '$v' is $($v.Length) characters; the maximum is $($r.Max)") }
    elseif ($v -cnotmatch $r.Re) { $problems.Add("$($r.What) name '$v' contains characters that are not allowed") }
  }
  return @($problems)
}

# ---------------------------------------------------------------------------
# State (infra\generated\deploy-state.json)
# ---------------------------------------------------------------------------
function Read-State {
  param($Ctx)
  $p = Join-Path $Ctx.Gen 'deploy-state.json'
  $s = $null
  if (Test-Path -LiteralPath $p) {
    try { $s = Get-Content -Raw -LiteralPath $p | ConvertFrom-Json -AsHashtable } catch { $s = $null }
    if ($s -isnot [hashtable]) {
      $s = $null
      Write-Warn 'infra\generated\deploy-state.json is empty or not valid JSON, so it is ignored and the recorded step results are lost.'
      if (-not $Ctx.CheckOnly) {
        try { Copy-Item -LiteralPath $p -Destination "$p.bad" -Force; Write-Dim 'A copy of the unreadable file is kept as deploy-state.json.bad.' } catch { }
      }
    }
  }
  if (-not $s) { $s = @{ schema = 1; createdAt = (Get-Date).ToUniversalTime().ToString('o'); steps = @{}; runs = @(); verify = @{} } }
  if (-not $s.ContainsKey('steps') -or $null -eq $s.steps) { $s.steps = @{} }
  if (-not $s.ContainsKey('runs') -or $null -eq $s.runs) { $s.runs = @() }
  return $s
}

function Save-State {
  param($Ctx, $State)
  if ($Ctx.CheckOnly) { return }
  $path = Join-Path $Ctx.Gen 'deploy-state.json'
  $tmp = "$path.tmp"
  Save-Json $tmp $State
  [System.IO.File]::Move($tmp, $path, $true)
}

function Set-StepState {
  param($Ctx, $State, [string]$Id, [string]$Status, [double]$Seconds = 0, [int]$Attempts = 1, [string]$Note = '')
  $State.steps[$Id] = [ordered]@{
    status = $Status; updatedAt = (Get-Date).ToUniversalTime().ToString('o')
    seconds = [math]::Round($Seconds, 1); attempts = $Attempts; note = $Note
  }
  Save-State -Ctx $Ctx -State $State
}

# ---------------------------------------------------------------------------
# Step table
# ---------------------------------------------------------------------------
function GenFile  { param([string]$Name) return "infra\generated\$Name" }
function GenFiles { param([string[]]$Names) return @($Names | ForEach-Object { "infra\generated\$_" }) }

function New-Step {
  param(
    [Parameter(Mandatory)][string]$Id,
    [Parameter(Mandatory)][string]$Title,
    [Parameter(Mandatory)][string]$Path,
    [ValidateSet('ps', 'py')][string]$Kind = 'ps',
    [string[]]$ScriptArgs = @(),
    [string[]]$Artifacts = @(),
    [string[]]$Produces = @(),
    [string[]]$Needs = @(),
    [scriptblock]$DoneProbe,
    [scriptblock]$Infer,
    [scriptblock]$SkipIf,
    [scriptblock]$Before,
    [switch]$StateOnly,
    [bool]$Fatal = $true,
    [int]$EtaMin = 0,
    [int]$EtaMax = 0,
    [string]$Disabled = '',
    [string]$Pattern = '',
    [int]$RetryDelay = 60
  )
  return [pscustomobject]@{
    Id = $Id; Title = $Title; Path = $Path; Kind = $Kind; ScriptArgs = @($ScriptArgs)
    Artifacts = @($Artifacts); Produces = @($Produces); Needs = @($Needs)
    DoneProbe = $DoneProbe; Infer = $Infer; SkipIf = $SkipIf; Before = $Before
    StateOnly = [bool]$StateOnly; Fatal = $Fatal; EtaMin = $EtaMin; EtaMax = $EtaMax
    Disabled = $Disabled; Pattern = $Pattern; RetryDelay = $RetryDelay
    Exe = $null; ExeArgs = @()
  }
}

function Test-AzdExtension {
  param([string]$Id = 'azure.ai.connections')
  $o = (& azd extension list --installed -o json 2>$null | Out-String)
  if ($LASTEXITCODE -ne 0 -or -not $o.Trim()) { return $false }
  try {
    $found = @($o | ConvertFrom-Json) | Where-Object { $_.PSObject.Properties['id'] -and $_.id -eq $Id }
    return [bool]$found
  } catch { return $false }
}

function Initialize-Azd {
  & azd config set auth.useAzCliAuth true 2>&1 | ForEach-Object { Write-Log ([string]$_) }
  if (-not (Test-AzdExtension)) {
    Out-Line '   installing the azd extension azure.ai.connections'
    & azd extension install azure.ai.connections 2>&1 | ForEach-Object { Out-Line ([string]$_) }
    if (-not (Test-AzdExtension)) { throw 'The azd extension azure.ai.connections is not installed. Run: azd extension install azure.ai.connections' }
  }
}

function Get-StepTable {
  param($Ctx)
  $o = $Ctx.Opt
  $jumpOff    = if ($o.SkipJumpBox) { 'skipped: -SkipJumpBox' } else { '' }
  $consoleOff = if ($o.SkipJumpBox) { 'skipped: -SkipJumpBox' } elseif ($o.SkipConsole) { 'skipped: -SkipConsole' } else { '' }
  $frontOff   = if ($o.SkipFrontDoor) { 'skipped: -SkipFrontDoor' } else { '' }
  $budgetOff  = if ($o.SkipBudget) { 'skipped: -SkipBudget' } else { '' }
  $guardOff   = if ($o.SkipGuardrail) { 'skipped: -SkipGuardrail' } else { '' }
  $extrasOff  = if ($o.WithExtras) { '' } else { 'off by default: add -WithExtras' }
  $proofsOff  = if ($o.RunProofs) { '' } else { 'off by default: add -RunProofs' }

  $probeGuardrail = { param($c)
    $p = Join-Path $c.Gen 'agents.json'
    (Test-Path -LiteralPath $p) -and ((Get-Content -Raw -LiteralPath $p) -match 'abw-wall-desk-redteam-shielded') }
  $probeJump = { param($c)
    $j = Read-Json (Join-Path $c.Gen 'jumpbox.json')
    [bool]($j -and $j.PSObject.Properties['deployedAt'] -and $j.deployedAt) }
  $probeConsole = { param($c)
    $j = Read-Json (Join-Path $c.Gen 'jumpbox.json')
    [bool]($j -and $j.PSObject.Properties['consoleOnVm'] -and $j.consoleOnVm) }
  $inferEntra2 = { param($c) Test-Path -LiteralPath (Join-Path $c.Gen 'apis.json') }
  $inferSeed = { param($c) [bool](@('connections.json', 'agents.json', 'governance.json') | Where-Object { Test-Path -LiteralPath (Join-Path $c.Gen $_) }) }
  $inferBaseline = { param($c) Test-Path -LiteralPath (Join-Path $c.Gen 'connections.json') }
  $skipNoEvidence = { param($c)
    if (-not (Test-Path -LiteralPath (Join-Path $c.RepoRoot 'demo\evidence-scrubbed\scoreboard.json'))) {
      'demo\evidence-scrubbed\scoreboard.json is missing; run python demo\scrub_evidence.py first'
    } }
  $beforeConnections = { param($c)
    if (-not $env:AZD_CONFIG_DIR) { $env:AZD_CONFIG_DIR = Join-Path $c.Secrets 'azd' }
    New-Item -ItemType Directory -Force -Path $env:AZD_CONFIG_DIR | Out-Null
    Initialize-Azd }

  $s = [System.Collections.Generic.List[object]]::new()
  $s.Add((New-Step -Id 'preflight' -Title 'Subscription preflight: resource providers, resource group' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'preflight' `
    -Artifacts (GenFiles 'preflight.json') -EtaMin 1 -EtaMax 3))
  $s.Add((New-Step -Id 'entra1' -Title 'Entra phase 1: API apps, clients, groups, five persona users' -Path 'identity\Setup-Entra.ps1' -ScriptArgs '-Phase', '1' `
    -Artifacts (GenFiles 'entra.json') -Produces '.secrets\agent-client.json' -EtaMin 3 -EtaMax 5))
  $s.Add((New-Step -Id 'network' -Title 'Network: VNet, subnets, NAT gateway' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'network' `
    -Artifacts (GenFiles 'network.json') -EtaMin 2 -EtaMax 4))
  $s.Add((New-Step -Id 'foundry' -Title 'Foundry account, project, model deployment, monitoring' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'foundry' `
    -Artifacts (GenFiles 'foundry.json') -Needs (GenFiles 'network.json') -EtaMin 15 -EtaMax 20))
  $s.Add((New-Step -Id 'foundryrbac' -Title 'Foundry role assignments' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'foundryrbac' `
    -Artifacts (GenFiles 'foundryrbac.json') -Needs (GenFiles 'foundry.json', 'entra.json') -EtaMin 1 -EtaMax 3))
  $s.Add((New-Step -Id 'platform' -Title 'Platform: Cosmos DB, Storage, Key Vault, ACR, AI Search, Container Apps environments' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'platform' `
    -Artifacts (GenFiles 'platform.json') -Needs (GenFiles 'network.json', 'entra.json') -EtaMin 10 -EtaMax 15))
  $s.Add((New-Step -Id 'images' -Title 'Build and push the MCP server image (ACR build, no local Docker)' -Path 'scripts\build-images.ps1' -ScriptArgs '-Target', 'mcp' `
    -Artifacts (GenFiles 'images.json') -Needs (GenFiles 'platform.json') -EtaMin 5 -EtaMax 8))
  $s.Add((New-Step -Id 'apps' -Title 'Six MCP Container Apps' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'apps' `
    -Artifacts (GenFiles 'apps.json') -Needs (GenFiles 'platform.json', 'entra.json', 'images.json') -EtaMin 5 -EtaMax 8))
  $s.Add((New-Step -Id 'entra2' -Title 'Entra phase 2: federated credentials for the managed identities' -Path 'identity\Setup-Entra.ps1' -ScriptArgs '-Phase', '2' `
    -StateOnly -Infer $inferEntra2 -Needs (GenFiles 'platform.json', 'entra.json') -EtaMin 1 -EtaMax 2))
  $s.Add((New-Step -Id 'apim' -Title 'API Management Standard v2 and private endpoint (the long one)' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'apim' `
    -Artifacts (GenFiles 'apim.json') -Needs (GenFiles 'network.json', 'entra.json', 'foundry.json') -EtaMin 35 -EtaMax 50))
  $s.Add((New-Step -Id 'apis' -Title 'Gateway APIs, policies and named values' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'apis' `
    -Artifacts (GenFiles 'apis.json') -Needs (GenFiles 'apps.json', 'entra.json', 'apim.json') -EtaMin 3 -EtaMax 6))
  $s.Add((New-Step -Id 'images-seed' -Title 'Build and push the seed job image' -Path 'scripts\build-images.ps1' -ScriptArgs '-Target', 'seed' `
    -Artifacts (GenFiles 'images-seed.json') -Needs (GenFiles 'platform.json') -EtaMin 3 -EtaMax 6))
  $s.Add((New-Step -Id 'seed' -Title 'Seed job: synthetic deals, documents, positions, research notes' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'seed' `
    -StateOnly -Infer $inferSeed -Needs (GenFiles 'platform.json', 'images-seed.json') -EtaMin 5 -EtaMax 12))
  $s.Add((New-Step -Id 'baseline' -Title 'Persona baseline: the signed-in admin mirrors wes + tara (before the first consent)' -Path 'identity\Use-AdminAsPersona.ps1' -ScriptArgs '-As', 'wes', '-Also', 'tara' `
    -StateOnly -Infer $inferBaseline -Needs (GenFiles 'entra.json') -EtaMin 1 -EtaMax 2))
  $s.Add((New-Step -Id 'connections' -Title 'Foundry OAuth connections to the five MCP APIs (azd)' -Path 'scripts\foundry-connections.ps1' `
    -Artifacts (GenFiles 'connections.json') -Needs ((GenFiles 'entra.json', 'apis.json', 'apps.json', 'foundry.json') + '.secrets\agent-client.json') -Before $beforeConnections -EtaMin 5 -EtaMax 10))
  $s.Add((New-Step -Id 'agents' -Title 'Publish the Foundry agents' -Kind py -Path 'src\agent\create_agents.py' `
    -Artifacts (GenFiles 'agents.json') -Needs (GenFiles 'foundry.json', 'connections.json') -EtaMin 2 -EtaMax 4))
  $s.Add((New-Step -Id 'governance' -Title 'Azure Policy initiative, guardrail, Sentinel rules, KQL function pack, workbook' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'governance' `
    -Artifacts (GenFiles 'governance.json', 'observability.json') -Needs (GenFiles 'foundry.json', 'platform.json') `
    -Pattern 'CheckAccessPrincipalCreationConcurrencyError|CheckAccessPrincipalTokenInvalid|OperationInProgress|RetryableError|ServiceUnavailable|GatewayTimeout' -RetryDelay 90 -EtaMin 8 -EtaMax 12))
  $s.Add((New-Step -Id 'guardrail' -Title 'Attach the Foundry guardrail; publish the shielded red-team agent' -Kind py -Path 'src\agent\create_agents.py' -ScriptArgs '--rai', 'abw-agent-guardrails' `
    -Artifacts (GenFiles 'agents.json') -DoneProbe $probeGuardrail -Needs (GenFiles 'agents.json', 'governance.json') -Fatal $false -Disabled $guardOff -EtaMin 1 -EtaMax 3))
  $s.Add((New-Step -Id 'frontdoor' -Title 'Agent front door (Act 7): API Management API for the agents' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'frontdoor' `
    -Artifacts (GenFiles 'frontdoor.json') -Needs (GenFiles 'apim.json') -Fatal $false -Disabled $frontOff -EtaMin 5 -EtaMax 10))
  $s.Add((New-Step -Id 'budget' -Title 'Resource-group cost budget with alerts (an alert, not a cap)' -Path 'scripts\deploy.ps1' -ScriptArgs '-Stage', 'budget' `
    -Artifacts (GenFiles 'budget.json') -Fatal $false -Disabled $budgetOff -EtaMin 1 -EtaMax 2))
  $s.Add((New-Step -Id 'jumpbox' -Title 'Bastion jump box inside the VNet (private endpoints resolve there)' -Path 'scripts\jumpbox.ps1' `
    -Artifacts (GenFiles 'jumpbox.json') -DoneProbe $probeJump -Needs (GenFiles 'network.json') -Fatal $false -Disabled $jumpOff -EtaMin 10 -EtaMax 15))
  $s.Add((New-Step -Id 'console' -Title 'Install the demo console on the jump box' -Path 'scripts\jumpbox-console.ps1' `
    -Artifacts (GenFiles 'jumpbox.json') -DoneProbe $probeConsole -Needs (GenFiles 'jumpbox.json') -SkipIf $skipNoEvidence -Fatal $false -Disabled $consoleOff -EtaMin 15 -EtaMax 25))
  $s.Add((New-Step -Id 'extras-defender' -Title 'Optional: Defender for Cloud to Sentinel wiring and read-back' -Path 'scripts\extras-defender-sentinel.ps1' `
    -Artifacts (GenFiles 'trackb-defender.json') -Needs (GenFiles 'platform.json') -Fatal $false -Disabled $extrasOff -EtaMin 2 -EtaMax 5))
  $s.Add((New-Step -Id 'extras-identity' -Title 'Optional: Agent 365 role pre-grant on API Management (no Conditional Access policy)' -Path 'scripts\extras-agent-identity.ps1' -ScriptArgs '-SkipConditionalAccess' `
    -Artifacts (GenFiles 'trackb-identity.json') -Needs (GenFiles 'apim.json', 'entra.json') -Fatal $false -Disabled $extrasOff -EtaMin 1 -EtaMax 3))
  $s.Add((New-Step -Id 'proofs' -Title 'Optional: the 18 proofs (demo\prove.py)' -Kind py -Path 'demo\prove.py' `
    -StateOnly -Needs (GenFiles 'agents.json', 'governance.json') -Fatal $false -Disabled $proofsOff -EtaMin 30 -EtaMax 40))
  $s.Add((New-Step -Id 'scoreboard' -Title 'Optional: check the proof scoreboard' -Kind py -Path 'demo\scoreboard.py' -ScriptArgs '--check' `
    -StateOnly -Fatal $false -Disabled $proofsOff -EtaMin 1 -EtaMax 1))
  return @($s)
}

function Test-StepDone {
  param($Ctx, $State, $Step)
  if ($Ctx.AssumeFresh) { return $false }
  $entry = $null
  if ($State.steps.ContainsKey($Step.Id)) { $entry = $State.steps[$Step.Id] }
  if ($entry -and ($entry.status -eq 'failed' -or $entry.status -eq 'running')) { return $false }
  if ($Step.StateOnly) {
    if ($entry) { return ($entry.status -eq 'done') }
    # Outputs on disk vouch for these steps only while no run is on record (an environment built before this script existed).
    # Once a run is on record, only recorded results count, so a skipped step is never taken for done.
    if ($Step.Infer -and @($State.runs).Count -eq 0) { return [bool](& $Step.Infer $Ctx) }
    return $false
  }
  return (@(Get-MissingOutputs -Ctx $Ctx -Step $Step).Count -eq 0)
}

# Before the first run is recorded, write down the steps that existing outputs show as done, so later runs keep treating them as done.
function Save-InferredSteps {
  param($Ctx, $State, $Steps)
  if ($Ctx.AssumeFresh -or @($State.runs).Count -gt 0) { return }
  foreach ($st in $Steps) {
    if (-not $st.StateOnly -or -not $st.Infer -or $State.steps.ContainsKey($st.Id)) { continue }
    if ([bool](& $st.Infer $Ctx)) { Set-StepState -Ctx $Ctx -State $State -Id $st.Id -Status 'done' -Note 'inferred from existing outputs' }
  }
}

function Get-MissingOutputs {
  param($Ctx, $Step)
  $missing = New-Object System.Collections.Generic.List[string]
  foreach ($a in @($Step.Artifacts)) {
    if ($a -and -not (Test-Path -LiteralPath (Join-Path $Ctx.RepoRoot $a))) { $missing.Add($a) }
  }
  if ($missing.Count -eq 0 -and $Step.DoneProbe) {
    if (-not (& $Step.DoneProbe $Ctx)) { $missing.Add('(completion marker)') }
  }
  return @($missing)
}

function Get-PlanItems {
  param($Ctx, $State, $Steps)
  $ids = @($Steps | ForEach-Object { $_.Id })
  foreach ($x in (@($Ctx.From, $Ctx.Until) + @($Ctx.Only) + @($Ctx.Skip))) {
    if ($x -and ($ids -notcontains $x)) { throw "Unknown step '$x'. Valid steps: $($ids -join ', ')" }
  }
  $fromIdx = 0
  if ($Ctx.From) { $fromIdx = [array]::IndexOf($ids, $Ctx.From) }
  $untilIdx = $ids.Count - 1
  if ($Ctx.Until) { $untilIdx = [array]::IndexOf($ids, $Ctx.Until) }
  if ($fromIdx -gt $untilIdx) { throw "-From $($Ctx.From) comes after -Until $($Ctx.Until) in the step order, so no step is selected. Step order: $($ids -join ', ')" }
  foreach ($o in @($Ctx.Only)) {
    if (-not $o) { continue }
    $oi = [array]::IndexOf($ids, $o)
    if ($oi -lt $fromIdx -or $oi -gt $untilIdx) { throw "-Only $o is outside the range selected by -From and -Until ($($ids[$fromIdx]) to $($ids[$untilIdx])). Step order: $($ids -join ', ')" }
  }
  $items = [System.Collections.Generic.List[object]]::new()
  for ($i = 0; $i -lt $Steps.Count; $i++) {
    $st = $Steps[$i]
    $action = 'run'
    $note = ''
    if ($st.Disabled) { $action = 'skip'; $note = $st.Disabled }
    elseif ($Ctx.Skip -contains $st.Id) { $action = 'skip'; $note = 'skipped by -Skip' }
    elseif ($Ctx.Only.Count -gt 0 -and ($Ctx.Only -notcontains $st.Id)) { $action = 'skip'; $note = 'not selected by -Only' }
    elseif ($i -lt $fromIdx) { $action = 'assumed'; $note = 'before -From (assumed done)' }
    elseif ($i -gt $untilIdx) { $action = 'skip'; $note = 'after -Until' }
    else {
      $done = Test-StepDone -Ctx $Ctx -State $State -Step $st
      if ($done -and -not $Ctx.Force) {
        $action = 'done'
        $note = 'already done'
        if ($Ctx.Only.Count -gt 0) { $note = 'already done (add -Force to run it again)' }
      } else {
        $reason = $null
        if ($st.SkipIf) { $reason = & $st.SkipIf $Ctx }
        if ($reason) { $action = 'skip'; $note = [string]$reason }
      }
    }
    $items.Add([pscustomobject]@{ Step = $st; Action = $action; Note = $note; Index = $i })
  }
  return @($items)
}

function Test-PlanNeeds {
  param($Ctx, $Items)
  $problems = New-Object System.Collections.Generic.List[string]
  $produced = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($it in $Items) {
    if ($it.Action -ne 'run') { continue }
    foreach ($need in @($it.Step.Needs)) {
      if (-not (Test-Path -LiteralPath (Join-Path $Ctx.RepoRoot $need)) -and -not $produced.Contains($need)) {
        $problems.Add("step '$($it.Step.Id)' needs $need, which does not exist and no earlier selected step produces it")
      }
    }
    foreach ($a in (@($it.Step.Artifacts) + @($it.Step.Produces))) { if ($a) { [void]$produced.Add($a) } }
  }
  return @($problems)
}

# ---------------------------------------------------------------------------
# Running a step
# ---------------------------------------------------------------------------
function Invoke-StepProcess {
  param($Ctx, $Step)
  $exe = $Ctx.Pwsh
  $argList = @()
  if ($Step.Exe) { $exe = $Step.Exe; $argList = @($Step.ExeArgs) }
  elseif ($Step.Kind -eq 'py') { $exe = $Ctx.VenvPython; $argList = @((Join-Path $Ctx.RepoRoot $Step.Path)) + @($Step.ScriptArgs) }
  else { $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Ctx.RepoRoot $Step.Path)) + @($Step.ScriptArgs) }

  $tail = New-Object System.Collections.Generic.Queue[string]
  $transient = $false
  $pattern = if ($Step.Pattern) { $Step.Pattern } else { $script:TransientPattern }
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $code = 1
  $global:LASTEXITCODE = $null
  Push-Location -LiteralPath $Ctx.RepoRoot
  try {
    & $exe @argList 2>&1 | ForEach-Object {
      $line = [string]$_
      Out-Line $line
      $tail.Enqueue($line)
      while ($tail.Count -gt 40) { [void]$tail.Dequeue() }
      if (-not $transient -and $line -match $pattern) { $transient = $true }
    }
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
  } catch {
    Out-Line "   could not run the step: $($_.Exception.Message)" 'Red'
    $tail.Enqueue([string]$_.Exception.Message)
    $code = 1
  } finally {
    Pop-Location
    $ErrorActionPreference = $prev
  }
  $sw.Stop()
  return [pscustomobject]@{ ExitCode = [int]$code; Seconds = $sw.Elapsed.TotalSeconds; Tail = @($tail); Transient = $transient }
}

function Invoke-Step {
  param($Ctx, $State, $Step, [int]$Number, [int]$Total)
  $eta = ''
  if ($Step.EtaMax -gt 0) { $eta = " (rough estimate $($Step.EtaMin)-$($Step.EtaMax) min)" }
  Out-Line ''
  Out-Line ("[{0}/{1}] {2}: {3}{4}" -f $Number, $Total, $Step.Id, $Step.Title, $eta) 'Cyan'

  if ($Step.Before) {
    try { & $Step.Before $Ctx | Out-Null } catch {
      $why = "preparation failed: $($_.Exception.Message)"
      Set-StepState -Ctx $Ctx -State $State -Id $Step.Id -Status 'failed' -Note $why
      Write-Bad "$($Step.Id) $why"
      return [pscustomobject]@{ Ok = $false; Seconds = 0.0; Reason = $why; Tail = @($why) }
    }
  }

  $maxAttempts = 3
  $attempt = 0
  $totalSec = 0.0
  while ($true) {
    $attempt++
    Set-StepState -Ctx $Ctx -State $State -Id $Step.Id -Status 'running' -Attempts $attempt
    $r = Invoke-StepProcess -Ctx $Ctx -Step $Step
    $totalSec += $r.Seconds
    $reason = ''
    if ($r.ExitCode -ne 0) { $reason = "exit code $($r.ExitCode)" }
    else {
      $missing = @(Get-MissingOutputs -Ctx $Ctx -Step $Step)
      if ($missing.Count -eq 0) {
        Set-StepState -Ctx $Ctx -State $State -Id $Step.Id -Status 'done' -Seconds $totalSec -Attempts $attempt
        Write-Good ("{0} finished in {1}" -f $Step.Id, (Format-Duration $totalSec))
        return [pscustomobject]@{ Ok = $true; Seconds = $totalSec; Reason = ''; Tail = @() }
      }
      $reason = "finished but did not leave the expected result: $($missing -join ', ')"
    }
    if ($r.Transient -and $r.ExitCode -ne 0 -and $attempt -lt $maxAttempts) {
      Write-Warn "$($Step.Id) hit a transient error ($reason); waiting $($Step.RetryDelay) s, then trying again (attempt $($attempt + 1) of $maxAttempts)"
      Start-Sleep -Seconds $Step.RetryDelay
      continue
    }
    Set-StepState -Ctx $Ctx -State $State -Id $Step.Id -Status 'failed' -Seconds $totalSec -Attempts $attempt -Note $reason
    Write-Bad "$($Step.Id) failed: $reason"
    return [pscustomobject]@{ Ok = $false; Seconds = $totalSec; Reason = $reason; Tail = @($r.Tail) }
  }
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
function Test-VersionAtLeast {
  param([string]$Have, [string]$Need)
  try { return ([version]($Have -replace '[^0-9.].*$', '') -ge [version]$Need) } catch { return $true }
}

function Find-Python {
  $candidates = @(@('py', '-3.13'), @('py', '-3.12'), @('py', '-3.11'), @('python'), @('python3'))
  foreach ($c in $candidates) {
    $exe = [string]$c[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $extra = @($c | Select-Object -Skip 1)
    $v = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $v) { continue }
    $m = [regex]::Match(([string]($v | Select-Object -First 1)).Trim(), '^(\d+)\.(\d+)$')
    if (-not $m.Success) { continue }
    $maj = [int]$m.Groups[1].Value
    $min = [int]$m.Groups[2].Value
    if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) { return [pscustomobject]@{ Exe = $exe; ExtraArgs = $extra; Version = "$maj.$min" } }
  }
  return $null
}

function Test-VenvPackages {
  param($Ctx)
  if (-not (Test-Path -LiteralPath $Ctx.VenvPython)) { return $false }
  & $Ctx.VenvPython -c 'import azure.identity, azure.ai.projects, azure.monitor.query, httpx, msal, jwt, requests, openai, starlette, uvicorn' 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}

function Install-MissingPrereqs {
  param($Ctx)
  if (-not $Ctx.InstallPrereqs) { return }
  if ($Ctx.CheckOnly) { Write-Dim '-InstallPrereqs is ignored in -CheckOnly (nothing is installed).'; return }
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-Warn 'winget was not found; install the missing tools by hand.'; return }
  $want = @()
  if (-not (Get-Command az -ErrorAction SilentlyContinue)) { $want += 'Microsoft.AzureCLI' }
  if (-not (Get-Command azd -ErrorAction SilentlyContinue)) { $want += 'Microsoft.Azd' }
  if (-not (Find-Python)) { $want += 'Python.Python.3.11' }
  foreach ($id in $want) {
    Write-Head "Installing $id with winget"
    & winget install -e --id $id --accept-source-agreements --accept-package-agreements 2>&1 | ForEach-Object { Out-Line ([string]$_) }
  }
  if ($want.Count -gt 0) {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
  }
}

function Test-Prereqs {
  param($Ctx, [bool]$NeedAzd)
  $blockers = New-Object System.Collections.Generic.List[string]
  Write-Head 'Prerequisites'

  if ($IsWindows) { Write-Good "Windows, PowerShell $($PSVersionTable.PSVersion)" }
  else { Write-Bad 'Windows is required: the stage scripts use .venv\Scripts\python.exe and Windows paths'; $blockers.Add('Windows is required') }

  $azVer = ''
  $bicepOk = $false
  if (Get-Command az -ErrorAction SilentlyContinue) {
    try { $azVer = [string]((& az version -o json 2>$null | Out-String | ConvertFrom-Json).'azure-cli') } catch { $azVer = '' }
  }
  if (-not $azVer) { Write-Bad 'Azure CLI not found. Install: winget install -e --id Microsoft.AzureCLI (or rerun with -InstallPrereqs)'; $blockers.Add('Azure CLI is missing') }
  elseif (-not (Test-VersionAtLeast $azVer '2.61.0')) { Write-Bad "Azure CLI $azVer is too old; 2.61 or newer is required (az upgrade)"; $blockers.Add('Azure CLI is too old') }
  else { Write-Good "Azure CLI $azVer" }

  if ($azVer) {
    $bicep = (& az bicep version 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0 -and $bicep -match '(\d+\.\d+\.\d+)') { Write-Good "Bicep $($Matches[1])"; $bicepOk = $true }
    else { Write-Warn 'Bicep CLI is not installed yet; az installs it on first use (or run: az bicep install)' }
  }

  $py = Find-Python
  if (-not $py) { Write-Bad 'Python 3.11 or newer not found. Install: winget install -e --id Python.Python.3.11 (or rerun with -InstallPrereqs)'; $blockers.Add('Python 3.11+ is missing') }
  else {
    Write-Good "Python $($py.Version)"
    if (Test-VenvPackages -Ctx $Ctx) { Write-Good '.venv exists with the pinned packages' }
    elseif (Test-Path -LiteralPath $Ctx.VenvPython) { Write-Warn '.venv exists but packages are missing; requirements.txt will be installed into it' }
    else { Write-Warn '.venv does not exist; it will be created and requirements.txt installed' }
  }

  if (Get-Command azd -ErrorAction SilentlyContinue) { Write-Good 'azd found (Foundry connections)' }
  elseif ($NeedAzd) { Write-Bad 'azd not found but the connections step needs it. Install: winget install -e --id Microsoft.Azd (or rerun with -InstallPrereqs)'; $blockers.Add('azd is missing') }
  else { Write-Warn 'azd not found (only the connections step needs it)' }

  return [pscustomobject]@{ Blockers = @($blockers); Python = $py; BicepInstalled = $bicepOk }
}

function Initialize-Venv {
  param($Ctx, $Py)
  $venvDir = Join-Path $Ctx.RepoRoot '.venv'
  if (-not (Test-Path -LiteralPath $Ctx.VenvPython)) {
    Write-Head 'Creating .venv'
    & $Py.Exe @($Py.ExtraArgs) -m venv $venvDir 2>&1 | ForEach-Object { Out-Line ([string]$_) }
    if ($LASTEXITCODE -ne 0) { throw 'python -m venv failed' }
  }
  if (-not (Test-VenvPackages -Ctx $Ctx)) {
    Write-Head 'Installing Python packages from requirements.txt'
    & $Ctx.VenvPython -m pip install --disable-pip-version-check --progress-bar off -r (Join-Path $Ctx.RepoRoot 'requirements.txt') 2>&1 | ForEach-Object { Out-Line ([string]$_) }
    if ($LASTEXITCODE -ne 0) { throw 'pip install -r requirements.txt failed' }
    if (-not (Test-VenvPackages -Ctx $Ctx)) { throw 'The pinned packages are installed but could not be imported' }
  }
  Write-Good '.venv ready'
}

# ---------------------------------------------------------------------------
# Azure context, configuration, guards
# ---------------------------------------------------------------------------
function Get-AzAccountInfo {
  param([string]$Subscription)
  $azArgs = @('account', 'show', '-o', 'json', '--only-show-errors')
  if ($Subscription) { $azArgs += @('--subscription', $Subscription) }
  $out = & az @azArgs 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
  try { return ($out | Out-String | ConvertFrom-Json) } catch { return $null }
}

function Initialize-AzContext {
  param($Ctx)
  $p = $Ctx.Opt
  Write-Head 'Azure sign-in'
  $acct = Get-AzAccountInfo -Subscription $p.SubscriptionId
  if (-not $acct) {
    if ($p.SubscriptionId) { Write-Bad 'That subscription is not visible to the current az login. Run: az login --tenant <tenant-id>, then az account list' }
    else { Write-Bad 'Not signed in to the Azure CLI. Run: az login --tenant <tenant-id>' }
    return $null
  }
  if ($acct.user.type -ne 'user') {
    Write-Bad 'Sign in as a user (az login). A service principal or managed identity cannot create the Entra users, groups and consents.'
    return $null
  }
  if ($p.TenantId -and ([string]$acct.tenantId -ne [string]$p.TenantId)) {
    Write-Bad "The subscription is in a different tenant than -TenantId. Run: az login --tenant $($p.TenantId)"
    return $null
  }
  Write-Good "Signed in as $($acct.user.name)"
  Write-Good ("Subscription: {0} ({1})" -f $acct.name, (Hide-Guid ([string]$acct.id)))
  Write-Good ("Tenant: {0}" -f (Hide-Guid ([string]$acct.tenantId)))
  if ($p.SubscriptionId -and -not $acct.isDefault) {
    if ($Ctx.CheckOnly) {
      Write-Dim 'CheckOnly does not change the az default subscription; a real run switches to it.'
      $default = Get-AzAccountInfo
      if (-not $default -or ([string]$default.tenantId -ne [string]$acct.tenantId)) { $Ctx.GraphOk = $false }
    } else {
      & az account set --subscription $acct.id 2>&1 | Out-Null
      if ($LASTEXITCODE -ne 0) { throw 'az account set failed' }
    }
  }
  return $acct
}

function Get-InitialDomain {
  try {
    $r = Invoke-Graph -Path '/organization' -Query @{ '$select' = 'verifiedDomains' }
    $d = @($r.value[0].verifiedDomains | Where-Object { $_.isInitial })
    if ($d.Count -gt 0) { return [string]$d[0].name }
  } catch { }
  return $null
}

function New-ConfigObject {
  param($Ctx, $Acct, [string]$Domain, [string]$OperatorOid)
  $p = $Ctx.Opt
  $loc = ([string]$p.Location).ToLowerInvariant()
  $searchLoc = $loc
  if ($p.SearchLocation) { $searchLoc = ([string]$p.SearchLocation).ToLowerInvariant() }
  elseif ($loc -eq 'eastus2') { $searchLoc = 'eastus' }
  $rc = Get-RegionCode $loc
  $u4 = if ($p.UniqueSuffix) { [string]$p.UniqueSuffix } else { New-UniqueSuffix }
  $rg = if ($p.ResourceGroupName) { [string]$p.ResourceGroupName } else { "rg-$($p.Workload)-$($p.EnvName)-$rc-$($p.Instance)" }
  $upn = [string]$Acct.user.name
  $owner = (($upn -split '@')[0] -replace '[^a-zA-Z0-9-]', '-').ToLowerInvariant()
  $cfg = [ordered]@{
    tenantId        = [string]$Acct.tenantId
    tenantDomain    = $Domain
    subscriptionId  = [string]$Acct.id
    location        = $loc
    searchLocation  = $searchLoc
    workload        = [string]$p.Workload
    env             = [string]$p.EnvName
    regionCode      = $rc
    instance        = [string]$p.Instance
    u4              = $u4
    rgName          = $rg
    operatorUpn     = $upn
    operatorOid     = $OperatorOid
    tags            = [ordered]@{ workload = [string]$p.Workload; env = [string]$p.EnvName; owner = $owner; purpose = 'agent-wall-demo'; data = 'synthetic'; 'delete-after' = (Get-Date).AddDays(45).ToString('yyyy-MM-dd') }
    modelName       = [string]$p.ModelName
    modelVersion    = [string]$p.ModelVersion
    modelSku        = [string]$p.ModelSku
    modelCapacity   = [int]$p.ModelCapacity
    modelDeployment = (([string]$p.ModelName) -replace '\.', '')
  }
  if ($p.PublisherEmail) { $cfg.publisherEmail = [string]$p.PublisherEmail }
  elseif ($upn -notmatch '#') { $cfg.publisherEmail = $upn }
  if ($p.AlertEmail) { $cfg.alertEmail = [string]$p.AlertEmail }
  if ($p.EntraWorkspaceId) { $cfg.entraWorkspaceId = [string]$p.EntraWorkspaceId }
  return [pscustomobject]$cfg
}

function Get-ConfigConflicts {
  param($Cfg, $Opt, $Bound)
  $map = @(
    @{ P = 'Location'; C = 'location' }, @{ P = 'SearchLocation'; C = 'searchLocation' }, @{ P = 'Workload'; C = 'workload' }
    @{ P = 'EnvName'; C = 'env' }, @{ P = 'Instance'; C = 'instance' }, @{ P = 'UniqueSuffix'; C = 'u4' }
    @{ P = 'ResourceGroupName'; C = 'rgName' }, @{ P = 'TenantDomain'; C = 'tenantDomain' }
    @{ P = 'ModelName'; C = 'modelName' }, @{ P = 'ModelVersion'; C = 'modelVersion' }, @{ P = 'ModelSku'; C = 'modelSku' }
    @{ P = 'ModelCapacity'; C = 'modelCapacity' }
  )
  $out = New-Object System.Collections.Generic.List[string]
  foreach ($m in $map) {
    if (-not $Bound.ContainsKey($m.P)) { continue }
    $want = [string]$Opt[$m.P]
    $have = [string](Get-CfgValue $Cfg $m.C '')
    if ($have -and ($want -ne $have)) {
      $out.Add("-$($m.P) $want differs from the existing infra\generated\config.json ($($m.C) = $have). Remove the option, or rerun with -ResetState to start a new deployment.")
    }
  }
  return @($out)
}

function Test-NameAvailability {
  param($Cfg)
  $n = Get-AbwNames $Cfg
  $sub = [string]$Cfg.subscriptionId
  $taken = New-Object System.Collections.Generic.List[string]
  foreach ($k in @('storage', 'asvcStorage')) {
    $r = & az storage account check-name --name $n[$k] --subscription $sub --query nameAvailable -o tsv --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0 -and ([string]$r).Trim() -eq 'false') { $taken.Add("storage account $($n[$k])") }
  }
  $r = & az acr check-name --name $n.acr --subscription $sub --query nameAvailable -o tsv --only-show-errors 2>$null
  if ($LASTEXITCODE -eq 0 -and ([string]$r).Trim() -eq 'false') { $taken.Add("container registry $($n.acr)") }
  $r = & az apim check-name-availability --name $n.apim --subscription $sub --query nameAvailable -o tsv --only-show-errors 2>$null
  if ($LASTEXITCODE -eq 0 -and ([string]$r).Trim() -eq 'false') { $taken.Add("API Management $($n.apim)") }
  return @($taken)
}

function Get-PresentArtifacts {
  param($Ctx, $Steps)
  $all = @($Steps | ForEach-Object { $_.Artifacts } | Where-Object { $_ } | Sort-Object -Unique)
  return @($all | Where-Object { Test-Path -LiteralPath (Join-Path $Ctx.RepoRoot $_) })
}

function Resolve-Config {
  param($Ctx, $Acct, $Steps, $Bound)
  $problems = New-Object System.Collections.Generic.List[string]
  $notes = New-Object System.Collections.Generic.List[string]
  $existing = Read-Json (Join-Path $Ctx.Gen 'config.json')
  $present = @(Get-PresentArtifacts -Ctx $Ctx -Steps $Steps)
  $needArchive = $false
  $cfg = $null
  $isNew = $false

  if ($existing) {
    $sameScope = ([string]$existing.tenantId -eq [string]$Acct.tenantId) -and ([string]$existing.subscriptionId -eq [string]$Acct.id)
    if (-not $sameScope) {
      if ($Ctx.ResetState) { $needArchive = $true; $notes.Add('-ResetState: the local state belongs to another tenant or subscription and will be archived.') }
      else { $problems.Add('infra\generated\config.json belongs to a different tenant or subscription than the current az login. Sign in to the right one, or rerun with -ResetState to archive the old local state and start fresh.') }
    } else {
      $rgExists = $null
      if ($present.Count -gt 0) {
        $g = & az group exists --name $existing.rgName --subscription $Acct.id -o tsv --only-show-errors 2>$null
        if ($LASTEXITCODE -eq 0) { $rgExists = (([string]$g).Trim() -eq 'true') }
      }
      if ($rgExists -eq $false) {
        if ($Ctx.ResetState) { $needArchive = $true; $notes.Add('-ResetState: the resource group in config.json is gone; the stale local state will be archived.') }
        else { $problems.Add('The resource group in config.json no longer exists but stage outputs from it are still on disk (a teardown without -CleanLocal?). Rerun with -ResetState to archive them, or run scripts\teardown.ps1 -CleanLocal.') }
      } elseif ($Ctx.ResetState) {
        $needArchive = $true
        $notes.Add('-ResetState: the local state will be archived and new names generated. A deployment that is still running keeps costing money; remove it first with scripts\teardown.ps1.')
      }
      if ($problems.Count -eq 0 -and -not $needArchive) {
        $cfg = $existing
        $notes.Add('Using the existing infra\generated\config.json (a resumed deployment keeps its names).')
        foreach ($c in @(Get-ConfigConflicts -Cfg $existing -Opt $Ctx.Opt -Bound $Bound)) { $problems.Add($c) }
      }
    }
  } elseif ($present.Count -gt 0) {
    if ($Ctx.ResetState) { $needArchive = $true; $notes.Add('-ResetState: stage outputs without a config.json will be archived.') }
    else { $problems.Add('Stage outputs from an earlier deployment are in infra\generated but config.json is missing. Restore it, or rerun with -ResetState to archive them and start fresh.') }
  }

  if (-not $cfg -and $problems.Count -eq 0) {
    $isNew = $true
    $oid = ''
    try { $oid = ([string](& az ad signed-in-user show --query id -o tsv --only-show-errors 2>$null)).Trim() } catch { }
    $domain = [string]$Ctx.Opt.TenantDomain
    if (-not $domain -and $Ctx.GraphOk) { $domain = [string](Get-InitialDomain) }
    if (-not $domain) {
      $domain = ([string]$Acct.user.name -split '@')[-1]
      $notes.Add('The tenant initial domain could not be read; the persona users will use the domain of your sign-in name.')
    }
    $cfg = New-ConfigObject -Ctx $Ctx -Acct $Acct -Domain $domain -OperatorOid $oid
    $handled = $false
    for ($t = 0; $t -lt 6 -and -not $handled; $t++) {
      $taken = @(Test-NameAvailability -Cfg $cfg)
      if ($taken.Count -eq 0) { $handled = $true }
      elseif ($Ctx.Opt.UniqueSuffix) { $problems.Add("These names are already taken; choose another -UniqueSuffix: $($taken -join '; ')"); $handled = $true }
      else { $cfg.u4 = New-UniqueSuffix }
    }
    if (-not $handled) { $problems.Add('No free resource names were found after several tries; pass your own -UniqueSuffix.') }
  }
  return [pscustomobject]@{ Cfg = $cfg; IsNew = $isNew; NeedArchive = $needArchive; Problems = @($problems); Notes = @($notes) }
}

function Reset-LocalState {
  param($Ctx)
  $dest = Join-Path $Ctx.RepoRoot ("_archive\state-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
  foreach ($pair in @(@{ Src = $Ctx.Gen; Name = 'generated' }, @{ Src = $Ctx.Secrets; Name = 'secrets' })) {
    $target = Join-Path $dest $pair.Name
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Get-ChildItem -LiteralPath $pair.Src -Force | ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination $target -Force }
  }
  return $dest
}

function Test-ExistingEntraDeployment {
  # Same prefixes Invoke-Verify counts: any app, group or user of an earlier deployment means Phase 1 would take it over.
  $probes = @(
    @{ Path = '/applications'; Filter = "startswith(displayName,'abw-')" }
    @{ Path = '/groups';       Filter = "startswith(displayName,'sg-abw-')" }
    @{ Path = '/users';        Filter = "startswith(userPrincipalName,'abw.')" }
  )
  try {
    foreach ($pr in $probes) {
      $r = Invoke-Graph -Path $pr.Path -Query @{ '$filter' = $pr.Filter; '$select' = 'id'; '$top' = '1' }
      if (@($r.value).Count -gt 0) { return $true }
    }
    return $false
  } catch { return $null }
}

# Phase 1 takes over abw-* apps, groups and users it finds. Prints the outcome and returns the blocking messages (none when it is safe or unknown).
function Test-EntraTakeoverGuard {
  param($Ctx)
  if (-not $Ctx.GraphOk) {
    Write-Warn 'Skipped the check for existing abw-* Entra objects: -CheckOnly cannot read the Entra tenant of a subscription that is not the az default. A real run switches the default first and makes this check before anything is created.'
    return @()
  }
  $exists = Test-ExistingEntraDeployment
  if ($exists -eq $true) {
    if ($Ctx.AdoptExistingEntra) {
      Write-Warn 'abw-* Entra objects already exist in this tenant. -AdoptExistingEntra: Phase 1 will update them, create a new abw-agent-client secret when none is stored locally, and reset passwords of existing abw.* users that have no stored password. Any other deployment that uses them will break.'
      return @()
    }
    $m = 'abw-* Entra objects already exist in this tenant (another deployment, or an earlier run whose local state is gone). Phase 1 would take them over. Use a different tenant, or rerun with -AdoptExistingEntra if that is what you want.'
    Write-Bad $m
    return @($m)
  }
  if ($null -eq $exists) { Write-Warn 'Could not check the tenant for existing abw-* Entra objects (Graph read failed).'; return @() }
  Write-Good 'No abw-* Entra objects exist yet in this tenant'
  return @()
}

function Test-ExistingInitiative {
  param([string]$SubscriptionId)
  $out = & az policy set-definition show --name abw-agent-platform-controls --subscription $SubscriptionId -o json --only-show-errors 2>$null
  return ($LASTEXITCODE -eq 0 -and [bool]$out)
}

function Test-Permissions {
  param($Ctx, $Acct)
  Write-Head 'Permissions (soft checks: a warning is not a failure, but the deployment needs these rights)'
  $oid = ''
  try { $oid = ([string](& az ad signed-in-user show --query id -o tsv --only-show-errors 2>$null)).Trim() } catch { }
  $assignee = if ($oid) { $oid } else { [string]$Acct.user.name }
  $roles = $null
  try {
    $json = & az role assignment list --assignee $assignee --scope "/subscriptions/$($Acct.id)" --include-inherited --include-groups --subscription $Acct.id -o json --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0) {
      $roles = @(($json | Out-String | ConvertFrom-Json) | ForEach-Object { [string]$_.roleDefinitionName } | Where-Object { $_ } | Sort-Object -Unique)
    }
  } catch { }
  if ($null -eq $roles) { Write-Warn 'Could not read your Azure role assignments. You need Owner on the subscription.' }
  elseif ($roles -contains 'Owner') { Write-Good 'Azure: Owner on the subscription' }
  elseif (($roles -contains 'Contributor') -and (($roles -contains 'User Access Administrator') -or ($roles -contains 'Role Based Access Control Administrator'))) { Write-Good 'Azure: Contributor plus a role-assignment role' }
  else {
    $seen = if ($roles.Count) { $roles -join ', ' } else { 'none' }
    Write-Warn "Azure: Owner not found (roles seen: $seen). The platform step assigns roles; activate PIM or ask for Owner."
  }

  if ($Ctx.GraphOk) {
    try {
      $dr = Invoke-Graph -Path '/me/transitiveMemberOf/microsoft.graph.directoryRole' -Query @{ '$select' = 'displayName' }
      $dn = @($dr.value | ForEach-Object { [string]$_.displayName })
      if ($dn -contains 'Global Administrator') { Write-Good 'Entra: Global Administrator' }
      else {
        $seen = if ($dn.Count) { $dn -join ', ' } else { 'none' }
        Write-Warn "Entra: Global Administrator is not active (roles seen: $seen). The Entra steps create apps, groups and users and grant admin consent; activate PIM or ask for the role."
      }
    } catch { Write-Warn ("Could not read your Entra directory roles: {0}" -f (Hide-Guid $_.Exception.Message)) }
  } else { Write-Dim 'Entra role check skipped (CheckOnly with a subscription from another tenant).' }
}

function Test-ModelCapacity {
  param($Cfg)
  Write-Head 'Foundry model quota (soft check)'
  $loc = [string]$Cfg.location
  $sub = [string]$Cfg.subscriptionId
  $name = [string](Get-CfgValue $Cfg 'modelName' 'gpt-5.4-mini')
  $ver = [string](Get-CfgValue $Cfg 'modelVersion' '2026-03-17')
  $sku = [string](Get-CfgValue $Cfg 'modelSku' 'GlobalStandard')
  $want = [int](Get-CfgValue $Cfg 'modelCapacity' 100)
  $usageName = $null
  try {
    $json = & az cognitiveservices model list --location $loc --subscription $sub -o json --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) {
      $models = @($json | Out-String | ConvertFrom-Json)
      foreach ($m in $models) {
        if ($m.model.name -eq $name -and $m.model.version -eq $ver) {
          $hit = @($m.model.skus | Where-Object { $_.name -eq $sku }) | Select-Object -First 1
          if ($hit) { $usageName = [string]$hit.usageName; break }
        }
      }
    }
  } catch { }
  if (-not $usageName) {
    Write-Warn "Could not confirm that $name $ver ($sku) is offered in $loc. Check: az cognitiveservices model list --location $loc"
    return
  }
  Write-Good "$name $ver is offered in $loc ($sku)"
  try {
    $json = & az cognitiveservices usage list --location $loc --subscription $sub -o json --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0 -and $json) {
      $u = @($json | Out-String | ConvertFrom-Json) | Where-Object { $_.name.value -eq $usageName } | Select-Object -First 1
      if ($u) {
        $left = [double]$u.limit - [double]$u.currentValue
        if ($left -ge $want) { Write-Good "Quota left for ${usageName}: $left (needed $want)" }
        else { Write-Warn "Quota left for $usageName is $left but the deployment asks for $want. Lower -ModelCapacity, pick another -Location, or request quota." }
        return
      }
    }
  } catch { }
  Write-Warn "Could not read the quota usage for $usageName; confirm at least $want in $loc."
}

function Test-BicepCompile {
  param($Ctx)
  Write-Head 'Template compile (az bicep build; nothing is deployed)'
  $files = @(Get-ChildItem -LiteralPath (Join-Path $Ctx.RepoRoot 'infra') -Filter '*.bicep' -File | Sort-Object Name)
  $bad = 0
  foreach ($f in $files) {
    $out = & az bicep build --file $f.FullName --stdout 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Good $f.Name }
    else {
      $bad++
      $first = (@($out) | ForEach-Object { [string]$_ } | Where-Object { $_ -match 'Error|error' } | Select-Object -First 2) -join ' '
      Write-Bad "$($f.Name): $first"
    }
  }
  return $bad
}

# ---------------------------------------------------------------------------
# Plan, confirmation, summary
# ---------------------------------------------------------------------------
function Show-Config {
  param($Cfg)
  $names = Get-AbwNames $Cfg
  Write-Head 'Configuration'
  Out-Line ("   Resource group : {0} ({1})" -f $Cfg.rgName, $Cfg.location)
  Out-Line ("   AI Search in   : {0}" -f $Cfg.searchLocation)
  Out-Line ("   Names          : {0}-{1}-{2}-{3}, unique suffix {4}" -f $Cfg.workload, $Cfg.env, $Cfg.regionCode, $Cfg.instance, $Cfg.u4)
  Out-Line ("   Model          : {0} {1}, {2}, {3}K TPM (deployment {4})" -f (Get-CfgValue $Cfg 'modelName' 'gpt-5.4-mini'), (Get-CfgValue $Cfg 'modelVersion' '2026-03-17'), (Get-CfgValue $Cfg 'modelSku' 'GlobalStandard'), (Get-CfgValue $Cfg 'modelCapacity' 100), $names.modelDeploy)
  Out-Line ("   Persona users  : abw.<name>@{0}" -f $Cfg.tenantDomain)
  if (Get-CfgValue $Cfg 'entraWorkspaceId' '') { Out-Line '   Entra sign-in logs: a workspace was supplied (AbwFullChain shows the Entra rows)' }
  else { Out-Line '   Entra sign-in logs: none supplied (AbwFullChain omits the Entra rows)' }
}

function Show-Plan {
  param($Ctx, $Items)
  Write-Head 'Plan'
  Out-Line ("   {0,-3} {1,-15} {2,-8} {3,-9} {4}" -f '#', 'Step', 'Action', 'Estimate', 'What') 'DarkGray'
  $n = 0
  foreach ($it in $Items) {
    $n++
    $est = ''
    if ($it.Action -eq 'run' -and $it.Step.EtaMax -gt 0) { $est = "$($it.Step.EtaMin)-$($it.Step.EtaMax) min" }
    $what = if ($it.Note) { $it.Note } else { $it.Step.Title }
    $color = switch ($it.Action) { 'run' { 'White' } 'done' { 'Green' } default { 'DarkGray' } }
    Out-Line ("   {0,-3} {1,-15} {2,-8} {3,-9} {4}" -f $n, $it.Step.Id, $it.Action, $est, $what) $color
  }
  $run = @($Items | Where-Object { $_.Action -eq 'run' })
  $lo = [int](($run | ForEach-Object { $_.Step.EtaMin } | Measure-Object -Sum).Sum)
  $hi = [int](($run | ForEach-Object { $_.Step.EtaMax } | Measure-Object -Sum).Sum)
  Out-Line ''
  Out-Line ("   {0} step(s) to run, rough estimate {1}-{2} minutes (the API Management step dominates; times are planning figures, not guarantees)." -f $run.Count, $lo, $hi)
}

function Show-Impact {
  param($Cfg)
  Write-Head 'What this will change'
  Out-Line ("   Azure : resource group {0} in {1} with the platform resources (docs\ARCHITECTURE-AND-DESIGN.md lists them); resource provider registrations; the Azure Policy initiative abw-agent-platform-controls (definition at subscription scope, assignment on the resource group)." -f $Cfg.rgName, $Cfg.location)
  Out-Line '   Entra : 7 app registrations (abw-*), 6 security groups (sg-abw-*), 5 users (abw.*); tenant-wide admin consent (the two client apps to the MCP APIs, the MCP APIs to Storage, Cosmos DB and AI Search for on-behalf-of); app-role assignments to the persona users; your own account gets the persona baseline (wes + tara).'
  Out-Line '   Cost  : about $37 per day while everything runs, API Management Standard v2 being about two thirds of it (USD list price estimate in docs\COST.md); the jump box adds about $4.4 per day only while its VM runs.'
  Out-Line '   Undo  : scripts\teardown.ps1 -WhatIf, then scripts\teardown.ps1 -Yes. Run it the day after you present.'
}

function Confirm-Run {
  param($Ctx, [string]$ResourceGroup)
  if ($Ctx.Yes) { return $true }
  if ([Console]::IsInputRedirected) { throw 'This session is not interactive. Pass -Yes to confirm the deployment.' }
  $answer = Read-Host "Type the resource group name ($ResourceGroup) to start the deployment; anything else cancels"
  return ($answer.Trim() -eq $ResourceGroup)
}

function Get-ArmJson {
  param([string]$Url)
  $out = & az rest --method get --url $Url --only-show-errors -o json 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
  try { return ($out | Out-String | ConvertFrom-Json) } catch { return $null }
}

function Invoke-Verify {
  param($Ctx, $State, $Cfg)
  Write-Head 'Verification (read-only)'
  $names = Get-AbwNames $Cfg
  $sub = [string]$Cfg.subscriptionId
  $rg = [string]$Cfg.rgName
  $arm = 'https://management.azure.com'
  $checks = [System.Collections.Generic.List[object]]::new()
  $add = {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $checks.Add([ordered]@{ name = $Name; ok = $Ok; detail = $Detail })
    if ($Ok) { Write-Good "${Name}: $Detail" } else { Write-Warn "${Name}: $Detail" }
  }

  $all = Get-ArmJson "$arm/subscriptions/$sub/resourceGroups/$rg/resources?api-version=2021-04-01"
  if ($all) { & $add 'Resources in the resource group' (@($all.value).Count -gt 0) "$(@($all.value).Count) resources" } else { & $add 'Resources in the resource group' $false 'could not be listed' }

  $ca = Get-ArmJson "$arm/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.App/containerApps?api-version=2024-03-01"
  if ($ca) {
    $st = @($ca.value | ForEach-Object { [string]$_.properties.provisioningState })
    $okCount = @($st | Where-Object { $_ -eq 'Succeeded' }).Count
    & $add 'Container Apps' ($st.Count -gt 0 -and $okCount -eq $st.Count) "$($st.Count) apps, $okCount provisioned"
  } else { & $add 'Container Apps' $false 'could not be listed' }

  $apim = Get-ArmJson "$arm/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.ApiManagement/service/$($names.apim)?api-version=2024-05-01"
  if ($apim) { & $add 'API Management' ([string]$apim.properties.provisioningState -eq 'Succeeded') "$($apim.sku.name), $($apim.properties.provisioningState)" } else { & $add 'API Management' $false 'not found' }

  $dep = Get-ArmJson "$arm/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.CognitiveServices/accounts/$($names.foundry)/deployments/$($names.modelDeploy)?api-version=2024-10-01"
  if ($dep) { & $add 'Foundry model deployment' ([string]$dep.properties.provisioningState -eq 'Succeeded') "$($names.modelDeploy), $($dep.properties.provisioningState)" } else { & $add 'Foundry model deployment' $false 'not found' }

  $agentsFile = Join-Path $Ctx.Gen 'agents.json'
  if (Test-Path -LiteralPath $agentsFile) {
    $ag = Get-Content -Raw -LiteralPath $agentsFile | ConvertFrom-Json
    $an = @($ag.PSObject.Properties.Name)
    & $add 'Foundry agents' ($an.Count -ge 3) "$($an.Count) published ($($an -join ', '))"
  } else { & $add 'Foundry agents' $false 'agents.json is missing' }

  $gov = Read-Json (Join-Path $Ctx.Gen 'governance.json')
  if ($gov -and $gov.PSObject.Properties['assignmentId'] -and $gov.assignmentId) {
    $pa = Get-ArmJson "$arm$($gov.assignmentId)?api-version=2022-06-01"
    & $add 'Policy initiative assignment' ([bool]$pa) $(if ($pa) { 'present' } else { 'not found' })
  } else { & $add 'Policy initiative assignment' $false 'governance.json has no assignmentId' }

  $obs = Read-Json (Join-Path $Ctx.Gen 'observability.json')
  if ($obs) {
    $rules = 0; if ($obs.PSObject.Properties['sentinelRuleCount']) { $rules = [int]$obs.sentinelRuleCount }
    $fn = 0; if ($obs.PSObject.Properties['functionNames']) { $fn = @($obs.functionNames).Count }
    & $add 'Sentinel analytics rules' ($rules -ge 1) "$rules rules"
    & $add 'KQL function pack' ($fn -ge 1) "$fn functions"
    & $add 'Cockpit workbook' ([bool]($obs.PSObject.Properties['workbookName'] -and $obs.workbookName)) $(if ($obs.PSObject.Properties['workbookName'] -and $obs.workbookName) { [string]$obs.workbookName } else { 'not recorded' })
  } else { & $add 'Observability' $false 'observability.json is missing' }

  if ($Ctx.GraphOk) {
    try {
      $apps = @(Get-GraphAll '/applications' @{ '$filter' = "startswith(displayName,'abw-')"; '$select' = 'id' })
      $groups = @(Get-GraphAll '/groups' @{ '$filter' = "startswith(displayName,'sg-abw-')"; '$select' = 'id' })
      $users = @(Get-GraphAll '/users' @{ '$filter' = "startswith(userPrincipalName,'abw.')"; '$select' = 'id' })
      & $add 'Entra app registrations' ($apps.Count -eq 7) "$($apps.Count) (expected 7)"
      & $add 'Entra groups' ($groups.Count -eq 6) "$($groups.Count) (expected 6)"
      & $add 'Entra persona users' ($users.Count -eq 5) "$($users.Count) (expected 5)"
    } catch { & $add 'Entra objects' $false (Hide-Guid $_.Exception.Message) }
  }

  $State.verify = @{ at = (Get-Date).ToUniversalTime().ToString('o'); checks = @($checks) }
  Save-State -Ctx $Ctx -State $State
  return @($checks | Where-Object { -not $_.ok }).Count
}

function Show-NextSteps {
  param($Ctx)
  Write-Head 'What still needs a human'
  Out-Line '   1. Persona sign-in. Path A (real persona sign-ins): per persona about 12 minutes of MFA enrolment, then one Foundry OAuth consent per connection'
  Out-Line '      (research, wall, actions, vendor, private), one at a time, in a private browser window. Path B (admin as persona): no MFA setup;'
  Out-Line '      the persona baseline (wes + tara) is already applied to your account, so the agent beats run as you. See docs\SELF-DEPLOY.md.'
  Out-Line '   2. Optional admin-portal switches (not needed for the demo): Agent 365 gateway, Defender XDR "Security for AI agents", Purview DSPM for AI.'
  Out-Line '   3. Optional proof run: python demo\prove.py (about 30 minutes), then python demo\scoreboard.py --check. Or rerun this script with -RunProofs.'
  Out-Line '   4. Jump box: open the VM in the portal with Bastion and sign in to Azure once with a device code (scripts\jumpbox.ps1 -OpenPortal).'
  Out-Line '      The console on it shows the shipped scrubbed scoreboard until you run the proofs and python demo\scrub_evidence.py yourself.'
  Out-Line '   5. When you are done: scripts\teardown.ps1 -WhatIf, then scripts\teardown.ps1 -Yes.'
}

function Show-RunSummary {
  param($Items, $Results)
  Write-Head 'Summary'
  foreach ($it in $Items) {
    $r = $Results[$it.Step.Id]
    $status = switch ($it.Action) {
      'run'     { if ($r) { if ($r.Ok) { 'done (ran)' } else { 'FAILED' } } else { 'not run' } }
      'done'    { 'done (earlier)' }
      'assumed' { 'assumed done' }
      default   { 'skipped' }
    }
    $time = if ($r) { Format-Duration $r.Seconds } else { '' }
    $color = if ($status -eq 'FAILED') { 'Red' } elseif ($status -like 'done*') { 'Green' } else { 'DarkGray' }
    Out-Line ("   {0,-15} {1,-15} {2}" -f $it.Step.Id, $status, $time) $color
  }
}

function Complete-Blocked {
  param($Ctx, $Blockers)
  Write-Head 'Cannot continue'
  foreach ($b in $Blockers) { Write-Bad $b }
  Out-Line ''
  Out-Line '   Fix the items above and run again; use -CheckOnly to recheck without changing anything.'
  $script:ExitCode = if ($Ctx.CheckOnly) { 3 } else { 1 }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Invoke-Main {
  param([Parameter(Mandatory)][hashtable]$P, $Bound)
  $saved = @{ Azd = $env:AZD_CONFIG_DIR; Utf8 = $env:PYTHONUTF8; IoEnc = $env:PYTHONIOENCODING; Enc = $null }
  try { $saved.Enc = [Console]::OutputEncoding } catch { }
  try { Invoke-MainCore -P $P -Bound $Bound }
  finally {
    [Environment]::SetEnvironmentVariable('AZD_CONFIG_DIR', $saved.Azd, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONUTF8', $saved.Utf8, 'Process')
    [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $saved.IoEnc, 'Process')
    if ($saved.Enc) { try { [Console]::OutputEncoding = $saved.Enc } catch { } }
  }
}

function Invoke-MainCore {
  param([Parameter(Mandatory)][hashtable]$P, $Bound)
  $ctx = New-RunContext -P $P
  try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
  $env:PYTHONUTF8 = '1'
  $env:PYTHONIOENCODING = 'utf-8'

  Write-Head 'Agents Behind the Wall: one-command deployment'
  Out-Line "   Repository: $($ctx.RepoRoot)"
  if ($ctx.CheckOnly) { Out-Line '   Mode: -CheckOnly. Read-only: nothing is created, changed or written.' 'Yellow' }

  $steps = @(Get-StepTable -Ctx $ctx)
  $state = Read-State -Ctx $ctx
  if ($ctx.ResetState) { $ctx.AssumeFresh = $true }
  $firstPlan = @(Get-PlanItems -Ctx $ctx -State $state -Steps $steps)
  $needAzd = (@($firstPlan | Where-Object { $_.Step.Id -eq 'connections' -and $_.Action -eq 'run' }).Count -gt 0)

  Install-MissingPrereqs -Ctx $ctx
  $pre = Test-Prereqs -Ctx $ctx -NeedAzd $needAzd
  $blockers = New-Object System.Collections.Generic.List[string]
  foreach ($b in $pre.Blockers) { $blockers.Add($b) }
  if ($blockers.Count -gt 0) { Complete-Blocked -Ctx $ctx -Blockers $blockers; return }

  $acct = Initialize-AzContext -Ctx $ctx
  if (-not $acct) { $blockers.Add('Azure sign-in is not ready'); Complete-Blocked -Ctx $ctx -Blockers $blockers; return }

  Write-Head 'Configuration and local state'
  $rc = Resolve-Config -Ctx $ctx -Acct $acct -Steps $steps -Bound $Bound
  foreach ($n in $rc.Notes) { Write-Dim $n }
  foreach ($pr in $rc.Problems) { Write-Bad $pr; $blockers.Add($pr) }
  if ($blockers.Count -gt 0) { Complete-Blocked -Ctx $ctx -Blockers $blockers; return }
  $cfg = $rc.Cfg
  foreach ($np in @(Test-AbwNameRules -Cfg $cfg)) { Write-Bad $np; $blockers.Add($np) }
  if ($blockers.Count -gt 0) { Complete-Blocked -Ctx $ctx -Blockers $blockers; return }
  Show-Config -Cfg $cfg
  if ($rc.IsNew) {
    $g = & az group exists --name ([string]$cfg.rgName) --subscription ([string]$cfg.subscriptionId) -o tsv --only-show-errors 2>$null
    if ($LASTEXITCODE -eq 0 -and ([string]$g).Trim() -eq 'true') {
      Write-Warn "Resource group $($cfg.rgName) already exists in this subscription, so this run adds resources to it. If it holds an earlier copy of this solution, run scripts\teardown.ps1 first or pass another -ResourceGroupName."
    }
  }

  $items = @(Get-PlanItems -Ctx $ctx -State $state -Steps $steps)
  foreach ($np in @(Test-PlanNeeds -Ctx $ctx -Items $items)) { Write-Bad $np; $blockers.Add($np) }
  if ($ctx.Force -and $ctx.Only.Count -eq 0 -and -not $ctx.From) { Write-Warn '-Force without -Only or -From runs every selected step again, including ones that are already done.' }
  $willRun = @($items | Where-Object { $_.Action -eq 'run' } | ForEach-Object { $_.Step.Id })
  if ($willRun -contains 'entra1' -and ($ctx.AssumeFresh -or -not (Test-Path -LiteralPath (Join-Path $ctx.Gen 'entra.json')))) {
    foreach ($m in @(Test-EntraTakeoverGuard -Ctx $ctx)) { $blockers.Add($m) }
  }
  if ($willRun -contains 'governance' -and -not (Test-Path -LiteralPath (Join-Path $ctx.Gen 'governance.json'))) {
    if (Test-ExistingInitiative -SubscriptionId ([string]$cfg.subscriptionId)) {
      Write-Warn 'The policy initiative abw-agent-platform-controls already exists in this subscription (another deployment?). The governance step would take it over.'
    }
  }

  Test-Permissions -Ctx $ctx -Acct $acct
  Test-ModelCapacity -Cfg $cfg
  if ($ctx.CheckOnly) {
    if ($pre.BicepInstalled) {
      $bad = Test-BicepCompile -Ctx $ctx
      if ($bad -gt 0) { $blockers.Add("$bad template(s) do not compile") }
    } else {
      Write-Head 'Template compile'
      Write-Warn 'Skipped: Bicep is not installed and -CheckOnly installs nothing. Run az bicep install, then check again.'
    }
  }

  Show-Plan -Ctx $ctx -Items $items
  Show-Impact -Cfg $cfg

  $runCount = @($items | Where-Object { $_.Action -eq 'run' }).Count
  if ($blockers.Count -gt 0) { Complete-Blocked -Ctx $ctx -Blockers $blockers; return }
  if ($ctx.CheckOnly) {
    if ($runCount -eq 0) { [void](Invoke-Verify -Ctx $ctx -State $state -Cfg $cfg) }
    Write-Head 'Result'
    Write-Good 'Ready. Nothing was created, changed or written. Run without -CheckOnly to deploy.'
    $script:ExitCode = 0
    return
  }
  if ($runCount -eq 0) {
    Write-Head 'Result'
    Write-Good 'Nothing to run: every selected step is already done. Use -Force with -Only <step> to run one again.'
    [void](Invoke-Verify -Ctx $ctx -State $state -Cfg $cfg)
    Show-NextSteps -Ctx $ctx
    return
  }

  Write-Head 'Confirmation'
  if (-not (Confirm-Run -Ctx $ctx -ResourceGroup ([string]$cfg.rgName))) { Out-Line '   Cancelled. Nothing was deployed.' 'Yellow'; $script:ExitCode = 1; return }

  if ($rc.NeedArchive) {
    $dest = Reset-LocalState -Ctx $ctx
    $ctx.AssumeFresh = $false
    $state = Read-State -Ctx $ctx
    Write-Good "Archived the previous local state to $dest"
    $items = @(Get-PlanItems -Ctx $ctx -State $state -Steps $steps)
  }
  if ($rc.IsNew) {
    Save-Json (Join-Path $ctx.Gen 'config.json') $cfg
    Write-Good 'Wrote infra\generated\config.json'
  }

  $logDir = Join-Path $ctx.Gen 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $logPath = Join-Path $logDir ("deploy-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
  $fs = [System.IO.File]::Open($logPath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
  $script:LogWriter = New-Object System.IO.StreamWriter($fs, (New-Object System.Text.UTF8Encoding($false)))
  $script:LogWriter.AutoFlush = $true
  Out-Line ("   Log file: {0}" -f $logPath)

  $runStarted = Get-Date
  try {
    Initialize-Venv -Ctx $ctx -Py $pre.Python
    $opts = @()
    foreach ($k in @('From', 'Until')) { if ($P[$k]) { $opts += "-$k $($P[$k])" } }
    if ($ctx.Only.Count) { $opts += "-Only $($ctx.Only -join ',')" }
    if ($ctx.Skip.Count) { $opts += "-Skip $($ctx.Skip -join ',')" }
    foreach ($k in @('Force', 'ResetState', 'AdoptExistingEntra', 'SkipJumpBox', 'SkipConsole', 'SkipFrontDoor', 'SkipBudget', 'SkipGuardrail', 'WithExtras', 'RunProofs')) { if ($P[$k]) { $opts += "-$k" } }
    Save-InferredSteps -Ctx $ctx -State $state -Steps $steps
    $state.runs = @(@($state.runs) | Select-Object -Last 49) + @([ordered]@{ startedAt = $runStarted.ToUniversalTime().ToString('o'); options = ($opts -join ' ') })
    Save-State -Ctx $ctx -State $state

    $toRun = @($items | Where-Object { $_.Action -eq 'run' })
    $results = @{}
    $softFailed = New-Object System.Collections.Generic.List[string]
    $fatalFailed = $null
    $number = 0
    foreach ($it in $toRun) {
      $number++
      $step = $it.Step
      $missingNeeds = @(@($step.Needs) | Where-Object { -not (Test-Path -LiteralPath (Join-Path $ctx.RepoRoot $_)) })
      if ($missingNeeds.Count -gt 0) {
        $why = "needs $($missingNeeds -join ', ')"
        Out-Line ''
        if ($step.Fatal) { Write-Bad "$($step.Id): $why"; $results[$step.Id] = [pscustomobject]@{ Ok = $false; Seconds = 0.0 }; $fatalFailed = $step; break }
        Write-Warn "$($step.Id) skipped: $why"
        $it.Action = 'skip'; $it.Note = $why
        $softFailed.Add($step.Id)
        continue
      }
      $res = Invoke-Step -Ctx $ctx -State $state -Step $step -Number $number -Total $toRun.Count
      $results[$step.Id] = $res
      if (-not $res.Ok) {
        if ($step.Fatal) { $fatalFailed = $step; Out-Line ''; Out-Line "   Last lines of $($step.Id):" 'Red'; foreach ($l in @($res.Tail | Select-Object -Last 25)) { Out-Line "   | $l" 'DarkGray' }; break }
        $softFailed.Add($step.Id)
        Write-Warn "$($step.Id) is optional for the demo; continuing."
      }
    }

    Show-RunSummary -Items $items -Results $results
    $total = (Get-Date) - $runStarted
    Out-Line ''
    Out-Line ("   Elapsed: {0}. Log: {1}" -f (Format-Duration $total.TotalSeconds), $logPath)

    if ($fatalFailed) {
      Write-Head 'Stopped'
      Write-Bad "Step '$($fatalFailed.Id)' failed. Read the lines above or the log, fix the cause, then run the same command again: finished steps are skipped and this one is retried."
      Out-Line "   To retry just this step: .\scripts\Deploy-AgentWall.ps1 -Only $($fatalFailed.Id) -Force   (then run without -Only to continue)"
      $script:ExitCode = 1
      return
    }

    $failedChecks = Invoke-Verify -Ctx $ctx -State $state -Cfg $cfg
    if ($failedChecks -gt 0) { Write-Warn "$failedChecks verification check(s) need a look (some resources may still be provisioning)." }
    Show-NextSteps -Ctx $ctx
    if ($softFailed.Count -gt 0) {
      Write-Head 'Finished with warnings'
      Write-Warn "Optional step(s) did not complete: $($softFailed -join ', '). Rerun the same command to retry them."
      $script:ExitCode = 2
    } else {
      Write-Head 'Finished'
      Write-Good 'Deployment complete.'
      $script:ExitCode = 0
    }
  } finally {
    if ($script:LogWriter) { $script:LogWriter.Dispose(); $script:LogWriter = $null }
  }
}

if ($MyInvocation.InvocationName -ne '.') {
  $opts = Get-DefaultOptions
  foreach ($k in @($opts.Keys)) {
    $v = Get-Variable -Name $k -ValueOnly -ErrorAction SilentlyContinue
    if ($null -ne $v) { $opts[$k] = $(if ($v -is [System.Management.Automation.SwitchParameter]) { [bool]$v } else { $v }) }
  }
  try { Invoke-Main -P $opts -Bound $PSBoundParameters }
  catch {
    Out-Line ''
    Out-Line ("ERROR: {0}" -f (Hide-Guid $_.Exception.Message)) 'Red'
    if ($script:LogWriter) { $script:LogWriter.Dispose(); $script:LogWriter = $null }
    $script:ExitCode = 1
  }
  exit $script:ExitCode
}
