#requires -Version 7
<#
.SYNOPSIS
  Offline self-test for scripts\Deploy-AgentWall.ps1 and the preflight and secret handling of scripts\deploy.ps1. No Azure, Entra or network calls.

.DESCRIPTION
  Dot-sources the orchestrator (its main block does not run when dot-sourced) and checks it with plain assertions:
    - step table: scripts exist, -Stage/-Phase/-Target values are accepted by the target scripts, inputs are produced by earlier steps
    - plan resolution: -From, -Until (a reversed or excluding range is refused), -Only, -Skip, -Force, option-driven skips,
      "done" detection from artifacts, probes and state, and when existing outputs count as evidence (only before the first run is recorded)
    - step runner: success, missing output, failure, transient retry, retry limit, output tail, missing executable, failing preparation
    - names, region codes, configuration object, conflict detection, state file (atomic save, unreadable file kept as .bad),
      -CheckOnly writing nothing, local-state archive
    - sign-in, permission, model-quota, existing-tenant (apps, groups and users), verification and azd-extension logic, against mocked az, azd and Graph
    - scripts\deploy.ps1 run from a temp copy of the scripts against a fake az: preflight stops on a failed az call, and the vendor key
      reaches az only through a short-lived file under .secrets that is removed again, while infra\generated keeps a masked copy

  Everything it creates is in temp folders; dot-sourcing the scripts only makes sure the empty, git-ignored infra\generated and .secrets
  folders exist. This proves the logic of the orchestrator. It does not deploy anything; run Deploy-AgentWall.ps1 -CheckOnly for a
  read-only check of your own tenant and subscription.

  Exit code 0 = every check passed, 1 = at least one failed.

.EXAMPLE
  .\scripts\Test-DeployOrchestrator.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Deploy-AgentWall.ps1"

$script:Pass = 0
$script:Fail = 0
$script:TempRoots = New-Object System.Collections.Generic.List[string]

function Assert-That {
  param($Condition, [string]$Name)
  if ($Condition) { $script:Pass++; Write-Host "  ok    $Name" -ForegroundColor DarkGreen }
  else { $script:Fail++; Write-Host "  FAIL  $Name" -ForegroundColor Red }
}

function Assert-Equal {
  param($Actual, $Expected, [string]$Name)
  $a = (@($Actual) | ForEach-Object { "$_" }) -join '|'
  $e = (@($Expected) | ForEach-Object { "$_" }) -join '|'
  if ($a -ceq $e) { $script:Pass++; Write-Host "  ok    $Name" -ForegroundColor DarkGreen }
  else { $script:Fail++; Write-Host "  FAIL  $Name" -ForegroundColor Red; Write-Host "        expected: $e"; Write-Host "        actual:   $a" }
}

function Write-Section { param([string]$Text) Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }

function New-TestContext {
  param([hashtable]$Options = @{})
  $root = Join-Path ([System.IO.Path]::GetTempPath()) ('abw-orch-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  New-Item -ItemType Directory -Force -Path (Join-Path $root 'infra\generated'), (Join-Path $root '.secrets') | Out-Null
  $script:TempRoots.Add($root)
  $p = Get-DefaultOptions
  foreach ($k in $Options.Keys) { $p[$k] = $Options[$k] }
  $c = New-RunContext -P $p
  $c.RepoRoot = $root
  $c.Gen = Join-Path $root 'infra\generated'
  $c.Secrets = Join-Path $root '.secrets'
  $c.VenvPython = Join-Path $root '.venv\Scripts\python.exe'
  return $c
}

function Set-GenFile {
  param($Ctx, [string]$Name, [string]$Content = '{}')
  [System.IO.File]::WriteAllText((Join-Path $Ctx.Gen $Name), $Content)
}

function Get-ActionMap {
  param($Items)
  $m = @{}
  foreach ($it in $Items) { $m[$it.Step.Id] = $it.Action }
  return $m
}

function Get-PlanMap {
  param($Ctx)
  $steps = @(Get-StepTable -Ctx $Ctx)
  $state = Read-State -Ctx $Ctx
  return (Get-ActionMap (Get-PlanItems -Ctx $Ctx -State $state -Steps $steps))
}

function Get-PlanError {
  param($Ctx)
  try { [void](Get-PlanMap -Ctx $Ctx); return $null } catch { return $_.Exception.Message }
}

# Runs a script block and keeps what it returns apart from what it prints with Write-Host.
function Invoke-Captured {
  param([scriptblock]$Script)
  $all = @(& $Script 6>&1)
  $printed = @($all | Where-Object { $_ -is [System.Management.Automation.InformationRecord] })
  return [pscustomobject]@{
    Values = @($all | Where-Object { $_ -isnot [System.Management.Automation.InformationRecord] })
    Text   = (@($printed | ForEach-Object { [string]$_.MessageData }) -join "`n")
  }
}

function Get-ScriptParameterInfo {
  param([string]$Path)
  $tokens = $null; $errs = $null
  $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errs)
  $map = @{}
  if ($ast.ParamBlock) {
    foreach ($p in $ast.ParamBlock.Parameters) {
      $set = $null
      foreach ($a in $p.Attributes) {
        if ($a -is [System.Management.Automation.Language.AttributeAst] -and $a.TypeName.Name -eq 'ValidateSet') {
          $set = @($a.PositionalArguments | ForEach-Object { [string]$_.Value })
        }
      }
      $map[$p.Name.VariablePath.UserPath.ToLowerInvariant()] = $set
    }
  }
  return $map
}

# ---------------------------------------------------------------------------
Write-Section 'Parameters and help'
$scriptPath = Join-Path $PSScriptRoot 'Deploy-AgentWall.ps1'
$tk = $null; $er = $null
$ownAst = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tk, [ref]$er)
$paramNames = @($ownAst.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
$defaultKeys = @((Get-DefaultOptions).Keys)
Assert-Equal @($paramNames | Where-Object { $defaultKeys -notcontains $_ }) @() 'every script parameter has a default option'
Assert-Equal @($defaultKeys | Where-Object { $paramNames -notcontains $_ }) @() 'every default option is a script parameter'
$help = Get-Help $scriptPath -Full
$undocumented = @($help.parameters.parameter | Where-Object { -not ($_.description | Out-String).Trim() } | ForEach-Object { $_.name })
Assert-Equal $undocumented @() 'every parameter is documented in the comment-based help'
Assert-Equal (@(Select-String -LiteralPath $scriptPath -Pattern '[^\x00-\x7F]').Count) 0 'script is ASCII only'

# ---------------------------------------------------------------------------
Write-Section 'Step table'
$real = New-TestContext
$real.RepoRoot = $script:RepoRoot
$steps = @(Get-StepTable -Ctx $real)
$expectedIds = @('preflight', 'entra1', 'network', 'foundry', 'foundryrbac', 'platform', 'images', 'apps', 'entra2', 'apim', 'apis', 'images-seed', 'seed', 'baseline', 'connections', 'agents', 'governance', 'guardrail', 'frontdoor', 'budget', 'jumpbox', 'console', 'extras-defender', 'extras-identity', 'proofs', 'scoreboard')
Assert-Equal @($steps | ForEach-Object { $_.Id }) $expectedIds 'step ids and order'
Assert-Equal @($steps | ForEach-Object { $_.Path } | Where-Object { -not (Test-Path -LiteralPath (Join-Path $script:RepoRoot $_)) }) @() 'every step script exists in the repo'
Assert-Equal @($steps | ForEach-Object { @($_.Artifacts) + @($_.Needs) } | Where-Object { $_ -and ($_ -notlike 'infra\generated\*.json') -and ($_ -ne '.secrets\agent-client.json') }) @() 'artifacts and inputs live under infra\generated (or are the one known secret)'

$badArgs = New-Object System.Collections.Generic.List[string]
foreach ($s in $steps) {
  if ($s.Kind -ne 'ps' -or @($s.ScriptArgs).Count -eq 0) { continue }
  $info = Get-ScriptParameterInfo -Path (Join-Path $script:RepoRoot $s.Path)
  $sa = @($s.ScriptArgs)
  for ($i = 0; $i -lt $sa.Count; $i++) {
    if ($sa[$i] -notmatch '^-(\w+)$') { continue }
    $pn = $Matches[1].ToLowerInvariant()
    if (-not $info.ContainsKey($pn)) { $badArgs.Add("$($s.Id): $($s.Path) has no parameter -$pn"); continue }
    if (($i + 1) -lt $sa.Count -and $sa[$i + 1] -notlike '-*' -and $info[$pn] -and ($info[$pn] -notcontains $sa[$i + 1])) {
      $badArgs.Add("$($s.Id): -$pn does not accept '$($sa[$i + 1])'")
    }
  }
}
Assert-Equal @($badArgs) @() 'every -Stage/-Phase/-Target/-As value is accepted by the script it is passed to'

$allOn = New-TestContext @{ WithExtras = $true; RunProofs = $true }
New-Item -ItemType Directory -Force -Path (Join-Path $allOn.RepoRoot 'demo\evidence-scrubbed') | Out-Null
[System.IO.File]::WriteAllText((Join-Path $allOn.RepoRoot 'demo\evidence-scrubbed\scoreboard.json'), '{}')
$allSteps = @(Get-StepTable -Ctx $allOn)
$allItems = @(Get-PlanItems -Ctx $allOn -State (Read-State -Ctx $allOn) -Steps $allSteps)
Assert-Equal @($allItems | Where-Object { $_.Action -eq 'run' }).Count $expectedIds.Count 'with every option on, all steps are planned'
Assert-Equal @(Test-PlanNeeds -Ctx $allOn -Items $allItems) @() 'dependency order: every step input is produced by an earlier step'

# ---------------------------------------------------------------------------
Write-Section 'Plan resolution'
$c = New-TestContext
$m = Get-PlanMap -Ctx $c
Assert-Equal $m['preflight'] 'run' 'fresh state: preflight runs'
Assert-Equal $m['apim'] 'run' 'fresh state: apim runs'
Assert-Equal $m['extras-defender'] 'skip' 'extras are off by default'
Assert-Equal $m['proofs'] 'skip' 'proofs are off by default'
Assert-Equal $m['console'] 'skip' 'console is skipped when the scrubbed scoreboard is missing'

Set-GenFile $c 'preflight.json'
Assert-Equal (Get-PlanMap -Ctx $c)['preflight'] 'done' 'artifact present: step is done'
$c.Force = $true
Assert-Equal (Get-PlanMap -Ctx $c)['preflight'] 'run' '-Force runs a finished step again'
$c.Force = $false
$c.AssumeFresh = $true
Assert-Equal (Get-PlanMap -Ctx $c)['preflight'] 'run' 'AssumeFresh ignores existing artifacts'

$c = New-TestContext @{ From = 'foundry' }
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m['preflight'], $m['entra1'], $m['network'], $m['foundry']) @('assumed', 'assumed', 'assumed', 'run') '-From: earlier steps assumed, the named step runs'

