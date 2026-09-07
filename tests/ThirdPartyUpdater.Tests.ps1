$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
Import-Module (Join-Path $PSScriptRoot '..\scripts\ThirdPartyUpdater.psm1') -Force

$script:Passed = 0
$script:Failed = 0

function Assert-True { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw $Message } }
function Invoke-Test {
  param([string]$Name, [scriptblock]$Body)
  try { & $Body; $script:Passed++; Write-Host "PASS $Name" } catch { $script:Failed++; Write-Host "FAIL $Name`n  $($_.Exception.Message)`n  $($_.ScriptStackTrace)" }
}
function Write-TestJson { param([string]$Path, $Value) $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8 }

Invoke-Test 'updates are grouped once per repository and manual-only is skipped' {
  $root = Join-Path ([IO.Path]::GetTempPath()) ('third-party-group-test-' + [Guid]::NewGuid().ToString('N'))
  try {
    New-Item -ItemType Directory -Path (Join-Path $root 'profiles') -Force | Out-Null
    $catalog = @{ thirdParty = @{
      one = @{ status = 'active'; repository = 'https://example.invalid/shared'; subpath = 'one' }
      two = @{ status = 'active'; repository = 'https://example.invalid/shared'; subpath = 'two' }
      manual = @{ status = 'active' }
    } }
    Write-TestJson (Join-Path $root 'profiles\catalog.json') $catalog
    $entries = @(Get-ThirdPartyUpdateSelection -Root $root)
    $groups = @(Group-ThirdPartyUpdates -Entries $entries)
    Assert-True ($groups.Count -eq 1) 'Expected exactly one repository fetch group.'
    Assert-True ($groups[0].Entries.Count -eq 2) 'Expected both repository skills in one group.'
    $manual = @($entries | Where-Object ManualOnly)
    Assert-True ($manual.Count -eq 1 -and $manual[0].Skill -eq 'manual') 'Expected manual-only entry to be reported.'
    Assert-True (@($groups[0].Entries | Where-Object Skill -eq 'manual').Count -eq 0) 'Manual-only entry was not skipped.'
    $output = @(& (Join-Path $PSScriptRoot '..\scripts\update-third-party.ps1') -HubRoot $root -Skill manual)
    Assert-True (($output -join "`n") -match 'MANUAL-ONLY manual') 'Manual-only entry was not reported by the updater.'
    Assert-True (($output -join "`n") -notmatch 'FETCH') 'Manual-only entry triggered a repository fetch.'
  } finally { if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force } }
}

Invoke-Test 'dry-run reports differences without changing snapshots' {
  $root = Join-Path ([IO.Path]::GetTempPath()) ('third-party-dryrun-test-' + [Guid]::NewGuid().ToString('N'))
  $upstream = Join-Path $root 'upstream'
  try {
    New-Item -ItemType Directory -Path (Join-Path $root 'profiles'), (Join-Path $root 'skills\third-party\sample'), (Join-Path $upstream 'sample') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $root 'skills\third-party\sample\SKILL.md') -Value 'old snapshot' -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $upstream 'sample\SKILL.md') -Value 'new upstream' -Encoding UTF8
    & git init --quiet $upstream
    & git -C $upstream add .
    & git -C $upstream -c user.name=SkillHubTest -c user.email=skillhub@example.invalid commit --quiet -m initial
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create local upstream repository.' }
    Write-TestJson (Join-Path $root 'profiles\catalog.json') @{ thirdParty = @{ sample = @{ status = 'active'; repository = $upstream; subpath = 'sample' } } }
    $before = Get-Content -Raw -LiteralPath (Join-Path $root 'skills\third-party\sample\SKILL.md')
    & (Join-Path $PSScriptRoot '..\scripts\update-third-party.ps1') -HubRoot $root -All | Out-Null
    $after = Get-Content -Raw -LiteralPath (Join-Path $root 'skills\third-party\sample\SKILL.md')
    Assert-True ($before -eq $after) 'Dry-run modified the third-party snapshot.'
  } finally { if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force } }
}

Write-Host "ThirdPartyUpdater: $script:Passed passed, $script:Failed failed"
if ($script:Failed -gt 0) { throw 'ThirdPartyUpdater tests failed.' }
