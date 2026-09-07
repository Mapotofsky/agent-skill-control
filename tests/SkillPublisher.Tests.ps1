$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Import-Module (Join-Path $PSScriptRoot '..\scripts\SkillPublisher.psm1') -Force

$script:Passed = 0
$script:Failed = 0

function Assert-True {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
}

function Assert-Throws {
  param([scriptblock]$Action, [string]$Pattern)
  try { & $Action; throw 'Expected an exception, but none was thrown.' } catch {
    if ($_.Exception.Message -eq 'Expected an exception, but none was thrown.') { throw }
    if ($_.Exception.Message -notmatch $Pattern) { throw "Exception did not match '$Pattern': $($_.Exception.Message)" }
  }
}

function Invoke-Test {
  param([string]$Name, [scriptblock]$Body)
  try { & $Body; $script:Passed++; Write-Host "PASS $Name" } catch { $script:Failed++; Write-Host "FAIL $Name`n  $($_.Exception.Message)" }
}

function Write-TestJson {
  param([string]$Path, $Value)
  $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function New-TestHub {
  param($Catalog, $Deployments, $Paths)
  $root = Join-Path ([IO.Path]::GetTempPath()) ('skill-publisher-test-' + [Guid]::NewGuid().ToString('N'))
  $testHome = Join-Path $root 'home'
  New-Item -ItemType Directory -Path (Join-Path $root 'skills\self\alpha'), (Join-Path $root 'skills\third-party\beta'), (Join-Path $root 'profiles'), $testHome -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $root 'skills\self\alpha\SKILL.md') -Value '# alpha' -Encoding UTF8
  Set-Content -LiteralPath (Join-Path $root 'skills\third-party\beta\SKILL.md') -Value '# beta' -Encoding UTF8
  if ($null -eq $Catalog) {
    $Catalog = @{ self = @{ alpha = @{ status = 'active' } }; thirdParty = @{ beta = @{ status = 'active'; repository = 'https://example.invalid/repo'; subpath = 'beta' } } }
  }
  if ($null -eq $Deployments) {
    $Deployments = @{ global = @{ shared = @(); codexOnly = @(); workbuddyOnly = @() }; scoped = @{} }
  }
  if ($null -eq $Paths) { $Paths = @{ scopes = @{} } }
  Write-TestJson (Join-Path $root 'profiles\catalog.json') $Catalog
  Write-TestJson (Join-Path $root 'profiles\deployments.json') $Deployments
  Write-TestJson (Join-Path $root 'profiles\paths.local.json') $Paths
  return [PSCustomObject]@{ Root = $root; Home = $testHome }
}

function Remove-TestHub {
  param($Fixture)
  if ($null -ne $Fixture -and (Test-Path -LiteralPath $Fixture.Root)) { Remove-Item -LiteralPath $Fixture.Root -Recurse -Force }
}