$c = New-TestContext @{ Until = 'apim' }
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m['apim'], $m['apis'], $m['governance']) @('run', 'skip', 'skip') '-Until: later steps are skipped'

$c = New-TestContext @{ Only = @('foundry', 'apim') }
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m.Keys | Where-Object { $m[$_] -eq 'run' } | Sort-Object) @('apim', 'foundry') '-Only runs exactly the named steps'

$c = New-TestContext @{ Skip = 'budget,frontdoor' }
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m['budget'], $m['frontdoor'], $m['apim']) @('skip', 'skip', 'run') '-Skip accepts a comma separated list'

$c = New-TestContext @{ Only = 'nope' }
$threw = $false
try { [void](Get-PlanMap -Ctx $c) } catch { $threw = ($_.Exception.Message -like "Unknown step 'nope'*") }
Assert-That $threw 'an unknown step name is rejected with the list of valid steps'

$lastId = (@(Get-StepTable -Ctx (New-TestContext)))[-1].Id
$e = Get-PlanError (New-TestContext @{ From = 'apim'; Until = 'network' })
Assert-That ($e -like '-From apim comes after -Until network*') 'a -From that comes after -Until is refused instead of planning nothing'
$e = Get-PlanError (New-TestContext @{ Only = @('network'); From = 'apim' })
Assert-That ($e -like "-Only network is outside the range selected by -From and -Until (apim to $lastId)*") '-Only before -From is refused'
$e = Get-PlanError (New-TestContext @{ Only = @('apim'); Until = 'network' })
Assert-That ($e -like '-Only apim is outside the range selected by -From and -Until (preflight to network)*') '-Only after -Until is refused'
$m = Get-PlanMap -Ctx (New-TestContext @{ Only = @('apim'); From = 'network'; Until = 'apis' })
Assert-Equal @($m.Keys | Where-Object { $m[$_] -eq 'run' }) @('apim') '-Only inside the -From to -Until range plans just that step'
Assert-Equal (Get-PlanMap -Ctx (New-TestContext @{ Only = @('seed'); From = 'apim' }))['seed'] 'run' '-Only with a step after -From is accepted'
$m = Get-PlanMap -Ctx (New-TestContext @{ From = 'apim'; Until = 'apim' })
Assert-Equal @($m['apps'], $m['apim'], $m['apis']) @('assumed', 'run', 'skip') '-From and -Until naming the same step select just that step'

$c = New-TestContext @{ SkipJumpBox = $true }
$items = @(Get-PlanItems -Ctx $c -State (Read-State -Ctx $c) -Steps @(Get-StepTable -Ctx $c))
$byId = @{}; foreach ($it in $items) { $byId[$it.Step.Id] = $it }
Assert-That ($byId['jumpbox'].Action -eq 'skip' -and $byId['jumpbox'].Note -like '*SkipJumpBox*') '-SkipJumpBox skips the jump box'
Assert-That ($byId['console'].Action -eq 'skip' -and $byId['console'].Note -like '*SkipJumpBox*') '-SkipJumpBox also skips the console'
$c = New-TestContext @{ SkipGuardrail = $true; SkipFrontDoor = $true; SkipBudget = $true }
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m['guardrail'], $m['frontdoor'], $m['budget']) @('skip', 'skip', 'skip') '-SkipGuardrail, -SkipFrontDoor and -SkipBudget skip their steps'

Write-Section 'Done detection (artifacts, probes, inference, state)'
$c = New-TestContext
Assert-Equal (Get-PlanMap -Ctx $c)['entra2'] 'run' 'entra2 without evidence runs'
Set-GenFile $c 'apis.json'
Assert-Equal (Get-PlanMap -Ctx $c)['entra2'] 'done' 'entra2 is inferred done when apis.json exists'
$st = Read-State -Ctx $c
Set-StepState -Ctx $c -State $st -Id 'entra2' -Status 'failed' -Note 'x'
Assert-Equal (Get-PlanMap -Ctx $c)['entra2'] 'run' 'a failed state entry beats inference'
$st = Read-State -Ctx $c
Set-StepState -Ctx $c -State $st -Id 'entra2' -Status 'done'
Assert-Equal (Get-PlanMap -Ctx $c)['entra2'] 'done' 'a done state entry is trusted'
$st = Read-State -Ctx $c
Set-StepState -Ctx $c -State $st -Id 'entra2' -Status 'running'
Assert-Equal (Get-PlanMap -Ctx $c)['entra2'] 'run' 'a step left in running (interrupted) is run again'

# Outputs on disk vouch for a state-only step only while no run is on record; afterwards only recorded results count.
$c = New-TestContext
Set-GenFile $c 'connections.json'
$st = Read-State -Ctx $c
$st.runs = @([ordered]@{ startedAt = '2026-01-01T00:00:00Z'; options = '-Skip seed' })
Save-State -Ctx $c -State $st
Assert-Equal (Get-PlanMap -Ctx $c)['seed'] 'run' 'a seed skipped on an earlier run is not taken for done because later steps left outputs'
Assert-Equal (Get-PlanMap -Ctx $c)['baseline'] 'run' 'with a run on record, outputs on disk no longer make baseline done'
$st = Read-State -Ctx $c
Set-StepState -Ctx $c -State $st -Id 'seed' -Status 'done'
Assert-Equal (Get-PlanMap -Ctx $c)['seed'] 'done' 'a recorded result still makes a state-only step done after the first run'

$c = New-TestContext
Set-GenFile $c 'apis.json'
Set-GenFile $c 'connections.json'
$st = Read-State -Ctx $c
Save-InferredSteps -Ctx $c -State $st -Steps @(Get-StepTable -Ctx $c)
$st2 = Read-State -Ctx $c
Assert-Equal @($st2.steps.Keys | Sort-Object) @('baseline', 'entra2', 'seed') 'before the first run, existing outputs are written down as done (entra2, seed, baseline)'
Assert-Equal @($st2.steps['seed'].status, $st2.steps['seed'].note) @('done', 'inferred from existing outputs') 'an inferred step is marked done with the reason'
Assert-That (-not $st2.steps.ContainsKey('proofs') -and -not $st2.steps.ContainsKey('scoreboard')) 'steps that have no inference rule (proofs, scoreboard) are never inferred'

$c = New-TestContext
Set-GenFile $c 'apis.json'
$st = Read-State -Ctx $c
$st.runs = @([ordered]@{ startedAt = '2026-01-01T00:00:00Z'; options = '' })
Save-InferredSteps -Ctx $c -State $st -Steps @(Get-StepTable -Ctx $c)
Assert-Equal @($st.steps.Keys).Count 0 'nothing is inferred once a run is on record'
$c = New-TestContext
Set-GenFile $c 'apis.json'
$c.AssumeFresh = $true
$st = Read-State -Ctx $c
Save-InferredSteps -Ctx $c -State $st -Steps @(Get-StepTable -Ctx $c)
Assert-Equal @($st.steps.Keys).Count 0 'nothing is inferred when AssumeFresh is set'
$co = New-TestContext @{ CheckOnly = $true }
Set-GenFile $co 'apis.json'
$so = Read-State -Ctx $co
Save-InferredSteps -Ctx $co -State $so -Steps @(Get-StepTable -Ctx $co)
Assert-That ($so.steps.ContainsKey('entra2') -and -not (Test-Path -LiteralPath (Join-Path $co.Gen 'deploy-state.json'))) '-CheckOnly infers in memory and writes no state file'

