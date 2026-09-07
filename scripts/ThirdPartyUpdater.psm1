Set-StrictMode -Version 2.0

function Get-ThirdPartyUpdateSelection {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string[]]$Skill,
    [string[]]$Repository
  )

  $hasSkillSelection = $null -ne $Skill -and $Skill.Length -gt 0
  $hasRepositorySelection = $null -ne $Repository -and $Repository.Length -gt 0
  if ($hasSkillSelection -and $hasRepositorySelection) { throw 'Select by Skill or Repository, not both.' }
  $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
  $catalogPath = Join-Path $rootPath 'profiles\catalog.json'
  if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) { throw "Catalog does not exist: $catalogPath" }
  $catalog = Get-Content -Raw -LiteralPath $catalogPath | ConvertFrom-Json
  $entries = [Collections.Generic.List[object]]::new()
  foreach ($property in @($catalog.thirdParty.PSObject.Properties)) {
    $name = $property.Name
    $entry = $property.Value
    $repositoryValue = if ($entry.PSObject.Properties.Name -contains 'repository') { [string]$entry.repository } else { $null }
    $selected = $true
    if ($hasSkillSelection) { $selected = $name -in $Skill }
    if ($hasRepositorySelection) { $selected = $repositoryValue -in $Repository }
    if (-not $selected) { continue }
    $subpath = if ($entry.PSObject.Properties.Name -contains 'subpath') { [string]$entry.subpath } else { '' }
    $entries.Add([PSCustomObject]@{
      Skill = $name
      Repository = $repositoryValue
      Subpath = $subpath
      Destination = Join-Path $rootPath ("skills\third-party\$name")
      ManualOnly = [string]::IsNullOrWhiteSpace($repositoryValue)
    })
  }

  if ($hasSkillSelection) {
    $unknown = @($Skill | Where-Object { $_ -notin @($catalog.thirdParty.PSObject.Properties.Name) })
    if ($unknown.Count -gt 0) { throw "Unknown third-party skill(s): $($unknown -join ', ')" }
  }
  if ($hasRepositorySelection) {
    $knownRepositories = @($catalog.thirdParty.PSObject.Properties | ForEach-Object {
      if ($_.Value.PSObject.Properties.Name -contains 'repository') { $_.Value.repository }
    } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $unknown = @($Repository | Where-Object { $_ -notin $knownRepositories })
    if ($unknown.Count -gt 0) { throw "Unknown third-party repository/repositories: $($unknown -join ', ')" }
  }
  return @($entries | Sort-Object Skill)
}

function Group-ThirdPartyUpdates {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][object[]]$Entries)

  return @($Entries | Where-Object { -not $_.ManualOnly } | Group-Object Repository | ForEach-Object {
    [PSCustomObject]@{ Repository = $_.Name; Entries = @($_.Group | Sort-Object Skill) }
  } | Sort-Object Repository)
}

function Get-DirectoryDifferences {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  $sourceRoot = [IO.Path]::GetFullPath($Source).TrimEnd('\', '/')
  $destinationRoot = [IO.Path]::GetFullPath($Destination).TrimEnd('\', '/')
  $sourceFiles = @{}
  $destinationFiles = @{}
  if (Test-Path -LiteralPath $sourceRoot -PathType Container) {
    foreach ($file in @(Get-ChildItem -Force -LiteralPath $sourceRoot -Recurse -File)) {
      $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
      if ([IO.Path]::GetFileName($relative) -eq '.openskills.json' -or $relative.StartsWith('.git\', [StringComparison]::OrdinalIgnoreCase)) { continue }
      $sourceFiles[$relative] = $file.FullName
    }
  }
  if (Test-Path -LiteralPath $destinationRoot -PathType Container) {
    foreach ($file in @(Get-ChildItem -Force -LiteralPath $destinationRoot -Recurse -File)) {
      $relative = $file.FullName.Substring($destinationRoot.Length).TrimStart('\', '/')
      if ([IO.Path]::GetFileName($relative) -eq '.openskills.json' -or $relative.StartsWith('.git\', [StringComparison]::OrdinalIgnoreCase)) { continue }
      $destinationFiles[$relative] = $file.FullName
    }
  }

  $differences = [Collections.Generic.List[object]]::new()
  foreach ($relative in @($sourceFiles.Keys | Sort-Object)) {
    if (-not $destinationFiles.ContainsKey($relative)) {
      $differences.Add([PSCustomObject]@{ Change = 'ADD'; Path = $relative })
      continue
    }
    $sourceBytes = [IO.File]::ReadAllBytes($sourceFiles[$relative])
    $destinationBytes = [IO.File]::ReadAllBytes($destinationFiles[$relative])
    if (-not [Collections.StructuralComparisons]::StructuralEqualityComparer.Equals($sourceBytes, $destinationBytes)) {
      $differences.Add([PSCustomObject]@{ Change = 'MODIFY'; Path = $relative })
    }
  }
  foreach ($relative in @($destinationFiles.Keys | Sort-Object)) {
    if (-not $sourceFiles.ContainsKey($relative)) { $differences.Add([PSCustomObject]@{ Change = 'REMOVE'; Path = $relative }) }
  }
  return @($differences | Sort-Object Path, Change)
}

function Copy-ThirdPartySnapshot {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )

  if (-not (Test-Path -LiteralPath (Join-Path $Source 'SKILL.md') -PathType Leaf)) { throw "Upstream Skill is missing SKILL.md: $Source" }
  $parent = Split-Path -Parent $Destination
  $staging = Join-Path $parent ('.skill-update-' + [Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $staging | Out-Null
  try {
    foreach ($item in @(Get-ChildItem -Force -LiteralPath $Source)) {
      if ($item.Name -in @('.git', '.openskills.json')) { continue }
      Copy-Item -LiteralPath $item.FullName -Destination $staging -Recurse -Force
    }
    Get-ChildItem -Force -LiteralPath $staging -Recurse -File -Filter '.openskills.json' | Remove-Item -Force
    if (Test-Path -LiteralPath $Destination) { Remove-Item -LiteralPath $Destination -Recurse -Force }
    Move-Item -LiteralPath $staging -Destination $Destination
  } finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
  }
}

Export-ModuleMember -Function Get-ThirdPartyUpdateSelection, Group-ThirdPartyUpdates, Get-DirectoryDifferences, Copy-ThirdPartySnapshot
