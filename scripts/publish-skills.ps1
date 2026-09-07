param(
  [ValidateSet('Validate', 'Check', 'Plan', 'Apply', 'Status')]
  [string]$Mode = 'Check'
)

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Import-Module (Join-Path $PSScriptRoot 'SkillPublisher.psm1') -Force

try {
  if ($Mode -eq 'Validate') {
    $configuration = Get-SkillHubConfiguration -Root $root
    if ($configuration.InvalidJunctions.Count -gt 0) {
      $configuration.InvalidJunctions | Format-Table Host, Scope, Skill, Path, Target -AutoSize
      Write-Host "INVALID: found $($configuration.InvalidJunctions.Count) invalid Junction(s)."
      exit 1
    }
    Write-Host "VALID: $($configuration.Sources.Count) skills, $($configuration.Records.Count) deployment entries; no invalid Junctions."
    exit 0
  }

  $plan = @(Get-SkillPublishPlan -Root $root)
  if ($Mode -eq 'Status') {
    foreach ($action in @('CREATE', 'KEEP', 'REMOVE', 'CONFLICT')) {
      $count = @($plan | Where-Object { $_.Action -eq $action }).Count
      Write-Host ("{0,-8} {1}" -f $action, $count)
    }
  } elseif ($plan.Count -eq 0) {
    Write-Host 'No managed Skill targets are configured.'
  } else {
    $plan | Format-Table Action, Reason, Host, Scope, Skill, Path -AutoSize
  }

  $conflicts = @($plan | Where-Object { $_.Action -eq 'CONFLICT' })
  if ($Mode -eq 'Apply') {
    Invoke-SkillPublishPlan -Plan $plan
    $created = @($plan | Where-Object { $_.Action -eq 'CREATE' }).Count
    $removed = @($plan | Where-Object { $_.Action -eq 'REMOVE' }).Count
    Write-Host "Applied: $created created, $removed removed."
  } elseif ($Mode -in @('Check', 'Plan')) {
    $changes = @($plan | Where-Object { $_.Action -in @('CREATE', 'REMOVE') }).Count
    Write-Host "DRY RUN: $changes change(s), $($conflicts.Count) conflict(s); no changes made."
  }

  if ($conflicts.Count -gt 0) { exit 1 }
  exit 0
} catch {
  Write-Error $_
  exit 1
}