$c = New-TestContext
Set-GenFile $c 'agents.json' '{"abw-wall-desk":{}}'
Assert-Equal (Get-PlanMap -Ctx $c)['guardrail'] 'run' 'guardrail: agents.json without the shielded agent is not done'
Set-GenFile $c 'agents.json' '{"abw-wall-desk":{},"abw-wall-desk-redteam-shielded":{}}'
Assert-Equal (Get-PlanMap -Ctx $c)['guardrail'] 'done' 'guardrail: shielded agent present is done'

$c = New-TestContext
Set-GenFile $c 'jumpbox.json' '{"vm":"x"}'
$m = Get-PlanMap -Ctx $c
Assert-Equal @($m['jumpbox'], $m['console']) @('run', 'skip') 'jump box without deployedAt is not done; console has no evidence file'
Set-GenFile $c 'jumpbox.json' '{"deployedAt":"2026-01-01T00:00:00Z"}'
Assert-Equal (Get-PlanMap -Ctx $c)['jumpbox'] 'done' 'jump box with deployedAt is done'
New-Item -ItemType Directory -Force -Path (Join-Path $c.RepoRoot 'demo\evidence-scrubbed') | Out-Null
[System.IO.File]::WriteAllText((Join-Path $c.RepoRoot 'demo\evidence-scrubbed\scoreboard.json'), '{}')
Assert-Equal (Get-PlanMap -Ctx $c)['console'] 'run' 'console runs when the evidence file exists and the console is not on the VM'
Set-GenFile $c 'jumpbox.json' '{"deployedAt":"2026-01-01T00:00:00Z","consoleOnVm":{"files":3}}'
Assert-Equal (Get-PlanMap -Ctx $c)['console'] 'done' 'console with consoleOnVm is done'

Write-Section 'Plan needs'
$c = New-TestContext @{ Only = @('foundry') }
$items = @(Get-PlanItems -Ctx $c -State (Read-State -Ctx $c) -Steps @(Get-StepTable -Ctx $c))
$p = @(Test-PlanNeeds -Ctx $c -Items $items)
Assert-That ($p.Count -eq 1 -and $p[0] -like "*network.json*") '-Only foundry on a fresh checkout reports the missing network output'
Set-GenFile $c 'network.json'
Assert-Equal @(Test-PlanNeeds -Ctx $c -Items @(Get-PlanItems -Ctx $c -State (Read-State -Ctx $c) -Steps @(Get-StepTable -Ctx $c))) @() 'the problem disappears once network.json exists'
$c = New-TestContext @{ From = 'apim' }
$items = @(Get-PlanItems -Ctx $c -State (Read-State -Ctx $c) -Steps @(Get-StepTable -Ctx $c))
Assert-That (@(Test-PlanNeeds -Ctx $c -Items $items).Count -ge 1) '-From apim without the earlier outputs on disk is reported'

# ---------------------------------------------------------------------------
Write-Section 'Names, regions, suffix, formatting'
Assert-Equal (Get-RegionCode 'eastus2') 'eus2' 'region code eastus2'
Assert-Equal (Get-RegionCode 'WestUS3') 'wus3' 'region code is case-insensitive'
Assert-Equal (Get-RegionCode 'brazilsouth') 'braz' 'unknown region falls back to four letters'
$sfx = 1..100 | ForEach-Object { New-UniqueSuffix }
Assert-That (@($sfx | Where-Object { $_ -notmatch '^[a-z0-9]{4}$' }).Count -eq 0) 'unique suffix is always 4 lowercase letters or digits'
Assert-That (@($sfx | Select-Object -Unique).Count -ge 50) 'unique suffix varies'
$cfgN = [pscustomobject]@{ workload = 'abw'; env = 'demo'; regionCode = 'eus2'; instance = '001'; u4 = 't3st'; rgName = 'rg-abw-demo-eus2-001' }
Assert-Equal @(Test-AbwNameRules -Cfg $cfgN) @() 'default names pass the Azure naming rules'
$cfgLong = [pscustomobject]@{ workload = 'abcde'; env = 'abcdefgh'; regionCode = 'wus3'; instance = '001'; u4 = 'abcd'; rgName = 'rg-x' }
Assert-That (@(Test-AbwNameRules -Cfg $cfgLong).Count -ge 1) 'overlong names are reported'
$cfgUp = [pscustomobject]@{ workload = 'abw'; env = 'demo'; regionCode = 'eus2'; instance = '001'; u4 = 'ABCD'; rgName = 'rg-abw-demo-eus2-001' }
Assert-That (@(Test-AbwNameRules -Cfg $cfgUp).Count -ge 1) 'upper-case suffix is reported'
Assert-Equal (Hide-Guid 'tenant 12345678-aaaa-bbbb-cccc-1234567890ab ok') 'tenant 12345678-**** ok' 'Hide-Guid keeps the first group only'
Assert-Equal (Format-Duration 45) '45s' 'duration seconds'
Assert-Equal (Format-Duration 125) '2m 05s' 'duration minutes'
Assert-Equal (Format-Duration 3700) '1h 01m' 'duration hours'
Assert-That ((Test-VersionAtLeast '2.61.0' '2.61') -and -not (Test-VersionAtLeast '2.60.9' '2.61') -and (Test-VersionAtLeast '3.11.9' '3.11') -and -not (Test-VersionAtLeast '3.10.2' '3.11') -and (Test-VersionAtLeast '1.29.0 (commit abc)' '1.20')) 'version comparison'

Write-Section 'Configuration object and conflicts'
$acct = [pscustomobject]@{ tenantId = 'aaaaaaaa-0000-0000-0000-000000000000'; id = 'bbbbbbbb-0000-0000-0000-000000000000'; name = 'Test Subscription'; isDefault = $true; user = [pscustomobject]@{ name = 'first.last@contoso.com'; type = 'user' } }
$c = New-TestContext
$cfg = New-ConfigObject -Ctx $c -Acct $acct -Domain 'contoso.onmicrosoft.com' -OperatorOid 'cccccccc-0000-0000-0000-000000000000'
Assert-Equal @($cfg.location, $cfg.searchLocation, $cfg.regionCode, $cfg.rgName) @('eastus2', 'eastus', 'eus2', 'rg-abw-demo-eus2-001') 'defaults: eastus2, search in eastus, eus2, rg-abw-demo-eus2-001'
Assert-Equal $cfg.modelDeployment 'gpt-54-mini' 'model deployment name drops the dot'
Assert-Equal @($cfg.publisherEmail, $cfg.tags.owner) @('first.last@contoso.com', 'first-last') 'publisher e-mail and owner tag come from the sign-in name'
Assert-That ($cfg.u4 -match '^[a-z0-9]{4}$') 'a unique suffix is generated'
$needed = @('tenantId', 'tenantDomain', 'subscriptionId', 'location', 'searchLocation', 'workload', 'env', 'regionCode', 'instance', 'u4', 'rgName', 'operatorUpn', 'operatorOid', 'tags', 'modelName', 'modelVersion', 'modelSku', 'modelCapacity', 'modelDeployment')
Assert-Equal @($needed | Where-Object { -not $cfg.PSObject.Properties[$_] }) @() 'config carries every key the stage scripts read'
Assert-That ($null -eq $cfg.PSObject.Properties['alertEmail'] -and $null -eq $cfg.PSObject.Properties['entraWorkspaceId']) 'optional keys are absent unless supplied'
$c = New-TestContext @{ Location = 'westus3'; UniqueSuffix = 'ab12'; ResourceGroupName = 'my-rg'; AlertEmail = 'ops@contoso.com'; EntraWorkspaceId = '/subscriptions/s/resourceGroups/r/providers/Microsoft.OperationalInsights/workspaces/w'; ModelName = 'gpt-5.4-mini' }
$cfg2 = New-ConfigObject -Ctx $c -Acct $acct -Domain 'contoso.onmicrosoft.com' -OperatorOid ''
Assert-Equal @($cfg2.searchLocation, $cfg2.regionCode, $cfg2.rgName, $cfg2.u4, $cfg2.alertEmail) @('westus3', 'wus3', 'my-rg', 'ab12', 'ops@contoso.com') 'explicit options flow into the config'
Assert-That ([bool]$cfg2.entraWorkspaceId) 'workspace id is stored when supplied'
$guest = [pscustomobject]@{ tenantId = $acct.tenantId; id = $acct.id; name = 'x'; user = [pscustomobject]@{ name = 'x_contoso.com#EXT#@fabrikam.onmicrosoft.com'; type = 'user' } }
$cfg3 = New-ConfigObject -Ctx (New-TestContext) -Acct $guest -Domain 'fabrikam.onmicrosoft.com' -OperatorOid ''
Assert-That ($null -eq $cfg3.PSObject.Properties['publisherEmail']) 'a guest sign-in name is not used as the publisher e-mail'
$existing = [pscustomobject]@{ location = 'eastus2'; u4 = 'abcd'; workload = 'abw' }
$opt = Get-DefaultOptions; $opt.Location = 'westus3'
Assert-Equal @(Get-ConfigConflicts -Cfg $existing -Opt $opt -Bound @{ Location = $true }).Count 1 'a bound option that differs from the existing config is a conflict'
Assert-Equal @(Get-ConfigConflicts -Cfg $existing -Opt $opt -Bound @{}).Count 0 'an option that was not passed is never a conflict'
$opt.Location = 'eastus2'
Assert-Equal @(Get-ConfigConflicts -Cfg $existing -Opt $opt -Bound @{ Location = $true }).Count 0 'the same value is not a conflict'

