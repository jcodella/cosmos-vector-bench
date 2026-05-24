[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('quantizedFlat', 'quantizedflat', 'diskANN', 'diskann')]
    [string]$IndexType = 'quantizedFlat',

    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP
)

$ErrorActionPreference = 'Stop'

if (-not $ResourceGroup) {
    throw 'Set AZURE_RESOURCE_GROUP or pass -ResourceGroup <resource-group-name>.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$normalizedIndexType = if ($IndexType -ieq 'diskANN') { 'diskANN' } else { 'quantizedFlat' }
$containerIndexSuffix = if ($normalizedIndexType -eq 'diskANN') { 'diskann' } else { 'quantizedflat' }
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
        $containerName = "benchmark-openai-c$config-$containerIndexSuffix"

        Write-Host ""
        Write-Host "=== OpenAI config $config ($normalizedIndexType) ==="
        Write-Host "Provisioning $containerName"
        az deployment group create --resource-group $ResourceGroup --parameters $paramFile
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }

        $env:COSMOS_CONTAINER_NAME = $containerName
        Write-Host "Running benchmark against $env:COSMOS_CONTAINER_NAME"
        & $pythonExe .\main.py `
            --bulk-size $scenario['BulkSize'] `
            --num-clients $scenario['NumClients'] `
            --total-docs $scenario['TotalDocs'] `
            --data-path .\data\open_ai_corpus-initial-indexing.json.bz2

        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
}
finally {
    Pop-Location
}