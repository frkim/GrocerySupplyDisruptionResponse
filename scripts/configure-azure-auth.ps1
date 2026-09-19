#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('ValidateSecret', 'UseAzureCli')]
    [string]$Mode
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest

function Read-Guid {
    param([object]$Value, [string]$Label)

    $guid = [guid]::Empty
    if ($Value -isnot [string] -or [string]::IsNullOrWhiteSpace($Value) -or
        -not [guid]::TryParse($Value, [ref]$guid) -or $guid -eq [guid]::Empty) {
        throw "$Label must be a nonempty, valid GUID."
    }
    return $guid
}

function Read-JsonObject {
    param([string]$Text, [string]$Label)

    try {
        $value = ConvertFrom-Json -InputObject $Text -AsHashtable -NoEnumerate -ErrorAction Stop
    }
    catch {
        # Parser exceptions can contain the credential payload.
        throw "$Label must contain valid JSON."
    }
    if ($value -isnot [System.Collections.IDictionary]) {
        throw "$Label must be a JSON object."
    }
    return $value
}

function Invoke-AuthCommand {
    param([string]$Command, [string[]]$Arguments, [string]$Label)

    try {
        # Capture every stream: CLI diagnostics must not expose account data or tokens.
        $output = & $Command @Arguments *>&1
        $exitCode = $LASTEXITCODE
    }
    catch {
        throw "$Label failed. Deployment is blocked."
    }
    if ($exitCode -ne 0) {
        throw "$Label failed (exit $exitCode). Deployment is blocked."
    }
    return ($output -join "`n")
}

$settings = @{}
foreach ($name in @(
    'AZURE_CLIENT_ID', 'AZURE_TENANT_ID', 'AZURE_SUBSCRIPTION_ID', 'AZURE_ENV_NAME', 'AZURE_LOCATION'
)) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required repository variable $name is missing or empty."
    }
    $settings[$name] = $value
}
foreach ($name in @('AZURE_CLIENT_ID', 'AZURE_TENANT_ID', 'AZURE_SUBSCRIPTION_ID')) {
    $settings[$name] = Read-Guid -Value $settings[$name] -Label $name
}

if ($Mode -eq 'ValidateSecret') {
    $payload = $env:AZURE_CREDENTIALS
    if ([string]::IsNullOrWhiteSpace($payload)) {
        throw 'AZURE_CREDENTIALS is missing or empty.'
    }
    $credentials = Read-JsonObject -Text $payload -Label 'AZURE_CREDENTIALS'
    foreach ($field in @('clientId', 'clientSecret', 'subscriptionId', 'tenantId')) {
        if ($credentials[$field] -isnot [string] -or
            [string]::IsNullOrWhiteSpace($credentials[$field])) {
            throw "AZURE_CREDENTIALS requires a nonempty string for $field."
        }
    }
    $fields = @{
        clientId = 'AZURE_CLIENT_ID'
        tenantId = 'AZURE_TENANT_ID'
        subscriptionId = 'AZURE_SUBSCRIPTION_ID'
    }
    foreach ($field in $fields.Keys) {
        $actual = Read-Guid -Value $credentials[$field] -Label "AZURE_CREDENTIALS $field"
        if ($actual -ne $settings[$fields[$field]]) {
            throw "AZURE_CREDENTIALS $field does not match repository variable $($fields[$field])."
        }
    }
    Write-Host 'AZURE_CREDENTIALS is valid and matches the deployment repository variables.'
    return
}

$accountJson = Invoke-AuthCommand -Command 'az' -Arguments @(
    'account', 'show', '--output', 'json', '--only-show-errors'
) -Label 'Azure CLI account check'
$account = Read-JsonObject -Text $accountJson -Label 'Azure CLI account response'
foreach ($pair in @(
    @{ Field = 'id'; Variable = 'AZURE_SUBSCRIPTION_ID' },
    @{ Field = 'tenantId'; Variable = 'AZURE_TENANT_ID' }
)) {
    $actual = Read-Guid -Value $account[$pair.Field] -Label "Azure CLI account $($pair.Field)"
    if ($actual -ne $settings[$pair.Variable]) {
        throw "Azure CLI account does not match repository variable $($pair.Variable)."
    }
}
$user = $account['user']
if ($user -isnot [System.Collections.IDictionary] -or
    $user['type'] -isnot [string] -or $user['type'] -cne 'servicePrincipal') {
    throw 'Azure CLI must be authenticated as the deployment service principal.'
}
$clientId = Read-Guid -Value $user['name'] -Label 'Azure CLI service principal client ID'
if ($clientId -ne $settings['AZURE_CLIENT_ID']) {
    throw 'Azure CLI service principal does not match repository variable AZURE_CLIENT_ID.'
}

Invoke-AuthCommand -Command 'azd' -Arguments @(
    'config', 'set', 'auth.useAzCliAuth', 'true'
) -Label 'Azure Developer CLI Azure CLI authentication configuration' | Out-Null
Invoke-AuthCommand -Command 'azd' -Arguments @(
    'auth', 'login', '--check-status'
) -Label 'Azure Developer CLI authentication status check' | Out-Null
Write-Host 'Deployment service principal verified; Azure Developer CLI is using the Azure CLI session.'