# ---------------------------------------------------------------------------
Write-Section 'State file'
$c = New-TestContext
$s = Read-State -Ctx $c
Assert-Equal @($s.schema, @($s.steps.Keys).Count) @(1, 0) 'fresh state'
Set-StepState -Ctx $c -State $s -Id 'network' -Status 'done' -Seconds 12.34 -Attempts 2 -Note 'n'
$s2 = Read-State -Ctx $c
Assert-Equal @($s2.steps['network'].status, $s2.steps['network'].attempts, $s2.steps['network'].seconds) @('done', 2, 12.3) 'state round-trips through the file'
$statePath = Join-Path $c.Gen 'deploy-state.json'
[System.IO.File]::WriteAllText($statePath, '{not json')
Assert-Equal @((Read-State -Ctx $c 6>$null).steps.Keys).Count 0 'a corrupt state file is replaced by a fresh state'
$badText = ''
if (Test-Path -LiteralPath "$statePath.bad") { $badText = [System.IO.File]::ReadAllText("$statePath.bad") }
Assert-Equal $badText '{not json' 'the unreadable state file is kept as deploy-state.json.bad'
[System.IO.File]::WriteAllText($statePath, '[1,2]')
$txt = (Read-State -Ctx $c 6>&1 | Out-String)
Assert-That ($txt -like '*is empty or not valid JSON*') 'a state file that is JSON but not an object is reported and replaced too'
$co = New-TestContext @{ CheckOnly = $true }
$so = Read-State -Ctx $co
Set-StepState -Ctx $co -State $so -Id 'network' -Status 'done'
Assert-That (-not (Test-Path -LiteralPath (Join-Path $co.Gen 'deploy-state.json'))) '-CheckOnly never writes the state file'
Assert-Equal $so.steps['network'].status 'done' '-CheckOnly still tracks state in memory'
$co = New-TestContext @{ CheckOnly = $true }
[System.IO.File]::WriteAllText((Join-Path $co.Gen 'deploy-state.json'), '{not json')
[void](Read-State -Ctx $co 6>$null)
Assert-That (-not (Test-Path -LiteralPath (Join-Path $co.Gen 'deploy-state.json.bad'))) '-CheckOnly writes no .bad copy either'

$c = New-TestContext
$s = Read-State -Ctx $c
Set-StepState -Ctx $c -State $s -Id 'a' -Status 'done'
Set-StepState -Ctx $c -State $s -Id 'b' -Status 'failed' -Note 'x'
Assert-Equal @((Read-State -Ctx $c).steps.Keys | Sort-Object) @('a', 'b') 'a second save keeps the first entry and adds the new one'
[System.IO.File]::WriteAllText((Join-Path $c.Gen 'deploy-state.json.tmp'), 'left behind by a crashed write')
Set-StepState -Ctx $c -State $s -Id 'c' -Status 'done'
Assert-Equal @((Read-State -Ctx $c).steps.Keys).Count 3 'a stale .tmp file from a crashed write does not stop the next save'
Assert-That (-not (Test-Path -LiteralPath (Join-Path $c.Gen 'deploy-state.json.tmp'))) 'saving the state leaves no .tmp file behind'

Write-Section 'Local state archive'
$c = New-TestContext
Set-GenFile $c 'config.json'
Set-GenFile $c 'network.json'
[System.IO.File]::WriteAllText((Join-Path $c.Secrets 'x.txt'), 'x')
$dest = Reset-LocalState -Ctx $c
Assert-That ((@(Get-ChildItem -LiteralPath $c.Gen -Force).Count -eq 0) -and (@(Get-ChildItem -LiteralPath $c.Secrets -Force).Count -eq 0)) 'archive empties infra\generated and .secrets'
Assert-That ((Test-Path -LiteralPath (Join-Path $dest 'generated\config.json')) -and (Test-Path -LiteralPath (Join-Path $dest 'secrets\x.txt'))) 'archive keeps the moved files under _archive'

# ---------------------------------------------------------------------------
Write-Section 'Step runner (fake child process)'
$fc = New-TestContext
$helper = Join-Path $fc.RepoRoot 'fake-step.ps1'
[System.IO.File]::WriteAllText($helper, @'
param([string]$Mode, [string]$Marker, [string]$Artifact)
switch ($Mode) {
  'ok'               { Set-Content -LiteralPath $Artifact -Value '{}'; 'working'; exit 0 }
  'ok-noartifact'    { 'working'; exit 0 }
  'fail'             { 'something broke'; exit 1 }
  'exit7'            { exit 7 }
  'transient-once'   {
    if (-not (Test-Path -LiteralPath $Marker)) { Set-Content -LiteralPath $Marker -Value 'x'; 'ServiceUnavailable: try again'; exit 1 }
    Set-Content -LiteralPath $Artifact -Value '{}'; 'recovered'; exit 0 }
  'transient-always' { 'GatewayTimeout from upstream'; exit 1 }
  'custom'           { 'CheckAccessPrincipalCreationConcurrencyError: wait'; exit 1 }
  'noisy'            { 1..100 | ForEach-Object { "line $_" }; exit 1 }
}
'@)
function New-FakeStep {
  param($Ctx, [string]$Mode, [string]$Id, [string]$Pattern = '')
  $art = "infra\generated\$Id.json"
  $s = New-Step -Id $Id -Title "fake $Mode" -Path 'x' -Artifacts $art -RetryDelay 0 -Pattern $Pattern
  $s.Exe = $Ctx.Pwsh
  $s.ExeArgs = @('-NoProfile', '-File', $helper, $Mode, (Join-Path $Ctx.RepoRoot "$Id.marker"), (Join-Path $Ctx.RepoRoot $art))
  return $s
}
$state = Read-State -Ctx $fc
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'ok' 'f-ok') -Number 1 -Total 1 6>$null
Assert-That ($r.Ok -and $state.steps['f-ok'].status -eq 'done' -and $state.steps['f-ok'].attempts -eq 1) 'exit 0 with the expected output is done in one attempt'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'ok-noartifact' 'f-noart') -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $r.Reason -like '*did not leave the expected result*' -and $state.steps['f-noart'].status -eq 'failed') 'exit 0 without the expected output fails'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'fail' 'f-fail') -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $r.Reason -eq 'exit code 1' -and $state.steps['f-fail'].attempts -eq 1) 'a plain failure is not retried'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'exit7' 'f-7') -Number 1 -Total 1 6>$null
Assert-Equal $r.Reason 'exit code 7' 'the exit code is reported'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'transient-once' 'f-once') -Number 1 -Total 1 6>$null
Assert-That ($r.Ok -and $state.steps['f-once'].attempts -eq 2) 'a transient failure is retried and then succeeds'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'transient-always' 'f-always') -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $state.steps['f-always'].attempts -eq 3) 'retries stop after three attempts'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'custom' 'f-custom' 'CheckAccessPrincipalCreationConcurrencyError') -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $state.steps['f-custom'].attempts -eq 3) 'a step-specific transient pattern is honoured'
$r = Invoke-Step -Ctx $fc -State $state -Step (New-FakeStep $fc 'custom' 'f-custom2') -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $state.steps['f-custom2'].attempts -eq 1) 'without the pattern the same output is not retried'
$pr = Invoke-StepProcess -Ctx $fc -Step (New-FakeStep $fc 'noisy' 'f-noisy') 6>$null
Assert-That ($pr.ExitCode -eq 1 -and $pr.Tail.Count -eq 40 -and $pr.Tail[-1] -eq 'line 100') 'only the last 40 output lines are kept'
$bad = New-FakeStep $fc 'ok' 'f-missing'
$bad.Exe = Join-Path $fc.RepoRoot 'no-such-program.exe'
$pr = Invoke-StepProcess -Ctx $fc -Step $bad 6>$null
Assert-That ($pr.ExitCode -ne 0 -and $pr.Tail.Count -ge 1) 'a missing executable is reported as a failure, not a crash'
$prep = New-Step -Id 'f-prep' -Title 'prep' -Path 'x' -Artifacts 'infra\generated\f-prep.json' -Before { throw 'boom' }
$r = Invoke-Step -Ctx $fc -State $state -Step $prep -Number 1 -Total 1 6>$null
Assert-That ((-not $r.Ok) -and $r.Reason -eq 'preparation failed: boom' -and $state.steps['f-prep'].status -eq 'failed') 'a failing preparation hook fails the step'

