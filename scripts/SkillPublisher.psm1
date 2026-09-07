Set-StrictMode -Version 2.0

function Get-NormalizedPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Get-PropertyNames {
  param($Object)
  if ($null -eq $Object) { return @() }
  return @($Object.PSObject.Properties | ForEach-Object { $_.Name })
}

function Read-JsonFile {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required configuration file does not exist: $Path" }
  return Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
}

function Test-PathInside {
  param([Parameter(Mandatory = $true)][string]$Parent, [Parameter(Mandatory = $true)][string]$Child)
  $parentPath = (Get-NormalizedPath $Parent) + [IO.Path]::DirectorySeparatorChar
  return (Get-NormalizedPath $Child).StartsWith($parentPath, [StringComparison]::OrdinalIgnoreCase)
}

function Get-JunctionTarget {
  param([Parameter(Mandatory = $true)]$Item)
  if ($Item.LinkType -ne 'Junction') { return $null }
  $target = @($Item.Target)[0]
  if ([string]::IsNullOrWhiteSpace($target)) { return $null }
  if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path $Item.Parent.FullName $target }
  return Get-NormalizedPath $target
}

function Get-InvalidJunctions {
  param([Parameter(Mandatory = $true)][object[]]$Targets)
  $invalid = [Collections.Generic.List[object]]::new()
  foreach ($target in $Targets) {
    if (-not (Test-Path -LiteralPath $target.TargetRoot -PathType Container)) { continue }
    foreach ($item in @(Get-ChildItem -Force -LiteralPath $target.TargetRoot)) {
      if ($item.LinkType -ne 'Junction') { continue }
      $junctionTarget = Get-JunctionTarget $item
      if ($null -ne $junctionTarget -and (Test-Path -LiteralPath $junctionTarget)) { continue }
      $invalid.Add([PSCustomObject]@{ Host = $target.Host; Scope = $target.Scope; Skill = $item.Name; Path = $item.FullName; Target = $junctionTarget })
    }
  }
  return @($invalid | Sort-Object Host, Scope, Skill)
}

