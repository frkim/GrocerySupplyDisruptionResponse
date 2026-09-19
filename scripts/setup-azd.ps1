[CmdletBinding()]
param(
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$')]
    [string]$EnvironmentName = 'grocery-disruption',
    [guid]$SubscriptionId = 'bb766161-890c-4a8e-9c63-981b510e4e38',
    [guid]$TenantId = '6d84d14b-2ff0-4d99-9ab1-fae089687459',
    [ValidatePattern('^[a-z0-9]+$')]
    [string]$Location = 'swedencentral'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Get-Command azd -ErrorAction Stop | Out-Null
$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    $environmentFile = Join-Path $root ".azure/$EnvironmentName/.env"
    if (Test-Path -LiteralPath $environmentFile) {
        azd env select $EnvironmentName
        if ($LASTEXITCODE -ne 0) { throw "Cannot select azd environment '$EnvironmentName'." }
    }
    else {
        azd env new $EnvironmentName --subscription $SubscriptionId --location $Location --no-prompt
        if ($LASTEXITCODE -ne 0) { throw "Cannot create azd environment '$EnvironmentName'." }
    }

    $settings = [ordered]@{
        AZURE_SUBSCRIPTION_ID = $SubscriptionId.ToString()
        AZURE_TENANT_ID = $TenantId.ToString()
        AZURE_LOCATION = $Location
    }
    foreach ($setting in $settings.GetEnumerator()) {
        azd env set $setting.Key $setting.Value --environment $EnvironmentName
        if ($LASTEXITCODE -ne 0) { throw "Cannot set $($setting.Key) in '$EnvironmentName'." }
    }

    Write-Host "Configured azd environment '$EnvironmentName' for subscription $SubscriptionId."
    Write-Host "Sign in: azd auth login --tenant-id $TenantId"
    Write-Host "Preview: azd provision --preview --environment $EnvironmentName"
    Write-Host "Deploy:  azd up --environment $EnvironmentName"
}
finally {
    Pop-Location
}
