#requires -Version 7.0
<#
azd lifecycle entry point; run from azure.yaml with:
  pwsh ./scripts/azd-hooks.ps1 -Phase preprovision|postprovision|postdeploy
Endpoints are inherited from azd outputs; this script never creates a .env file.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('preprovision', 'postprovision', 'postdeploy')]
    [string]$Phase
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.azure/azd-hooks/.venv'
$VenvPython = Join-Path $Venv $(if ($IsWindows) { 'Scripts/python.exe' } else { 'bin/python' })

try {
    if (Test-Path -LiteralPath $VenvPython -PathType Leaf) {
        $Python = $VenvPython
    }
    else {
        $Python = $null
        $Candidates = if ($IsWindows) { @('python', 'python3') } else { @('python3', 'python') }
        foreach ($Candidate in $Candidates) {
            $Command = Get-Command $Candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($Command) {
                $Python = $Command.Source
                break
            }
        }
        if (-not $Python) { throw 'Python 3.11+ is required. Install Python and rerun azd up.' }
    }

    & $Python (Join-Path $PSScriptRoot 'deployment_hooks.py') --phase $Phase
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("azd $Phase hook failed (Python exit code $LASTEXITCODE).")
        exit $LASTEXITCODE
    }
}
catch {
    [Console]::Error.WriteLine("azd $Phase hook failed: $($_.Exception.Message)")
    exit 1
}
