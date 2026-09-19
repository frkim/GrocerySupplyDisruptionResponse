# Compatibility entry point; azd owns provisioning, seeding, build and deployment.
[CmdletBinding()]
param(
    [string]$EnvironmentName = 'grocery-disruption',
    [guid]$SubscriptionId = 'bb766161-890c-4a8e-9c63-981b510e4e38',
    [guid]$TenantId = '6d84d14b-2ff0-4d99-9ab1-fae089687459',
    [string]$Location = 'swedencentral'
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'setup-azd.ps1') `
    -EnvironmentName $EnvironmentName -SubscriptionId $SubscriptionId `
    -TenantId $TenantId -Location $Location

Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    azd up --environment $EnvironmentName
    if ($LASTEXITCODE -ne 0) { throw 'azd deployment failed. See the failed step above.' }
}
finally {
    Pop-Location
}