# ---------------------------------------------------------------------------
Write-Section 'Output of plan, configuration, blockers'
$c = New-TestContext
$items = @(Get-PlanItems -Ctx $c -State (Read-State -Ctx $c) -Steps @(Get-StepTable -Ctx $c))
$txt = (Show-Plan -Ctx $c -Items $items 6>&1 | Out-String)
Assert-That (($txt -like '*step(s) to run*') -and ($txt -like '*apim*') -and ($txt -like '*off by default*')) 'plan lists the steps, the estimate and why optional steps are off'
$txt = (Show-Config -Cfg $cfg 6>&1 | Out-String)
Assert-That (($txt -like '*rg-abw-demo-eus2-001*') -and ($txt -notlike '*aaaaaaaa-0000*') -and ($txt -notlike '*bbbbbbbb-0000*')) 'configuration summary shows the resource group and no tenant or subscription id'
$txt = (Show-Impact -Cfg $cfg 6>&1 | Out-String)
Assert-That (($txt -like '*teardown.ps1*') -and ($txt -notlike '*100 resources*')) 'impact summary names the undo path and makes no unverified resource-count claim'
$script:ExitCode = 0
Complete-Blocked -Ctx (New-TestContext @{ CheckOnly = $true }) -Blockers @('x') 6>$null
$e1 = $script:ExitCode
Complete-Blocked -Ctx (New-TestContext) -Blockers @('x') 6>$null
Assert-Equal @($e1, $script:ExitCode) @(3, 1) 'blocked exit codes: 3 for -CheckOnly, 1 for a real run'
$script:ExitCode = 0
Assert-That (Confirm-Run -Ctx (New-TestContext @{ Yes = $true }) -ResourceGroup 'rg-x') '-Yes skips the typed confirmation'

# ---------------------------------------------------------------------------
Write-Section 'azd extension probe (mock azd)'
$script:AzdMock = @{ Installed = $false; InstallWorks = $true; Raw = $null; Exit = 0 }
function azd {
  $a = @($args | ForEach-Object { [string]$_ })
  $global:LASTEXITCODE = $script:AzdMock.Exit
  if ($a[0] -eq 'extension' -and $a[1] -eq 'list') {
    if ($null -ne $script:AzdMock.Raw) { return $script:AzdMock.Raw }
    if ($script:AzdMock.Installed) { return '[{"id":"azure.ai.connections","version":"1.0.0-beta.9"}]' }
    return '[]'
  }
  if ($a[0] -eq 'extension' -and $a[1] -eq 'install') { if ($script:AzdMock.InstallWorks) { $script:AzdMock.Installed = $true }; return 'installed' }
  return $null
}
Assert-Equal (Test-AzdExtension) $false 'empty extension list: not installed'
$script:AzdMock.Installed = $true
Assert-Equal (Test-AzdExtension) $true 'extension list with the id: installed'
$script:AzdMock.Installed = $false
$script:AzdMock.Raw = '{"type":"consoleMessage","data":{"message":"hello"}}' + "`n" + '{"type":"consoleMessage","data":{"message":"bye"}}'
Assert-Equal (Test-AzdExtension) $false 'console-message output (empty config dir) is read as not installed'
$script:AzdMock.Raw = ''
Assert-Equal (Test-AzdExtension) $false 'empty output: not installed'
$script:AzdMock.Raw = '[{"id":"azure.ai.connections"}]'; $script:AzdMock.Exit = 1
Assert-Equal (Test-AzdExtension) $false 'a non-zero exit code: not installed'
$script:AzdMock.Raw = $null; $script:AzdMock.Exit = 0
$script:AzdMock.Installed = $false; $script:AzdMock.InstallWorks = $true
Initialize-Azd 6>$null
Assert-That $script:AzdMock.Installed 'Initialize-Azd installs a missing extension'
$script:AzdMock.Installed = $false; $script:AzdMock.InstallWorks = $false
$threw = $false
try { Initialize-Azd 6>$null } catch { $threw = $true }
Assert-That $threw 'Initialize-Azd fails when the extension still is not there after the install'
Remove-Item Function:\azd

# ---------------------------------------------------------------------------
Write-Section 'Azure sign-in, config resolution, guards (mock az and Graph)'
$script:AzMock = @{ Handler = $null; GroupExists = 'true'; NameAvailable = 'true'; Sub = $null; Default = $null; SetCalls = 0 }
function az {
  $a = @($args | ForEach-Object { [string]$_ })
  $global:LASTEXITCODE = 0
  $h = $script:AzMock.Handler
  if ($h) { return (& $h $a) }
  return $null
}
function Invoke-Graph {
  [CmdletBinding()]
  param([string]$Method = 'GET', [string]$Path, $Body = $null, [hashtable]$Query = $null, [switch]$Beta, [switch]$AllowNotFound)
  $h = $script:GraphMock.Handler
  if (-not $h) { throw 'no graph handler set' }
  return (& $h $Path $Query)
}
function Get-GraphAll {
  param([string]$Path, [hashtable]$Query = $null)
  $h = $script:GraphMock.All
  if (-not $h) { throw 'no graph handler set' }
  return @(& $h $Path $Query)
}
$script:GraphMock = @{ Handler = $null; All = $null }

$acctJson = { param($tenant, $id, $type, $isDefault) (@{ tenantId = $tenant; id = $id; name = 'Test Subscription'; isDefault = $isDefault; user = @{ name = 'first.last@contoso.com'; type = $type } } | ConvertTo-Json -Depth 5) }
$T1 = 'aaaaaaaa-0000-0000-0000-000000000000'; $T2 = 'dddddddd-0000-0000-0000-000000000000'; $S1 = 'bbbbbbbb-0000-0000-0000-000000000000'

$script:AzMock.Handler = { param($a) $global:LASTEXITCODE = 1; return $null }
Assert-That ($null -eq (Initialize-AzContext -Ctx (New-TestContext) 6>$null)) 'not signed in: no account'
$script:AzMock.Handler = { param($a) & $acctJson $T1 $S1 'servicePrincipal' $true }
Assert-That ($null -eq (Initialize-AzContext -Ctx (New-TestContext) 6>$null)) 'a service principal sign-in is refused'
$script:AzMock.Handler = { param($a) & $acctJson $T1 $S1 'user' $true }
Assert-That ($null -eq (Initialize-AzContext -Ctx (New-TestContext @{ TenantId = $T2 }) 6>$null)) '-TenantId that does not match the subscription tenant is refused'
$r = Initialize-AzContext -Ctx (New-TestContext @{ TenantId = $T1 }) 6>$null
Assert-That ($null -ne $r -and $r.user.name -eq 'first.last@contoso.com') 'a matching user sign-in is accepted'

$setCalls = New-Object System.Collections.Generic.List[string]
$script:AzMock.Handler = {
  param($a)
  $j = $a -join ' '
  if ($j -like 'account set*') { $setCalls.Add($j); return $null }
  if ($j -like 'account show*--subscription*') { return (& $acctJson $T1 $S1 'user' $false) }
  if ($j -like 'account show*') { return (& $acctJson $T2 'eeeeeeee-0000-0000-0000-000000000000' 'user' $true) }
  return $null
}
$cco = New-TestContext @{ SubscriptionId = $S1; CheckOnly = $true }
$r = Initialize-AzContext -Ctx $cco 6>$null
Assert-That ($null -ne $r -and $setCalls.Count -eq 0) '-CheckOnly never switches the az default subscription'
Assert-That (-not $cco.GraphOk) '-CheckOnly with a subscription from another tenant disables the Entra role check'
$crun = New-TestContext @{ SubscriptionId = $S1 }
$r = Initialize-AzContext -Ctx $crun 6>$null
Assert-That ($null -ne $r -and $setCalls.Count -eq 1) 'a real run switches the az default subscription to the chosen one'

$script:AzMock.Handler = {
  param($a)
  $j = $a -join ' '
  if ($j -like 'group exists*') { return $script:AzMock.GroupExists }
  if ($j -like 'ad signed-in-user show*') { return '11111111-2222-3333-4444-555555555555' }
  if ($j -like '*check-name*') { return $script:AzMock.NameAvailable }
  return $null
}
$acct = [pscustomobject]@{ tenantId = $T1; id = $S1; name = 'Test Subscription'; isDefault = $true; user = [pscustomobject]@{ name = 'first.last@contoso.com'; type = 'user' } }