Invoke-Test 'catalog matches both source directories' {
  $fixture = New-TestHub
  try {
    $configuration = Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home
    Assert-True ($configuration.Sources.Count -eq 2) 'Expected two indexed skills.'
    New-Item -ItemType Directory -Path (Join-Path $fixture.Root 'skills\self\uncataloged') | Out-Null
    Set-Content -LiteralPath (Join-Path $fixture.Root 'skills\self\uncataloged\SKILL.md') -Value '# uncataloged'
    Assert-Throws { Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home } 'missing from catalog'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'duplicate skill names across ownership groups fail' {
  $fixture = New-TestHub
  try {
    Copy-Item -LiteralPath (Join-Path $fixture.Root 'skills\self\alpha') -Destination (Join-Path $fixture.Root 'skills\third-party\alpha') -Recurse
    $catalog = Get-Content -Raw -LiteralPath (Join-Path $fixture.Root 'profiles\catalog.json') | ConvertFrom-Json
    $catalog.thirdParty | Add-Member -NotePropertyName alpha -NotePropertyValue ([PSCustomObject]@{ status = 'active' })
    Write-TestJson (Join-Path $fixture.Root 'profiles\catalog.json') $catalog
    Assert-Throws { Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home } 'both source groups|both catalog groups'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'retired skills cannot be deployed' {
  $catalog = @{ self = @{ alpha = @{ status = 'retired' } }; thirdParty = @{ beta = @{ status = 'active' } } }
  $deployments = @{ global = @{ shared = @('alpha'); codexOnly = @(); workbuddyOnly = @() }; scoped = @{} }
  $fixture = New-TestHub -Catalog $catalog -Deployments $deployments
  try { Assert-Throws { Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home } 'Retired skill' } finally { Remove-TestHub $fixture }
}

Invoke-Test 'missing Junctions are created and then kept' {
  $deployments = @{ global = @{ shared = @('alpha'); codexOnly = @(); workbuddyOnly = @() }; scoped = @{} }
  $fixture = New-TestHub -Deployments $deployments
  try {
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True (@($plan | Where-Object Action -eq 'CREATE').Count -eq 2) 'Expected two CREATE operations.'
    Invoke-SkillPublishPlan -Plan $plan
    $secondPlan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True (@($secondPlan | Where-Object Action -eq 'KEEP').Count -eq 2) 'Expected two KEEP operations.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'stale Hub Junction is removed' {
  $fixture = New-TestHub
  try {
    $targetRoot = Join-Path $fixture.Home '.agents\skills'
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $targetRoot 'alpha') -Target (Join-Path $fixture.Root 'skills\self\alpha') | Out-Null
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True (@($plan | Where-Object Action -eq 'REMOVE').Count -eq 1) 'Expected one REMOVE operation.'
    Invoke-SkillPublishPlan -Plan $plan
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'alpha'))) 'Stale Junction still exists.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'real directories are preserved as conflicts' {
  $deployments = @{ global = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() }; scoped = @{} }
  $fixture = New-TestHub -Deployments $deployments
  try {
    $destination = Join-Path $fixture.Home '.agents\skills\alpha'
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $destination 'owned.txt') -Value 'keep'
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True (@($plan | Where-Object Action -eq 'CONFLICT').Count -eq 1) 'Expected a conflict.'
    Assert-Throws { Invoke-SkillPublishPlan -Plan $plan } 'no changes were made'
    Assert-True (Test-Path -LiteralPath (Join-Path $destination 'owned.txt')) 'Real directory was modified.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'project-owned and external Junctions are preserved' {
  $fixture = New-TestHub
  try {
    $targetRoot = Join-Path $fixture.Home '.agents\skills'
    $projectTarget = Join-Path $fixture.Root 'project-owned'
    $externalTarget = Join-Path $fixture.Home 'external-owned'
    New-Item -ItemType Directory -Path $targetRoot, $projectTarget, $externalTarget -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $targetRoot 'alpha') -Target $projectTarget | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $targetRoot 'beta') -Target $externalTarget | Out-Null
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True ($plan.Count -eq 0) 'Unmanaged Junctions should not produce operations.'
    Assert-True ((Get-Item -Force -LiteralPath (Join-Path $targetRoot 'alpha')).LinkType -eq 'Junction') 'Project Junction was changed.'
    Assert-True ((Get-Item -Force -LiteralPath (Join-Path $targetRoot 'beta')).LinkType -eq 'Junction') 'External Junction was changed.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'invalid Junctions are validated and removed while healthy Junctions remain' {
  $fixture = New-TestHub
  try {
    $targetRoot = Join-Path $fixture.Home '.agents\skills'
    $missingTarget = Join-Path $fixture.Root 'missing-target'
    $healthyTarget = Join-Path $fixture.Root 'healthy-target'
    New-Item -ItemType Directory -Path $targetRoot, $missingTarget, $healthyTarget -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $targetRoot 'broken') -Target $missingTarget | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $targetRoot 'healthy') -Target $healthyTarget | Out-Null
    [IO.Directory]::Delete($missingTarget)

    $configuration = Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)

    Assert-True ($configuration.InvalidJunctions.Count -eq 1) 'Expected validation to find exactly one invalid Junction.'
    Assert-True ($configuration.InvalidJunctions[0].Skill -eq 'broken') 'Expected validation to report the broken Junction.'
    Assert-True (@($plan | Where-Object { $_.Action -eq 'REMOVE' -and $_.Reason -eq 'INVALID' }).Count -eq 1) 'Expected one invalid Junction removal.'
    Invoke-SkillPublishPlan -Plan $plan
    Assert-True ($null -eq (Get-Item -Force -LiteralPath (Join-Path $targetRoot 'broken') -ErrorAction SilentlyContinue)) 'Invalid Junction was not removed.'
    Assert-True ((Get-Item -Force -LiteralPath (Join-Path $targetRoot 'healthy')).LinkType -eq 'Junction') 'Healthy Junction was removed.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'invalid desired Junctions are replaced in one publish plan' {
  $deployments = @{ global = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() }; scoped = @{} }
  $fixture = New-TestHub -Deployments $deployments
  try {
    $targetRoot = Join-Path $fixture.Home '.agents\skills'
    $missingTarget = Join-Path $fixture.Root 'missing-target'
    $destination = Join-Path $targetRoot 'alpha'
    New-Item -ItemType Directory -Path $targetRoot, $missingTarget -Force | Out-Null
    New-Item -ItemType Junction -Path $destination -Target $missingTarget | Out-Null
    [IO.Directory]::Delete($missingTarget)

    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)

    Assert-True (@($plan | Where-Object { $_.Action -eq 'REMOVE' -and $_.Reason -eq 'INVALID' }).Count -eq 1) 'Expected the invalid Junction to be removed.'
    Assert-True (@($plan | Where-Object Action -eq 'CREATE').Count -eq 1) 'Expected the desired Junction to be recreated.'
    Assert-True (@($plan | Where-Object Action -eq 'CONFLICT').Count -eq 0) 'Invalid desired Junction should not be a conflict.'
    Invoke-SkillPublishPlan -Plan $plan
    $repaired = Get-Item -Force -LiteralPath $destination
    Assert-True (@($repaired.Target)[0] -eq (Join-Path $fixture.Root 'skills\self\alpha')) 'Desired Junction was not repaired.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'any conflict makes Apply zero-modification' {
  $deployments = @{ global = @{ shared = @('alpha'); codexOnly = @(); workbuddyOnly = @() }; scoped = @{} }
  $fixture = New-TestHub -Deployments $deployments
  try {
    $conflict = Join-Path $fixture.Home '.agents\skills\alpha'
    New-Item -ItemType Directory -Path $conflict -Force | Out-Null
    $plan = @(Get-SkillPublishPlan -Root $fixture.Root -UserHome $fixture.Home)
    Assert-True (@($plan | Where-Object Action -eq 'CREATE').Count -eq 1) 'Expected one pending create.'
    Assert-True (@($plan | Where-Object Action -eq 'CONFLICT').Count -eq 1) 'Expected one conflict.'
    Assert-Throws { Invoke-SkillPublishPlan -Plan $plan } 'no changes were made'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $fixture.Home '.workbuddy\skills\alpha'))) 'Apply created a Junction despite conflict.'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'global and scoped deployment for one host fails' {
  $fixture = New-TestHub
  try {
    $scopeRoot = Join-Path $fixture.Root 'project'
    New-Item -ItemType Directory -Path $scopeRoot | Out-Null
    $deployments = @{ global = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() }; scoped = @{ project = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() } } }
    Write-TestJson (Join-Path $fixture.Root 'profiles\deployments.json') $deployments
    Write-TestJson (Join-Path $fixture.Root 'profiles\paths.local.json') @{ scopes = @{ project = $scopeRoot } }
    Assert-Throws { Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home } 'both globally and scoped'
  } finally { Remove-TestHub $fixture }
}

Invoke-Test 'nested scopes cannot deploy one skill to one host' {
  $fixture = New-TestHub
  try {
    $parent = Join-Path $fixture.Root 'project'
    $child = Join-Path $parent 'child'
    New-Item -ItemType Directory -Path $child -Force | Out-Null
    $empty = @{ shared = @(); codexOnly = @(); workbuddyOnly = @() }
    $scoped = @{ parent = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() }; child = @{ shared = @(); codexOnly = @('alpha'); workbuddyOnly = @() } }
    Write-TestJson (Join-Path $fixture.Root 'profiles\deployments.json') @{ global = $empty; scoped = $scoped }
    Write-TestJson (Join-Path $fixture.Root 'profiles\paths.local.json') @{ scopes = @{ parent = $parent; child = $child } }
    Assert-Throws { Get-SkillHubConfiguration -Root $fixture.Root -UserHome $fixture.Home } 'nested scopes'
  } finally { Remove-TestHub $fixture }
}

Write-Host "SkillPublisher: $script:Passed passed, $script:Failed failed"
if ($script:Failed -gt 0) { throw 'SkillPublisher tests failed.' }
