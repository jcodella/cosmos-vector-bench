[CmdletBinding()]
param(
    [ValidateSet('quantizedFlat', 'quantizedflat', 'diskANN', 'diskann')]
    [string]$IndexType = 'quantizedFlat',

    [string]$ResourceGroup = $env:resourceGroup,

    [string]$AccountName = $env:accountName
)

$ErrorActionPreference = 'Stop'

if (-not $ResourceGroup) {
    $callerResourceGroup = Get-Variable -Name resourceGroup -Scope 1 -ValueOnly -ErrorAction SilentlyContinue
    if ($callerResourceGroup) {
        $ResourceGroup = $callerResourceGroup
    }
}

if (-not $ResourceGroup) {
    throw 'Set $env:resourceGroup, set $resourceGroup, or pass -ResourceGroup <resource-group-name>.'
}

if (-not $AccountName) {
    $callerAccountName = Get-Variable -Name accountName -Scope 1 -ValueOnly -ErrorAction SilentlyContinue
    if ($callerAccountName) {
        $AccountName = $callerAccountName
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$normalizedIndexType = if ($IndexType -ieq 'diskANN') { 'diskANN' } else { 'quantizedFlat' }
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonExe = 'python'
}

$scenarios = @(
    @{ Config = 1; BulkSize = 18; NumClients = 10; TotalDocs = 180000 },
    @{ Config = 2; BulkSize = 20; NumClients = 20; TotalDocs = 300000 },
    @{ Config = 3; BulkSize = 30; NumClients = 30; TotalDocs = 1200000 },
    @{ Config = 4; BulkSize = 40; NumClients = 10; TotalDocs = 400000 },
    @{ Config = 5; BulkSize = 10; NumClients = 40; TotalDocs = 90000 }
)

Push-Location $repoRoot
try {
    foreach ($scenario in $scenarios) {
        $config = $scenario.Config
        $paramFile = ".\scenarios\infra\config-$config-$normalizedIndexType.bicepparam"
        $containerName = "s$config-$normalizedIndexType"

        Write-Host ""
        Write-Host "=== OpenAI config $config ($normalizedIndexType) ==="
        Write-Host "Provisioning $containerName"
        $deploymentParameters = @($paramFile)
        if ($AccountName) {
            $deploymentParameters += "accountName=$AccountName"
        }
        az deployment group create --resource-group $ResourceGroup --parameters $deploymentParameters
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        Write-Host "Running benchmark against $containerName"
        & $pythonExe .\main.py `
            --bulk-size $scenario['BulkSize'] `
            --num-clients $scenario['NumClients'] `
            --total-docs $scenario['TotalDocs'] `
            --data-path .\data\open_ai_corpus-initial-indexing.json.bz2 `
            --container-name $containerName

        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
}
finally {
    Pop-Location
}