$c = New-TestContext @{ TenantDomain = 'contoso.onmicrosoft.com' }
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That ($rc.IsNew -and $rc.Problems.Count -eq 0 -and -not $rc.NeedArchive -and $rc.Cfg.operatorOid -eq '11111111-2222-3333-4444-555555555555' -and $rc.Cfg.tenantDomain -eq 'contoso.onmicrosoft.com') 'fresh checkout: a new config is built'

$script:AzMock.NameAvailable = 'false'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That (($rc.Problems -join ' ') -like '*No free resource names*') 'every generated suffix taken: reported after several tries'
$c = New-TestContext @{ TenantDomain = 'contoso.onmicrosoft.com'; UniqueSuffix = 'ab12' }
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That (($rc.Problems -join ' ') -like '*already taken*') 'a taken -UniqueSuffix is reported'
$script:AzMock.NameAvailable = 'true'

$existingCfg = [ordered]@{ tenantId = $T1; subscriptionId = $S1; location = 'eastus2'; workload = 'abw'; env = 'demo'; regionCode = 'eus2'; instance = '001'; u4 = 'abcd'; rgName = 'rg-abw-demo-eus2-001' }
$c = New-TestContext
Save-Json (Join-Path $c.Gen 'config.json') $existingCfg
Set-GenFile $c 'network.json'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That ((-not $rc.IsNew) -and $rc.Problems.Count -eq 0 -and $rc.Cfg.u4 -eq 'abcd') 'resume: the existing config and its names are kept'
$c.Opt.Location = 'westus3'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{ Location = $true } 6>$null
Assert-That (($rc.Problems -join ' ') -like '*differs from the existing*') 'resume: a conflicting option is refused'
$other = [pscustomobject]@{ tenantId = $T2; id = $S1; name = 'x'; isDefault = $true; user = $acct.user }
$c = New-TestContext
Save-Json (Join-Path $c.Gen 'config.json') $existingCfg
$rc = Resolve-Config -Ctx $c -Acct $other -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That (($rc.Problems -join ' ') -like '*different tenant or subscription*') 'local state from another tenant is refused'
$c = New-TestContext @{ ResetState = $true }
Save-Json (Join-Path $c.Gen 'config.json') $existingCfg
$rc = Resolve-Config -Ctx $c -Acct $other -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That ($rc.NeedArchive -and $rc.Problems.Count -eq 0) '-ResetState archives local state from another tenant'
$script:AzMock.GroupExists = 'false'
$c = New-TestContext
Save-Json (Join-Path $c.Gen 'config.json') $existingCfg
Set-GenFile $c 'network.json'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That (($rc.Problems -join ' ') -like '*no longer exists*') 'stage outputs whose resource group is gone are refused'
$c = New-TestContext @{ ResetState = $true }
Save-Json (Join-Path $c.Gen 'config.json') $existingCfg
Set-GenFile $c 'network.json'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That ($rc.NeedArchive -and $rc.Problems.Count -eq 0) '-ResetState archives stale outputs whose resource group is gone'
$script:AzMock.GroupExists = 'true'
$c = New-TestContext
Set-GenFile $c 'network.json'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That (($rc.Problems -join ' ') -like '*config.json is missing*') 'stage outputs without a config.json are refused'
$c = New-TestContext @{ ResetState = $true; TenantDomain = 'contoso.onmicrosoft.com' }
Set-GenFile $c 'network.json'
$rc = Resolve-Config -Ctx $c -Acct $acct -Steps @(Get-StepTable -Ctx $c) -Bound @{} 6>$null
Assert-That ($rc.NeedArchive -and $rc.IsNew -and $rc.Problems.Count -eq 0) '-ResetState archives orphan outputs and builds a new config'

$script:GraphMock.Handler = { param($p, $q) [pscustomobject]@{ value = @([pscustomobject]@{ id = 'x' }) } }
Assert-Equal (Test-ExistingEntraDeployment) $true 'existing abw-* app found in the tenant'
$script:GraphMock.Handler = { param($p, $q) [pscustomobject]@{ value = @() } }
Assert-Equal (Test-ExistingEntraDeployment) $false 'no abw-* app in the tenant'
$script:GraphMock.Handler = { param($p, $q) throw 'graph down' }
Assert-That ($null -eq (Test-ExistingEntraDeployment)) 'a Graph failure is reported as unknown, not as absent'

# The takeover check covers apps, groups and users, the same objects the verification counts.
$script:GraphCalls = New-Object System.Collections.Generic.List[string]
$script:GraphOnly = ''
$script:GraphMock.Handler = {
  param($p, $q)
  $script:GraphCalls.Add("$p $($q['$filter'])")
  $hit = ($script:GraphOnly -and $p -eq $script:GraphOnly)
  [pscustomobject]@{ value = $(if ($hit) { @([pscustomobject]@{ id = 'x' }) } else { @() }) }
}
Assert-Equal (Test-ExistingEntraDeployment) $false 'a tenant with no abw-* apps, groups or users is clean'
Assert-Equal @($script:GraphCalls) @("/applications startswith(displayName,'abw-')", "/groups startswith(displayName,'sg-abw-')", "/users startswith(userPrincipalName,'abw.')") 'the takeover check looks for abw- apps, sg-abw- groups and abw. users'
$script:GraphOnly = '/groups'
Assert-Equal (Test-ExistingEntraDeployment) $true 'a leftover sg-abw-* group alone counts as an existing deployment'
$script:GraphOnly = '/users'
Assert-Equal (Test-ExistingEntraDeployment) $true 'a leftover abw.* user alone counts as an existing deployment'

$gc = New-TestContext
$gc.GraphOk = $false
$script:GraphCalls.Clear()
$g = Invoke-Captured { Test-EntraTakeoverGuard -Ctx $gc }
Assert-That ($g.Values.Count -eq 0 -and $script:GraphCalls.Count -eq 0 -and $g.Text -like '*Skipped the check for existing abw-*') 'guard: Entra not readable (CheckOnly, other tenant) is skipped with a warning and reads nothing'
$gc = New-TestContext
$g = Invoke-Captured { Test-EntraTakeoverGuard -Ctx $gc }
Assert-That ($g.Values.Count -eq 1 -and "$($g.Values[0])" -like '*Phase 1 would take them over*' -and $g.Text.Contains('[FAIL]')) 'guard: existing abw-* objects block the run'
$gc = New-TestContext @{ AdoptExistingEntra = $true }
$g = Invoke-Captured { Test-EntraTakeoverGuard -Ctx $gc }
Assert-That ($g.Values.Count -eq 0 -and $g.Text -like '*-AdoptExistingEntra: Phase 1 will update them*') 'guard: -AdoptExistingEntra turns the block into a warning'
$script:GraphOnly = ''
$gc = New-TestContext
$g = Invoke-Captured { Test-EntraTakeoverGuard -Ctx $gc }
Assert-That ($g.Values.Count -eq 0 -and $g.Text -like '*No abw-* Entra objects exist yet*') 'guard: a clean tenant passes'
$script:GraphMock.Handler = { param($p, $q) throw 'graph down' }
$g = Invoke-Captured { Test-EntraTakeoverGuard -Ctx $gc }
Assert-That ($g.Values.Count -eq 0 -and $g.Text -like '*Could not check the tenant for existing abw-*') 'guard: a Graph failure warns and does not block'
$script:AzMock.Handler = { param($a) if (($a -join ' ') -like 'policy set-definition show*') { return '{"name":"abw-agent-platform-controls"}' } ; $global:LASTEXITCODE = 1; return $null }
Assert-That (Test-ExistingInitiative -SubscriptionId $S1) 'existing policy initiative found'
$script:AzMock.Handler = { param($a) $global:LASTEXITCODE = 1; return $null }
Assert-That (-not (Test-ExistingInitiative -SubscriptionId $S1)) 'no policy initiative'

Write-Section 'Permissions and model quota (mock az and Graph)'
$perm = {
  param($roles, $dirRoles)
  $script:AzMock.Handler = {
    param($a)
    $j = $a -join ' '
    if ($j -like 'ad signed-in-user show*') { return '11111111-2222-3333-4444-555555555555' }
    if ($j -like 'role assignment list*') { return ((@($script:PermRoles | ForEach-Object { @{ roleDefinitionName = $_ } })) | ConvertTo-Json -Depth 3) }
    return $null
  }
  $script:PermRoles = $roles
  $script:GraphMock.Handler = { param($p, $q) [pscustomobject]@{ value = @($script:PermDir | ForEach-Object { [pscustomobject]@{ displayName = $_ } }) } }
  $script:PermDir = $dirRoles
  $cc = New-TestContext
  (Test-Permissions -Ctx $cc -Acct $acct 6>&1 | Out-String)
}
$t = & $perm @('Owner') @('Global Administrator')
Assert-That (($t -like '*Azure: Owner on the subscription*') -and ($t -like '*Entra: Global Administrator*')) 'Owner plus Global Administrator: both pass'
$t = & $perm @('Reader') @('Application Administrator')
Assert-That (($t -like '*Owner not found*') -and ($t -like '*Global Administrator is not active*')) 'missing rights are warnings that name the roles seen'
$t = & $perm @('Contributor', 'User Access Administrator') @('Global Administrator')
Assert-That ($t -like '*Contributor plus a role-assignment role*') 'Contributor plus User Access Administrator is accepted'

