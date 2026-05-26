# OpenAI Vector Test Scenarios

These scenarios benchmark Cosmos DB vector document ingestion with the [ESRally](https://esrally.readthedocs.io/) OpenAI vector corpus.

## Dataset

Use this source file:

```text
https://rally-tracks.elastic.co/openai_vector/open_ai_corpus-initial-indexing.json.bz2
```

Download the `.bz2` file and keep it compressed. Do not decompress it. The benchmark reader streams paths ending in `.bz2` directly.

## One-Time Setup

Create a Python environment, install dependencies, and sign in for `DefaultAzureCredential` authentication.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
az login
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
az login
```

Create or choose the target Cosmos DB for NoSQL account, database, and container before running the scenarios. The benchmark does not create these resources. For the OpenAI vector corpus, the container should have the vector policy and indexing policy you want to test, and its partition key should align with `docid`.

Use a new container, or make sure the target container is empty before each scenario run. The writer uses create operations, so items that already exist with the same `id` and partition key are not overwritten; they fail as duplicate-item errors.

Set the shared `.env` values:

```dotenv
COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
COSMOS_DATABASE_NAME=testdb
COSMOS_CONTAINER_NAME=<container>

DATA_URL=https://rally-tracks.elastic.co/openai_vector/open_ai_corpus-initial-indexing.json.bz2
DATA_DIR=./data
DATA_TYPE=file
DOC_JSON_PATH=./data/open_ai_corpus-initial-indexing.json.bz2
DOC_JSON_FORMAT=jsonl

PARTITION_KEY_FIELD=docid
REPLACE_PARTITION_KEY_WITH_GUID=false
DOC_QUEUE_MULTIPLIER=30
MAX_CONCURRENCY=30
COSMOS_ERROR_SAMPLE_LIMIT=0

CSV_OUTPUT_ENABLED=true
TEST_RESULTS_ROOT=results
```

Download the compressed source file only:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\src\download_data.py --no-decompress
```

macOS/Linux:

```bash
./.venv/bin/python ./src/download_data.py --no-decompress
```

After download, verify the benchmark input points to the compressed file:

```dotenv
DOC_JSON_PATH=./data/open_ai_corpus-initial-indexing.json.bz2
```

## RU/s Recommendations

Use autoscale throughput for these write-heavy test runs. The table below gives initial autoscale max RU/s recommendations for `quantizedFlat` and `DiskANN` vector indexes.

Assumptions:

- Scenario throughput targets come from the `Docs/sec total` column below.
- For this dataset, `quantizedFlat` vector writes cost about 41 RU/document before buffer.
- For this dataset, `DiskANN` vector writes cost about 81 RU/document before buffer.
- Recommendations include a 20% buffer for indexing overhead, variance, retries, and partition imbalance.
- Recommended autoscale max RU/s values are rounded up to the nearest 1,000 RU/s.

```text
target_docs_per_second = docs_per_second_total
quantizedFlat_autoscale_max_RU = target_docs_per_second * 41 * 1.2
DiskANN_autoscale_max_RU = target_docs_per_second * 81 * 1.2
```

| Config | Iterations | Bulk size (docs/op) | Total docs | Clients | Target throughput | Bulk ops/sec/client | Docs/sec/client | Docs/sec total | `quantizedFlat` autoscale max RU/s | `DiskANN` autoscale max RU/s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10,000 | 18 | 180,000 | 10 | 8 | 0.8 | 14.4 | 144 | 8,000 | 14,000 |
| 2 | 15,000 | 20 | 300,000 | 20 | 24 | 1.2 | 24 | 480 | 24,000 | 47,000 |
| 3 | 40,000 | 30 | 1,200,000 | 30 | 40 | 1.33 | 40 | 1,200 | 60,000 | 117,000 |
| 4 | 10,000 | 40 | 400,000 | 10 | 25 | 2.5 | 100 | 1,000 | 50,000 | 98,000 |
| 5 | 9,000 | 10 | 90,000 | 40 | 8 | 0.2 | 2 | 80 | 4,000 | 8,000 |

If the run reports a different `avg_ru_per_operation`, resize the next run from the measured value:

```text
recommended_autoscale_max_RU = docs_per_second_total * avg_ru_per_operation * 1.2
```

Increase autoscale max RU/s if `throttles_total` rises, or reduce `NUM_CLIENTS` / `MAX_CONCURRENCY` if you want to hold RU/s constant.

## Run Commands

Each scenario has two matching Bicep parameter files under `scenarios/infra/`: one for `quantizedFlat` and one for `DiskANN`. The examples below show the `quantizedFlat` flow only. To run the same scenario with `DiskANN`, use the matching `config-*-diskANN.bicepparam` file and container name instead.

Before provisioning, edit the selected `.bicepparam` file and set `accountName` to your existing Cosmos DB account name. For manual deployments, use the scenario-specific files in `scenarios/infra/`, not the generic `infra/main.bicepparam`. The commands below create the matching container, point the benchmark process at that container, stream the compressed `.bz2` file directly, and write final metrics to `results/` when `CSV_OUTPUT_ENABLED=true`.

To run all five configs, use the helper scripts in this folder. They default to `quantizedFlat`; pass `diskANN` to run the DiskANN parameter files instead. Set `AZURE_RESOURCE_GROUP` to the resource group that contains the existing Cosmos DB account before running either script.

Windows PowerShell:

```powershell
$env:AZURE_RESOURCE_GROUP = '<account-resource-group-name>'

.\scenarios\run-openai.ps1
.\scenarios\run-openai.ps1 diskANN
```

macOS/Linux:

```bash
export AZURE_RESOURCE_GROUP='<account-resource-group-name>'

bash ./scenarios/run-openai.sh
bash ./scenarios/run-openai.sh diskANN
```

### Config 1

Windows PowerShell:

```powershell
$resourceGroup = '<account-resource-group-name>'

az deployment group create --resource-group $resourceGroup --parameters .\scenarios\infra\config-1-quantizedFlat.bicepparam
$env:COSMOS_CONTAINER_NAME = 'benchmark-openai-c1-quantizedflat'
.\.venv\Scripts\python.exe .\main.py --bulk-size 18 --num-clients 10 --total-docs 180000 --data-path .\data\open_ai_corpus-initial-indexing.json.bz2
```

macOS/Linux:

```bash
resourceGroup='<account-resource-group-name>'

az deployment group create --resource-group "$resourceGroup" --parameters ./scenarios/infra/config-1-quantizedFlat.bicepparam
export COSMOS_CONTAINER_NAME='benchmark-openai-c1-quantizedflat'
./.venv/bin/python ./main.py --bulk-size 18 --num-clients 10 --total-docs 180000 --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
```

### Config 2

Windows PowerShell:

```powershell
$resourceGroup = '<account-resource-group-name>'

az deployment group create --resource-group $resourceGroup --parameters .\scenarios\infra\config-2-quantizedFlat.bicepparam
$env:COSMOS_CONTAINER_NAME = 'benchmark-openai-c2-quantizedflat'
.\.venv\Scripts\python.exe .\main.py --bulk-size 20 --num-clients 20 --total-docs 300000 --data-path .\data\open_ai_corpus-initial-indexing.json.bz2
```

macOS/Linux:

```bash
resourceGroup='<account-resource-group-name>'

az deployment group create --resource-group "$resourceGroup" --parameters ./scenarios/infra/config-2-quantizedFlat.bicepparam
export COSMOS_CONTAINER_NAME='benchmark-openai-c2-quantizedflat'
./.venv/bin/python ./main.py --bulk-size 20 --num-clients 20 --total-docs 300000 --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
```

### Config 3

Windows PowerShell:

```powershell
$resourceGroup = '<account-resource-group-name>'

az deployment group create --resource-group $resourceGroup --parameters .\scenarios\infra\config-3-quantizedFlat.bicepparam
$env:COSMOS_CONTAINER_NAME = 'benchmark-openai-c3-quantizedflat'
.\.venv\Scripts\python.exe .\main.py --bulk-size 30 --num-clients 30 --total-docs 1200000 --data-path .\data\open_ai_corpus-initial-indexing.json.bz2
```

macOS/Linux:

```bash
resourceGroup='<account-resource-group-name>'

az deployment group create --resource-group "$resourceGroup" --parameters ./scenarios/infra/config-3-quantizedFlat.bicepparam
export COSMOS_CONTAINER_NAME='benchmark-openai-c3-quantizedflat'
./.venv/bin/python ./main.py --bulk-size 30 --num-clients 30 --total-docs 1200000 --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
```

### Config 4

Windows PowerShell:

```powershell
$resourceGroup = '<account-resource-group-name>'

az deployment group create --resource-group $resourceGroup --parameters .\scenarios\infra\config-4-quantizedFlat.bicepparam
$env:COSMOS_CONTAINER_NAME = 'benchmark-openai-c4-quantizedflat'
.\.venv\Scripts\python.exe .\main.py --bulk-size 40 --num-clients 10 --total-docs 400000 --data-path .\data\open_ai_corpus-initial-indexing.json.bz2
```

macOS/Linux:

```bash
resourceGroup='<account-resource-group-name>'

az deployment group create --resource-group "$resourceGroup" --parameters ./scenarios/infra/config-4-quantizedFlat.bicepparam
export COSMOS_CONTAINER_NAME='benchmark-openai-c4-quantizedflat'
./.venv/bin/python ./main.py --bulk-size 40 --num-clients 10 --total-docs 400000 --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
```

### Config 5

Windows PowerShell:

```powershell
$resourceGroup = '<account-resource-group-name>'

az deployment group create --resource-group $resourceGroup --parameters .\scenarios\infra\config-5-quantizedFlat.bicepparam
$env:COSMOS_CONTAINER_NAME = 'benchmark-openai-c5-quantizedflat'
.\.venv\Scripts\python.exe .\main.py --bulk-size 10 --num-clients 40 --total-docs 90000 --data-path .\data\open_ai_corpus-initial-indexing.json.bz2
```

macOS/Linux:

```bash
resourceGroup='<account-resource-group-name>'

az deployment group create --resource-group "$resourceGroup" --parameters ./scenarios/infra/config-5-quantizedFlat.bicepparam
export COSMOS_CONTAINER_NAME='benchmark-openai-c5-quantizedflat'
./.venv/bin/python ./main.py --bulk-size 10 --num-clients 40 --total-docs 90000 --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
```

## Reading Results

Review the generated CSV in `results/` after each run. The most useful fields are:

| Field | Use |
|---|---|
| `throughput_docs_per_sec_current`, `throughput_docs_per_sec_per_client_current` | Latest successful insert throughput sample, total and divided by configured client count. |
| `throughput_docs_per_sec_mean`, `throughput_docs_per_sec_per_client_mean`, `throughput_docs_per_sec_max` | Mean and peak successful insert throughput from sampled windows after warmup. |
| `avg_ru_per_operation` | Actual RU charged per inserted document. |
| `throttles_total` | Cosmos DB 429 throttles. Increase RU/s or reduce client pressure if this rises. |
| `service_time_ms_p90`, `service_time_ms_p99` | Time from each individual Cosmos `create_item` request send until that request receives a response or error. |
| `errors_total` | Non-throttle failures that need inspection before trusting a run. |

Keep the same compressed dataset path for repeatability, and change only one pressure knob at a time when comparing scenarios.