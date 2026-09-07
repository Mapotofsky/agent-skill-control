$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'SkillPublisher.Tests.ps1')
& (Join-Path $PSScriptRoot 'ThirdPartyUpdater.Tests.ps1')
Write-Host 'All tests passed.'