$cfgQ = [pscustomobject]@{ location = 'eastus2'; subscriptionId = $S1; modelName = 'gpt-5.4-mini'; modelVersion = '2026-03-17'; modelSku = 'GlobalStandard'; modelCapacity = 100 }
$quota = {
  param($limit, $current, [bool]$offered)
  $script:QuotaLimit = $limit; $script:QuotaCurrent = $current; $script:QuotaOffered = $offered
  $script:AzMock.Handler = {
    param($a)
    $j = $a -join ' '
    if ($j -like 'cognitiveservices model list*') {
      if (-not $script:QuotaOffered) { return '[]' }
      return '[{"model":{"name":"gpt-5.4-mini","version":"2026-03-17","skus":[{"name":"GlobalStandard","usageName":"OpenAI.GlobalStandard.gpt-5.4-mini"}]}}]'
    }
    if ($j -like 'cognitiveservices usage list*') { return ('[{"name":{"value":"OpenAI.GlobalStandard.gpt-5.4-mini"},"limit":' + $script:QuotaLimit + ',"currentValue":' + $script:QuotaCurrent + '}]') }
    return $null
  }
  (Test-ModelCapacity -Cfg $cfgQ 6>&1 | Out-String)
}
$t = & $quota 1000 100 $true
Assert-That (($t -like '*[ok]*Quota left for OpenAI.GlobalStandard.gpt-5.4-mini: 900*')) 'enough quota is reported with the remaining amount'
$t = & $quota 150 100 $true
Assert-That ($t -like '*[warn]*Quota left for OpenAI.GlobalStandard.gpt-5.4-mini is 50*') 'not enough quota is a warning'
$t = & $quota 1000 0 $false
Assert-That ($t -like '*Could not confirm that gpt-5.4-mini*') 'a model that is not offered in the region is a warning'

# ---------------------------------------------------------------------------
Write-Section 'Verification (mock ARM and Graph)'
$vc = New-TestContext
$vcfg = New-ConfigObject -Ctx $vc -Acct $acct -Domain 'contoso.onmicrosoft.com' -OperatorOid ''
$script:AzMock.Handler = {
  param($a)
  $j = $a -join ' '
  if ($j -notlike 'rest*') { return $null }
  if ($j -like '*Microsoft.App/containerApps*') { return (@{ value = @(1..6 | ForEach-Object { @{ properties = @{ provisioningState = 'Succeeded' } } }) } | ConvertTo-Json -Depth 6) }
  if ($j -like '*Microsoft.ApiManagement/service/*') { return '{"sku":{"name":"StandardV2"},"properties":{"provisioningState":"Succeeded"}}' }
  if ($j -like '*/deployments/*') { return '{"properties":{"provisioningState":"Succeeded"}}' }
  if ($j -like '*policyAssignments*') { return '{"id":"x"}' }
  if ($j -like '*/resources?*') { return '{"value":[{"name":"a"},{"name":"b"}]}' }
  return $null
}
$script:GraphMock.All = {
  param($p, $q)
  if ($p -eq '/applications') { return @(1..7 | ForEach-Object { [pscustomobject]@{ id = "a$_" } }) }
  if ($p -eq '/groups') { return @(1..6 | ForEach-Object { [pscustomobject]@{ id = "g$_" } }) }
  if ($p -eq '/users') { return @(1..5 | ForEach-Object { [pscustomobject]@{ id = "u$_" } }) }
  return @()
}
Set-GenFile $vc 'agents.json' '{"abw-wall-desk":{},"abw-research-desk":{},"abw-wall-desk-redteam-shielded":{}}'
Set-GenFile $vc 'governance.json' '{"assignmentId":"/subscriptions/s/providers/Microsoft.Authorization/policyAssignments/a"}'
Set-GenFile $vc 'observability.json' '{"sentinelRuleCount":9,"functionNames":["AbwFullChain","AbwDenials"],"workbookName":"abw-cockpit"}'
$vstate = Read-State -Ctx $vc
$failed = Invoke-Verify -Ctx $vc -State $vstate -Cfg $vcfg 6>$null
Assert-Equal $failed 0 'a complete deployment verifies with no failed check'
Assert-That ($vstate.verify.checks.Count -ge 10 -and (Test-Path -LiteralPath (Join-Path $vc.Gen 'deploy-state.json'))) 'verification results are recorded in the state file'
$vc2 = New-TestContext
$vstate2 = Read-State -Ctx $vc2
$script:GraphMock.All = { param($p, $q) return @() }
$failed2 = Invoke-Verify -Ctx $vc2 -State $vstate2 -Cfg $vcfg 6>$null
Assert-That ($failed2 -ge 5) 'a missing agents, governance, observability and Entra footprint fails the matching checks'

# ---------------------------------------------------------------------------
Write-Section 'deploy.ps1 against a fake az (preflight failures, secret parameter file)'
# The real scripts\deploy.ps1 and common.ps1 are copied into a temp repo and run in a child process. A fake az.ps1 is first on PATH,
# AZURE_CONFIG_DIR points at an empty folder, and the first check proves the fake is what gets found, so no real az or tenant is touched.
$script:ChildPwsh = (Get-Process -Id $PID).Path
$script:ShimText = @'
$a = @($args | ForEach-Object { [string]$_ })
$j = $a -join ' '
Add-Content -LiteralPath $env:ABW_FAKE_AZ_LOG -Value $j
$fail = @(($env:ABW_FAKE_AZ_FAIL -split ',') | Where-Object { $_ })
if ($j -like 'account set*') { if ($fail -contains 'account-set') { exit 1 }; exit 0 }
if ($j -like 'group create*') { if ($fail -contains 'group-create') { exit 1 }; exit 0 }
if ($j -like 'provider show*') { 'NotRegistered'; exit 0 }
if ($j -like 'provider register*') { if ($fail -contains 'provider-register') { exit 1 }; exit 0 }
if ($j -like 'deployment group create*' -or $j -like 'deployment group what-if*') {
  foreach ($x in $a) {
    if ($x.StartsWith('@')) {
      Copy-Item -LiteralPath $x.Substring(1) -Destination (Join-Path $env:ABW_FAKE_AZ_DIR 'seen-params.json') -Force
      [System.IO.File]::WriteAllText((Join-Path $env:ABW_FAKE_AZ_DIR 'seen-params-path.txt'), $x.Substring(1))
    }
  }
  if ($j -like '*what-if*') { 'fake what-if output'; exit 0 }
  if ($fail -contains 'deployment') { exit 1 }
  if ($j -like '*--no-wait*') { exit 0 }
  '{"properties":{"provisioningState":"Succeeded","duration":"PT1S","outputs":{}}}'
  exit 0
}
exit 0
'@

