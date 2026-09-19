#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$IdentityResourceId,
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$RegistryName,
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$ResourceGroup,
    [Parameter(Mandatory)]
    [guid]$SubscriptionId,
    [ValidateRange(0, 60)]
    [int]$RetryIntervalSeconds = 10,
    [ValidateRange(1, 31)]
    [int]$RetryCount = 31
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
Set-StrictMode -Version Latest
Get-Command az -ErrorAction Stop | Out-Null

function Invoke-AzureCli {
    param([string[]]$Arguments)

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed (exit $LASTEXITCODE): az $($Arguments -join ' '). Review the CLI error above."
    }
    $text = ($output -join "`n").Trim()
    if ([string]::IsNullOrWhiteSpace($text) -or $text -eq 'null') {
        throw "Azure CLI returned missing output: az $($Arguments -join ' ')."
    }
    return $text
}

$currentSubscription = Invoke-AzureCli @(
    'account', 'show', '--query', 'id', '--output', 'tsv', '--only-show-errors'
)
if ($currentSubscription -ne $SubscriptionId.ToString()) {
    throw "Azure CLI subscription '$currentSubscription' does not match deployment subscription '$SubscriptionId'. Sign in to the same subscription as azd."
}
if ($IdentityResourceId -notmatch "^/subscriptions/$SubscriptionId/resourceGroups/[^/]+/providers/Microsoft.ManagedIdentity/userAssignedIdentities/[^/]+$") {
    throw 'SERVICE_APP_IDENTITY_ID must be a user-assigned identity resource ID in the deployment subscription.'
}

$principalId = Invoke-AzureCli @(
    'identity', 'show', '--ids', $IdentityResourceId, '--subscription', $SubscriptionId.ToString(),
    '--query', 'principalId', '--output', 'tsv', '--only-show-errors'
)
$principalGuid = [guid]::Empty
if (-not [guid]::TryParse($principalId, [ref]$principalGuid) -or $principalGuid -eq [guid]::Empty) {
    throw "Managed identity returned an invalid principal ID: '$principalId'."
}
$registryId = Invoke-AzureCli @(
    'acr', 'show', '--name', $RegistryName, '--resource-group', $ResourceGroup,
    '--subscription', $SubscriptionId.ToString(), '--query', 'id', '--output', 'tsv', '--only-show-errors'
)
$expectedRegistryId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerRegistry/registries/$RegistryName"
if ($registryId -ne $expectedRegistryId) {
    throw "Registry resource ID '$registryId' does not match expected deployment registry '$expectedRegistryId'."
}

# Use the built-in role ID and disable name expansion to avoid Microsoft Graph queries.
$acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
$timer = [System.Diagnostics.Stopwatch]::StartNew()
$attempts = 0
Write-Host "Checking AcrPull for principal $principalId at $registryId (up to 300 seconds, $RetryCount attempts)."
for ($attempt = 1; $attempt -le $RetryCount; $attempt++) {
    if ($timer.Elapsed.TotalSeconds -ge 300) { break }
    $attempts = $attempt
    $roleJson = Invoke-AzureCli @(
        'role', 'assignment', 'list', '--assignee-object-id', $principalId, '--scope', $registryId,
        '--subscription', $SubscriptionId.ToString(), '--fill-principal-name', 'false',
        '--fill-role-definition-name', 'false', '--output', 'json', '--only-show-errors'
    )
    $assignments = ConvertFrom-Json -InputObject $roleJson -AsHashtable -NoEnumerate
    if ($assignments -isnot [array]) {
        throw 'Azure CLI role assignment output must be a JSON array (an empty array means the role is not yet visible).'
    }
    foreach ($assignment in $assignments) {
        if ($assignment -isnot [System.Collections.IDictionary]) {
            throw 'Azure CLI returned an invalid role assignment.'
        }
        if ($assignment['principalId'] -eq $principalId -and
            $assignment['scope'] -eq $registryId -and
            $assignment['roleDefinitionId'] -match "(^|/)$acrPullRoleId$") {
            Write-Host "AcrPull role is visible at the ACR scope (attempt $attempt). Image deployment may proceed."
            return
        }
    }

    $remainingSeconds = 300 - $timer.Elapsed.TotalSeconds
    if ($attempt -ge $RetryCount -or $remainingSeconds -le 0) { break }
    $delaySeconds = [Math]::Min($RetryIntervalSeconds, $remainingSeconds)
    Write-Host "AcrPull is not yet visible (attempt $attempt/$RetryCount); retrying in $([Math]::Round($delaySeconds, 1)) seconds."
    Start-Sleep -Milliseconds ([int]($delaySeconds * 1000))
}

throw "AcrPull is not visible for principal $principalId at $registryId after $attempts attempts ($([Math]::Round($timer.Elapsed.TotalSeconds, 1)) seconds). Deployment is blocked. Verify the provisioned assignment and allow RBAC propagation before retrying; this check does not create or change roles."