function Get-SkillHubConfiguration {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string]$UserHome = [Environment]::GetFolderPath('UserProfile')
  )

  $rootPath = Get-NormalizedPath $Root
  $catalog = Read-JsonFile (Join-Path $rootPath 'profiles\catalog.json')
  $deployments = Read-JsonFile (Join-Path $rootPath 'profiles\deployments.json')
  $paths = Read-JsonFile (Join-Path $rootPath 'profiles\paths.local.json')
  $errors = [Collections.Generic.List[string]]::new()
  $sources = @{}
  $ownership = @{}
  $catalogGroups = @{ self = Join-Path $rootPath 'skills\self'; thirdParty = Join-Path $rootPath 'skills\third-party' }

  foreach ($groupName in @('self', 'thirdParty')) {
    $sourceRoot = $catalogGroups[$groupName]
    if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
      $errors.Add("Skill source directory does not exist: $sourceRoot")
      continue
    }
    $group = $catalog.$groupName
    if ($null -eq $group) {
      $errors.Add("catalog.json is missing '$groupName'.")
      continue
    }
    $directoryNames = @(Get-ChildItem -LiteralPath $sourceRoot -Directory | ForEach-Object { $_.Name } | Sort-Object)
    foreach ($directoryName in $directoryNames) {
      $skillPath = Join-Path $sourceRoot $directoryName
      if (-not (Test-Path -LiteralPath (Join-Path $skillPath 'SKILL.md') -PathType Leaf)) { $errors.Add("Skill directory is missing SKILL.md: $skillPath") }
      if ($sources.ContainsKey($directoryName)) {
        $errors.Add("Skill '$directoryName' exists in both source groups.")
      } else {
        $sources[$directoryName] = Get-NormalizedPath $skillPath
        $ownership[$directoryName] = $groupName
      }
    }
    $catalogNames = @(Get-PropertyNames $group | Sort-Object)
    $missingCatalog = @($directoryNames | Where-Object { $_ -notin $catalogNames })
    $missingSource = @($catalogNames | Where-Object { $_ -notin $directoryNames })
    if ($missingCatalog.Count -gt 0) { $errors.Add("$groupName source skills missing from catalog: $($missingCatalog -join ', ')") }
    if ($missingSource.Count -gt 0) { $errors.Add("$groupName catalog skills missing from source directory: $($missingSource -join ', ')") }
    foreach ($name in $catalogNames) {
      $entry = $group.$name
      if ($entry.status -notin @('active', 'retired')) { $errors.Add("Skill '$name' has unsupported status '$($entry.status)'.") }
      if ($groupName -eq 'self' -and (Get-PropertyNames $entry) -contains 'repository') { $errors.Add("Self skill '$name' must not define a repository.") }
    }
  }

  $selfNames = @(Get-PropertyNames $catalog.self)
  $thirdPartyNames = @(Get-PropertyNames $catalog.thirdParty)
  $duplicates = @($selfNames | Where-Object { $_ -in $thirdPartyNames })
  if ($duplicates.Count -gt 0) { $errors.Add("Skills cannot appear in both catalog groups: $($duplicates -join ', ')") }
  if ($null -eq $paths.scopes) { $errors.Add("paths.local.json is missing 'scopes'.") }
  if ($null -eq $deployments.global -or $null -eq $deployments.scoped) { $errors.Add("deployments.json must contain 'global' and 'scoped'.") }

  $records = [Collections.Generic.List[object]]::new()
  $targets = [Collections.Generic.List[object]]::new()
  $contexts = [Collections.Generic.List[object]]::new()
  if ($null -ne $deployments.global) { $contexts.Add([PSCustomObject]@{ Name = 'global'; IsGlobal = $true; Definition = $deployments.global; Root = $null }) }
  $scopeRoots = @{}
  foreach ($scopeName in @(Get-PropertyNames $deployments.scoped)) {
    if ($null -eq $paths.scopes -or $scopeName -notin (Get-PropertyNames $paths.scopes)) {
      $errors.Add("Scoped deployment '$scopeName' is missing from paths.local.json.")
      continue
    }
    $scopeValue = $paths.scopes.$scopeName
    if (-not ($scopeValue -is [string]) -or [string]::IsNullOrWhiteSpace($scopeValue)) {
      $errors.Add("Scope '$scopeName' must map to a non-empty root path.")
      continue
    }
    $scopeRoot = Get-NormalizedPath $scopeValue
    if (-not (Test-Path -LiteralPath $scopeRoot -PathType Container)) { $errors.Add("Scope root does not exist: $scopeRoot") }
    foreach ($existingName in @($scopeRoots.Keys)) {
      if ($scopeRoots[$existingName] -eq $scopeRoot) { $errors.Add("Scope aliases '$existingName' and '$scopeName' resolve to the same root: $scopeRoot") }
    }
    $scopeRoots[$scopeName] = $scopeRoot
    $contexts.Add([PSCustomObject]@{ Name = $scopeName; IsGlobal = $false; Definition = $deployments.scoped.$scopeName; Root = $scopeRoot })
  }

  foreach ($context in $contexts) {
    $seenInContext = @{}
    foreach ($groupName in @('shared', 'codexOnly', 'workbuddyOnly')) {
      if ($null -eq $context.Definition.$groupName) {
        $errors.Add("Deployment '$($context.Name)' is missing '$groupName'.")
        continue
      }
      foreach ($skillName in @($context.Definition.$groupName)) {
        if ([string]::IsNullOrWhiteSpace($skillName)) { $errors.Add("Deployment '$($context.Name)/$groupName' contains an empty skill name."); continue }
        if ($seenInContext.ContainsKey($skillName)) { $errors.Add("Skill '$skillName' is listed more than once in deployment '$($context.Name)'."); continue }
        $seenInContext[$skillName] = $true
        if (-not $sources.ContainsKey($skillName)) { $errors.Add("Deployment '$($context.Name)' references unknown skill '$skillName'."); continue }
        $catalogGroup = if ($ownership[$skillName] -eq 'self') { $catalog.self } else { $catalog.thirdParty }
        if ($catalogGroup.$skillName.status -eq 'retired') { $errors.Add("Retired skill '$skillName' cannot be deployed."); continue }
        $hosts = if ($groupName -eq 'shared') { @('codex', 'workbuddy') } elseif ($groupName -eq 'codexOnly') { @('codex') } else { @('workbuddy') }
        foreach ($hostName in $hosts) {
          $targetRoot = if ($context.IsGlobal) {
            if ($hostName -eq 'codex') { Join-Path $UserHome '.agents\skills' } else { Join-Path $UserHome '.workbuddy\skills' }
          } else {
            if ($hostName -eq 'codex') { Join-Path $context.Root '.agents\skills' } else { Join-Path $context.Root '.workbuddy\skills' }
          }
          $records.Add([PSCustomObject]@{ Scope = $context.Name; ScopeRoot = $context.Root; IsGlobal = $context.IsGlobal; Host = $hostName; Skill = $skillName; TargetRoot = Get-NormalizedPath $targetRoot; Source = $sources[$skillName] })
        }
      }
    }
    foreach ($hostName in @('codex', 'workbuddy')) {
      $targetRoot = if ($context.IsGlobal) {
        if ($hostName -eq 'codex') { Join-Path $UserHome '.agents\skills' } else { Join-Path $UserHome '.workbuddy\skills' }
      } else {
        if ($hostName -eq 'codex') { Join-Path $context.Root '.agents\skills' } else { Join-Path $context.Root '.workbuddy\skills' }
      }
      $targets.Add([PSCustomObject]@{ Scope = $context.Name; ScopeRoot = $context.Root; IsGlobal = $context.IsGlobal; Host = $hostName; TargetRoot = Get-NormalizedPath $targetRoot })
    }
  }

  foreach ($group in @($records | Group-Object Host, Skill)) {
    $items = @($group.Group)
    $globalItems = @($items | Where-Object { $_.IsGlobal })
    $scopedItems = @($items | Where-Object { -not $_.IsGlobal })
    if ($globalItems.Count -gt 0 -and $scopedItems.Count -gt 0) { $errors.Add("Skill '$($items[0].Skill)' cannot be deployed to $($items[0].Host) both globally and scoped.") }
    for ($left = 0; $left -lt $scopedItems.Count; $left++) {
      for ($right = $left + 1; $right -lt $scopedItems.Count; $right++) {
        if ((Test-PathInside $scopedItems[$left].ScopeRoot $scopedItems[$right].ScopeRoot) -or (Test-PathInside $scopedItems[$right].ScopeRoot $scopedItems[$left].ScopeRoot)) {
          $errors.Add("Skill '$($items[0].Skill)' cannot be deployed to $($items[0].Host) in nested scopes '$($scopedItems[$left].Scope)' and '$($scopedItems[$right].Scope)'.")
        }
      }
    }
  }

  if ($errors.Count -gt 0) { throw "Skill Hub validation failed:`n- $($errors -join "`n- ")" }
  $invalidJunctions = @(Get-InvalidJunctions -Targets @($targets))
  return [PSCustomObject]@{ Root = $rootPath; Catalog = $catalog; Deployments = $deployments; Paths = $paths; Sources = $sources; Records = @($records); Targets = @($targets); InvalidJunctions = $invalidJunctions }
}

function Get-SkillPublishPlan {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][string]$Root, [string]$UserHome = [Environment]::GetFolderPath('UserProfile'))
  $configuration = Get-SkillHubConfiguration -Root $Root -UserHome $UserHome
  $operations = [Collections.Generic.List[object]]::new()
  $invalidPaths = @{}
  foreach ($junction in $configuration.InvalidJunctions) {
    $invalidPaths[(Get-NormalizedPath $junction.Path)] = $true
    $operations.Add([PSCustomObject]@{ Action = 'REMOVE'; Reason = 'INVALID'; Host = $junction.Host; Scope = $junction.Scope; Skill = $junction.Skill; Path = $junction.Path; Source = $null; Existing = $junction.Target })
  }
  foreach ($target in $configuration.Targets) {
    $desiredRecords = @($configuration.Records | Where-Object { $_.Host -eq $target.Host -and $_.TargetRoot -eq $target.TargetRoot })
    $desiredNames = @{}
    foreach ($record in $desiredRecords) { $desiredNames[$record.Skill] = $true }
    if (Test-Path -LiteralPath $target.TargetRoot -PathType Container) {
      foreach ($item in @(Get-ChildItem -Force -LiteralPath $target.TargetRoot)) {
        if ($item.LinkType -ne 'Junction' -or -not $configuration.Sources.ContainsKey($item.Name)) { continue }
        if ($invalidPaths.ContainsKey((Get-NormalizedPath $item.FullName))) { continue }
        $actualTarget = Get-JunctionTarget $item
        $managedTarget = $configuration.Sources[$item.Name]
        if ($actualTarget -eq $managedTarget -and -not $desiredNames.ContainsKey($item.Name)) {
          $operations.Add([PSCustomObject]@{ Action = 'REMOVE'; Reason = 'STALE'; Host = $target.Host; Scope = $target.Scope; Skill = $item.Name; Path = $item.FullName; Source = $managedTarget; Existing = $actualTarget })
        }
      }
    }
    foreach ($record in $desiredRecords) {
      $destination = Join-Path $record.TargetRoot $record.Skill
      if ($invalidPaths.ContainsKey((Get-NormalizedPath $destination))) {
        $operations.Add([PSCustomObject]@{ Action = 'CREATE'; Reason = $null; Host = $record.Host; Scope = $record.Scope; Skill = $record.Skill; Path = $destination; Source = $record.Source; Existing = $null })
        continue
      }
      $existing = Get-Item -Force -LiteralPath $destination -ErrorAction SilentlyContinue
      if ($null -eq $existing) {
        $operations.Add([PSCustomObject]@{ Action = 'CREATE'; Reason = $null; Host = $record.Host; Scope = $record.Scope; Skill = $record.Skill; Path = $destination; Source = $record.Source; Existing = $null })
        continue
      }
      $actualTarget = Get-JunctionTarget $existing
      if ($existing.LinkType -eq 'Junction' -and $actualTarget -eq $record.Source) {
        $operations.Add([PSCustomObject]@{ Action = 'KEEP'; Reason = $null; Host = $record.Host; Scope = $record.Scope; Skill = $record.Skill; Path = $destination; Source = $record.Source; Existing = $actualTarget })
      } else {
        $existingDescription = if ($existing.LinkType) { "$($existing.LinkType) -> $actualTarget" } elseif ($existing.PSIsContainer) { 'directory' } else { 'file' }
        $operations.Add([PSCustomObject]@{ Action = 'CONFLICT'; Reason = $null; Host = $record.Host; Scope = $record.Scope; Skill = $record.Skill; Path = $destination; Source = $record.Source; Existing = $existingDescription })
      }
    }
  }
  return @($operations | Sort-Object Host, Scope, Skill, Action)
}

function Invoke-SkillPublishPlan {
  [CmdletBinding()]
  param([Parameter(Mandatory = $true)][object[]]$Plan)
  $conflicts = @($Plan | Where-Object { $_.Action -eq 'CONFLICT' })
  if ($conflicts.Count -gt 0) { throw "Publication has $($conflicts.Count) conflict(s); no changes were made." }
  foreach ($operation in @($Plan | Where-Object { $_.Action -eq 'REMOVE' })) {
    $item = Get-Item -Force -LiteralPath $operation.Path -ErrorAction Stop
    $actualTarget = Get-JunctionTarget $item
    $isInvalid = $null -eq $actualTarget -or -not (Test-Path -LiteralPath $actualTarget)
    if ($item.LinkType -ne 'Junction' -or ($operation.Reason -eq 'INVALID' -and -not $isInvalid) -or ($operation.Reason -ne 'INVALID' -and $actualTarget -ne $operation.Source)) {
      throw "Refusing to remove changed or unmanaged path: $($operation.Path)"
    }
    [IO.Directory]::Delete($item.FullName)
  }
  foreach ($operation in @($Plan | Where-Object { $_.Action -eq 'CREATE' })) {
    $parent = Split-Path -Parent $operation.Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    if ($null -ne (Get-Item -Force -LiteralPath $operation.Path -ErrorAction SilentlyContinue)) { throw "Refusing to overwrite a path created after planning: $($operation.Path)" }
    New-Item -ItemType Junction -Path $operation.Path -Target $operation.Source | Out-Null
  }
}

Export-ModuleMember -Function Get-SkillHubConfiguration, Get-SkillPublishPlan, Invoke-SkillPublishPlan