function New-DeployRepo {
  param([switch]$WithApps)
  $root = Join-Path ([System.IO.Path]::GetTempPath()) ('abw-orch-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  $script:TempRoots.Add($root)
  $r = [pscustomobject]@{
    Root = $root; Scripts = (Join-Path $root 'scripts'); Shim = (Join-Path $root 'shim'); Gen = (Join-Path $root 'infra\generated')
    Secrets = (Join-Path $root '.secrets'); AzState = (Join-Path $root 'azstate'); AzCfg = (Join-Path $root 'azcfg')
  }
  foreach ($d in @($r.Scripts, $r.Shim, $r.Gen, $r.Secrets, $r.AzState, $r.AzCfg)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
  Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'deploy.ps1'), (Join-Path $PSScriptRoot 'common.ps1') -Destination $r.Scripts
  [System.IO.File]::WriteAllText((Join-Path $r.Shim 'az.ps1'), $script:ShimText)
  Save-Json (Join-Path $r.Gen 'config.json') ([ordered]@{
    tenantId = $T1; subscriptionId = $S1; location = 'eastus2'; workload = 'abw'; env = 'demo'; regionCode = 'eus2'; instance = '001'; u4 = 'abcd'
    rgName = 'rg-abw-demo-eus2-001'; operatorUpn = 'first.last@contoso.com'; operatorOid = ''
    tags = [ordered]@{ workload = 'abw'; owner = 'test' }
  })
  if ($WithApps) {
    Save-Json (Join-Path $r.Gen 'platform.json') ([ordered]@{ x = 1 })
    Save-Json (Join-Path $r.Gen 'entra.json') ([ordered]@{
      apis = [ordered]@{ research = @{ appId = 'a1' }; wall = @{ appId = 'a2' }; actions = @{ appId = 'a3' }; private = @{ appId = 'a4' } }
      clients = [ordered]@{ agent = @{ appId = 'c1' }; test = @{ appId = 'c2' } }
    })
    Save-Json (Join-Path $r.Gen 'images.json') ([ordered]@{ tag = 't1' })
  }
  return $r
}

function Invoke-ShimmedPwsh {
  param($Repo, [string[]]$PwshArgs, [string]$Fail = '')
  $names = 'PATH', 'AZURE_CONFIG_DIR', 'ABW_FAKE_AZ_FAIL', 'ABW_FAKE_AZ_LOG', 'ABW_FAKE_AZ_DIR'
  $saved = @{}
  foreach ($n in $names) { $saved[$n] = [Environment]::GetEnvironmentVariable($n) }
  $prev = $ErrorActionPreference
  try {
    $env:PATH = "$($Repo.Shim);$($saved['PATH'])"
    $env:AZURE_CONFIG_DIR = $Repo.AzCfg
    $env:ABW_FAKE_AZ_FAIL = $Fail
    $env:ABW_FAKE_AZ_LOG = Join-Path $Repo.AzState 'calls.log'
    $env:ABW_FAKE_AZ_DIR = $Repo.AzState
    $ErrorActionPreference = 'Continue'
    $text = (& $script:ChildPwsh -NoProfile -ExecutionPolicy Bypass @PwshArgs 2>&1 | Out-String)
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prev
    foreach ($n in $names) { [Environment]::SetEnvironmentVariable($n, $saved[$n]) }
  }
  return [pscustomobject]@{ ExitCode = $code; Text = $text }
}

function Invoke-DeployChild {
  param($Repo, [string[]]$StageArgs, [string]$Fail = '')
  return (Invoke-ShimmedPwsh -Repo $Repo -PwshArgs (@('-File', (Join-Path $Repo.Scripts 'deploy.ps1')) + $StageArgs) -Fail $Fail)
}

function ConvertTo-FlatText {
  param([string]$Text)
  return (($Text -replace '[\r\n]+\s*(\|\s*)?', ' ') -replace '\s+', ' ')
}

function Get-FakeAzCalls {
  param($Repo)
  return @(Get-Content -LiteralPath (Join-Path $Repo.AzState 'calls.log') -ErrorAction SilentlyContinue)
}

function Get-SeenParams {
  param($Repo)
  $pp = Join-Path $Repo.AzState 'seen-params-path.txt'
  $pj = Join-Path $Repo.AzState 'seen-params.json'
  if (-not (Test-Path -LiteralPath $pp) -or -not (Test-Path -LiteralPath $pj)) { return [pscustomobject]@{ Path = ''; Json = $null } }
  return [pscustomobject]@{ Path = [System.IO.File]::ReadAllText($pp); Json = (Get-Content -Raw -LiteralPath $pj | ConvertFrom-Json) }
}

function Get-LeftoverParamFiles {
  param($Repo)
  return @(Get-ChildItem -LiteralPath $Repo.Secrets -Filter 'params.*' -ErrorAction SilentlyContinue)
}

function Test-SecretParamFileGone {
  param($Repo, $Seen)
  if (-not $Seen.Path -or -not $Seen.Path.StartsWith($Repo.Secrets, [System.StringComparison]::OrdinalIgnoreCase)) { return $false }
  return ((-not (Test-Path -LiteralPath $Seen.Path)) -and (Get-LeftoverParamFiles $Repo).Count -eq 0)
}

$probeRepo = New-DeployRepo
$probe = Invoke-ShimmedPwsh -Repo $probeRepo -PwshArgs @('-Command', '(Get-Command az -ErrorAction Stop).Source')
$shimOk = ($probe.Text.Trim() -ieq (Join-Path $probeRepo.Shim 'az.ps1'))
Assert-That $shimOk 'the child process finds the fake az first on PATH, so no real az is ever called'
if ($shimOk) {
  # preflight must stop at the first failing az call instead of carrying on
  $cases = @(
    @{ Fail = 'account-set';       Expect = 'az account set failed for subscription';             NotCalled = 'group create*' }
    @{ Fail = 'group-create';      Expect = 'az group create failed for rg-abw-demo-eus2-001';    NotCalled = 'provider show*' }
    @{ Fail = 'provider-register'; Expect = 'az provider register failed for Microsoft.Network';  NotCalled = 'provider show -n Microsoft.App*' }
  )
  foreach ($case in $cases) {
    $r = New-DeployRepo
    $o = Invoke-DeployChild $r @('-Stage', 'preflight') $case.Fail
    Assert-That ($o.ExitCode -ne 0 -and (ConvertTo-FlatText $o.Text) -like "*$($case.Expect)*") "preflight fails with a clear message when az fails ($($case.Fail))"
    $later = @(Get-FakeAzCalls $r | Where-Object { $_ -like $case.NotCalled })
    Assert-That ($later.Count -eq 0 -and -not (Test-Path -LiteralPath (Join-Path $r.Gen 'preflight.json'))) "preflight stops at the failing call and writes no result ($($case.Fail))"
  }

  # the vendor key reaches az through a short-lived file under .secrets; infra\generated keeps a masked copy
  $r = New-DeployRepo -WithApps
  $o = Invoke-DeployChild $r @('-Stage', 'apps')
  Assert-Equal $o.ExitCode 0 'apps stage runs to the end against the fake az'
  $key = ''
  if (Test-Path -LiteralPath (Join-Path $r.Secrets 'vendor-api-key.txt')) { $key = (Get-Content -Raw -LiteralPath (Join-Path $r.Secrets 'vendor-api-key.txt')).Trim() }
  $seen = Get-SeenParams $r
  Assert-That ($key.Length -ge 20 -and $seen.Path.StartsWith($r.Secrets, [System.StringComparison]::OrdinalIgnoreCase)) 'az reads the apps parameters from a file under .secrets'
  Assert-That ($seen.Json.parameters.vendorApiKey.value -ceq $key -and $seen.Json.parameters.imageTag.value -ceq 't1') 'that file holds the real vendor key and the other parameters'
  $auditPath = Join-Path $r.Gen 'params.apps.json'
  $auditText = ''
  if (Test-Path -LiteralPath $auditPath) { $auditText = Get-Content -Raw -LiteralPath $auditPath }
  $audit = $auditText | ConvertFrom-Json
  Assert-That ($audit.parameters.vendorApiKey.value -ceq '***' -and $audit.parameters.imageTag.value -ceq 't1') 'the copy kept in infra\generated shows *** for the key and every other parameter as it is'
  Assert-That ($key.Length -ge 20 -and -not $auditText.Contains($key)) 'the key is nowhere in infra\generated\params.apps.json'
  Assert-That (Test-SecretParamFileGone $r $seen) 'the secret parameter file is removed once az returns'

  $r = New-DeployRepo -WithApps
  $o = Invoke-DeployChild $r @('-Stage', 'apps') 'deployment'
  Assert-That ($o.ExitCode -ne 0 -and (ConvertTo-FlatText $o.Text) -like "*stage 'apps' failed*") 'a failed deployment fails the stage'
  Assert-That (Test-SecretParamFileGone $r (Get-SeenParams $r)) 'the secret parameter file is removed when the deployment fails'

  foreach ($sw in '-WhatIf', '-NoWait') {
    $r = New-DeployRepo -WithApps
    $o = Invoke-DeployChild $r @('-Stage', 'apps', $sw)
    $seen = Get-SeenParams $r
    Assert-That ($o.ExitCode -eq 0 -and $seen.Path.StartsWith($r.Secrets, [System.StringComparison]::OrdinalIgnoreCase)) "$sw : az reads the parameters from a file under .secrets"
    Assert-That (Test-SecretParamFileGone $r $seen) "$sw : the secret parameter file is removed"
  }

  # a stage without secrets is unchanged: az reads the file in infra\generated, which stays as the audit copy
  $r = New-DeployRepo
  $o = Invoke-DeployChild $r @('-Stage', 'network')
  $seen = Get-SeenParams $r
  Assert-That ($o.ExitCode -eq 0 -and $seen.Path -ieq (Join-Path $r.Gen 'params.network.json')) 'a stage without secrets gives az infra\generated\params.<stage>.json'
  Assert-That ((Test-Path -LiteralPath (Join-Path $r.Gen 'params.network.json')) -and (Test-Path -LiteralPath (Join-Path $r.Gen 'network.json')) -and (Get-LeftoverParamFiles $r).Count -eq 0) 'that file stays as the audit copy next to the stage result, and .secrets holds no parameter file'
}

# ---------------------------------------------------------------------------
foreach ($root in $script:TempRoots) { try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue } catch { } }
Write-Host ''
if ($script:Fail -eq 0) { Write-Host ("All {0} checks passed." -f $script:Pass) -ForegroundColor Green; exit 0 }
Write-Host ("{0} check(s) FAILED, {1} passed." -f $script:Fail, $script:Pass) -ForegroundColor Red
exit 1
