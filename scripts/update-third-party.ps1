param(
  [string[]]$Skill,
  [string[]]$Repository,
  [switch]$All,
  [switch]$Apply,
  [string]$HubRoot
)

$ErrorActionPreference = 'Stop'
$hasSkillSelection = $null -ne $Skill -and $Skill.Length -gt 0
$hasRepositorySelection = $null -ne $Repository -and $Repository.Length -gt 0
if ($All -and ($hasSkillSelection -or $hasRepositorySelection)) { throw 'Use -All, -Skill, or -Repository as a single selection mode.' }
$root = if ([string]::IsNullOrWhiteSpace($HubRoot)) { [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')) } else { [IO.Path]::GetFullPath($HubRoot) }
Import-Module (Join-Path $PSScriptRoot 'ThirdPartyUpdater.psm1') -Force
$entries = @(Get-ThirdPartyUpdateSelection -Root $root -Skill $Skill -Repository $Repository)
$manualOnly = @($entries | Where-Object { $_.ManualOnly })
foreach ($entry in $manualOnly) { Write-Output "MANUAL-ONLY $($entry.Skill): repository is not recorded; skipped." }
$groups = @(Group-ThirdPartyUpdates -Entries $entries)
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('skill-hub-update-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporaryRoot | Out-Null

try {
  $groupNumber = 0
  foreach ($group in $groups) {
    $groupNumber++
    $checkout = Join-Path $temporaryRoot ([string]$groupNumber)
    Write-Host "FETCH $($group.Repository)"
    & git clone --quiet --depth 1 -- $group.Repository $checkout
    if ($LASTEXITCODE -ne 0) { throw "Failed to fetch repository: $($group.Repository)" }
    foreach ($entry in $group.Entries) {
      $source = if ([string]::IsNullOrWhiteSpace($entry.Subpath)) { $checkout } else { Join-Path $checkout $entry.Subpath }
      if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md') -PathType Leaf)) { throw "Upstream path for '$($entry.Skill)' does not contain SKILL.md: $source" }
      $differences = @(Get-DirectoryDifferences -Source $source -Destination $entry.Destination)
      if ($differences.Count -eq 0) {
        Write-Host "UNCHANGED $($entry.Skill)"
        continue
      }
      Write-Host "CHANGED $($entry.Skill)"
      $differences | ForEach-Object { Write-Host ("  {0,-6} {1}" -f $_.Change, $_.Path) }
      if ($Apply) { Copy-ThirdPartySnapshot -Source $source -Destination $entry.Destination }
    }
  }
} finally {
  if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}

if ($Apply) {
  Write-Host 'APPLIED. Review the resulting Git diff before keeping the updates.'
} else {
  Write-Host 'DRY RUN - no third-party files were changed. Use -Apply to replace snapshots.'
}
