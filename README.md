# Cosmos DB Vector Write Throughput Test

This repository contains a standalone Python throughput test for writing documents to Azure Cosmos DB. It can either generate synthetic documents or stream a JSON/JSONL corpus, including `.bz2`-compressed input. Use `src/download_data.py` to download and optionally decompress the source data into `data/` before running the writer.

## File Layout

- `main.py` is the root command entrypoint and accepts CLI overrides for common benchmark settings.
- `src/benchmark.py` is the internal benchmark entrypoint.
- `src/core.py` contains the Cosmos write path and worker orchestration.
- `src/metrics.py` contains metrics tracking, aggregation, console output, and CSV output.
- `src/data.py` contains runtime fake-doc and JSON/JSONL document sources.
- `src/config.py` loads repo-root `.env` and benchmark configuration.
- `src/download_data.py` downloads source datasets into `data/` and can optionally decompress `.bz2` files.
- `counts.py` streams a JSON/JSONL corpus and compares total records with unique `docid` values.

## Get Started Right Away

Before the benchmark setup, create a Python environment and install dependencies:

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

1. Configure the Cosmos DB resource, database, and container.

   Create or choose a Cosmos DB for NoSQL account, a database, and a container with the partition key and vector policy you want to test. The script expects the database and container to already exist, and it authenticates with `DefaultAzureCredential` (EntraID).

   Use a new container, or make sure the target container is empty before each file-based benchmark run. The writer uses create operations, so items that already exist with the same `id` and partition key are not overwritten; they fail as duplicate-item errors.

2. Configure `.env`.

   Set the Cosmos target, source mode, data path, partition key field, and throughput knobs. Some key values are:

   ```dotenv
   COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
   COSMOS_DATABASE_NAME=testdb
   COSMOS_CONTAINER_NAME=<container>
   DATA_TYPE=file
   DOC_JSON_PATH=./data/data-file.json
   DOC_JSON_FORMAT=jsonl
   PARTITION_KEY_FIELD=id
   ```

3. Download the dataset.

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\python.exe .\src\download_data.py
   ```

   macOS/Linux:

   ```bash
   ./.venv/bin/python ./src/download_data.py
   ```

   This downloads `DATA_URL` into `DATA_DIR` and, by default, decompresses `.bz2` files next to the downloaded archive. Use `--no-decompress` to skip that step. The benchmark reader can use either file.

4. Run the benchmark.

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\python.exe .\main.py --num-clients 4 --container-name <container>
   ```

   macOS/Linux:

   ```bash
   ./.venv/bin/python ./main.py --num-clients 4 --container-name <container>
   ```

Final metrics are printed to the console and written to a CSV file under `results/` when `CSV_OUTPUT_ENABLED=true`:

```text
results/<MMDDYY-HHMMSS>-clients-<N>-bulk-<BULK_SIZE>-maxdocs-<MAX_TOTAL_DOCS-or-all>.csv
```

For example:

```text
results/052326-143508-clients-40-bulk-30-maxdocs-all.csv
```

## Use Fake Documents

Fake mode is useful for checking auth, container access, write throughput, and basic throttling without a large source file.

Set:

```dotenv
DATA_TYPE=fake
TOTAL_DOCS=10000
BULK_SIZE=100
MAX_CONCURRENCY=100
PAYLOAD_BYTES=5000
```

Then run:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\main.py --num-clients 4
```

macOS/Linux:

```bash
./.venv/bin/python ./main.py --num-clients 4
```

## Use the local data file

Large json files are sometimes distributed as a bz2-compressed JSONL file where each line is a document. First download it:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\src\download_data.py
```

macOS/Linux:

```bash
./.venv/bin/python ./src/download_data.py
```

By default, the downloader also writes the decompressed `.json` file. To download only the `.bz2` archive, run:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\src\download_data.py --no-decompress
```

macOS/Linux:

```bash
./.venv/bin/python ./src/download_data.py --no-decompress
```

Then configure the writer to read either the decompressed JSON file or the downloaded `.bz2` file. The benchmark reader infers compression from the file name.

```dotenv
DATA_URL=https://path-to-data-file.json
DATA_DIR=./data
DATA_TYPE=file
DOC_JSON_PATH=./data/datafile-json
DOC_JSON_FORMAT=jsonl
PARTITION_KEY_FIELD=id
BULK_SIZE=30
MAX_CONCURRENCY=30
DOC_QUEUE_MULTIPLIER=30
```

To stream the compressed file directly, use:

```dotenv
DOC_JSON_PATH=./data/data-file.json
```

Reading `.bz2` directly avoids keeping the decompressed file, but it spends CPU decompressing during each benchmark run. For repeated throughput runs, the decompressed `.json` file is usually the steadier input path.

Run:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\main.py --num-clients 40
```

macOS/Linux:

```bash
./.venv/bin/python ./main.py --num-clients 40
```

If you want a bounded test run, set:

```dotenv
MAX_TOTAL_DOCS=100000
```

Leave it blank for the full file:

```dotenv
MAX_TOTAL_DOCS=
```

Cosmos DB requires every item to have an `id`, and file-input records must contain the configured `PARTITION_KEY_FIELD`. If `REPLACE_PARTITION_KEY_WITH_GUID=true`, the writer replaces that partition key field with a generated GUID for each loaded file document before upload. If a source document does not already have an `id`, the writer copies the final partition key value into `id`, so the source file does not need to be modified.

## CLI Overrides

`main.py` reads CLI arguments before importing the benchmark modules. Provided arguments are written to environment variables first, so they override matching `.env` values while all omitted values still come from `.env`. This is useful for reusing one `.env` while targeting a different container for a single run.

| Argument | Overrides | Notes |
|---|---|---|
| `--num-clients` | `NUM_CLIENTS` | Number of worker client processes. |
| `--bulk-size` | `BULK_SIZE` | Number of documents in each worker bulk. |
| `--total-docs` | `TOTAL_DOCS`, `MAX_TOTAL_DOCS` | Fake mode document count; JSON mode upload cap. |
| `--data-path` | `DOC_JSON_PATH`, `DATA_TYPE=file` | Uses the provided JSON/JSONL file. Paths ending in `.bz2` are decompressed while reading. |
| `--container-name` | `COSMOS_CONTAINER_NAME` | Target Cosmos DB container name. Wins over `.env` when specified. |

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\main.py --num-clients 40 --bulk-size 30 --total-docs 100000 --data-path .\data\data-file.json --container-name benchmark-100k
```

macOS/Linux:

```bash
./.venv/bin/python ./main.py --num-clients 40 --bulk-size 30 --total-docs 100000 --data-path ./data/data-file.json --container-name benchmark-100k
```

## Configuration

The benchmark loads `.env` and `main.py` can override common values from CLI arguments. The `.env.template` groups settings into Cosmos DB config, data loading, scenario/performance, metrics/diagnostics, and results. The table below lists the current knobs.

| Parameter | Data type | Example | Description |
|---|---|---:|---|
| `COSMOS_ENDPOINT` | string | `https://...documents.azure.com:443/` | Cosmos DB account endpoint. Uses Azure AD via `DefaultAzureCredential`. |
| `COSMOS_DATABASE_NAME` | string | `testdb` | Target database name. Must already exist. |
| `COSMOS_CONTAINER_NAME` | string | `benchmark-100k` | Target container name. Must already exist and have the desired partition key/vector policy. |
| `DATA_URL` | URL string | `https://source-url-here.com/example.json.bz2` | Source URL used by `src/download_data.py`. The file is downloaded into `DATA_DIR`. |
| `DATA_DIR` | path string | `./data` | Directory where `src/download_data.py` stores the downloaded file and optional decompressed JSON output. |
| `DATA_TYPE` | enum string | `fake` or `file` | Selects synthetic document generation or streaming JSON/JSONL input. Paths ending in `.bz2` are decompressed while reading. |
| `DOC_JSON_PATH` | path string | `./data/example.json` | Path to the JSON/JSONL file used by `src/benchmark.py`. May point to a plain file or a `.bz2` compressed file. Required when `DATA_TYPE=file`. |
| `DOC_JSON_FORMAT` | enum string | `jsonl` | JSON shape. Supported: `jsonl`, `array`, `multiple_values`. |
| `DOC_QUEUE_MULTIPLIER` | int | `30` | File-input queue capacity multiplier. Queue document capacity is approximately `NUM_CLIENTS * BULK_SIZE * DOC_QUEUE_MULTIPLIER`. Larger values buffer more documents from disk so inserts are less likely to wait on file loading, but consume more RAM. |
| `NUM_CLIENTS` | int | `1` | Number of worker client processes used to upload documents. Can be overridden with `--num-clients`. |
| `BULK_SIZE` | int | `30` | Number of documents each worker pulls into a local bulk before scheduling uploads. |
| `MAX_TOTAL_DOCS` | optional int | `100000` or blank | Optional cap on how many documents to upload. Blank means no cap for JSON mode. |
| `PARTITION_KEY_FIELD` | string | `docid` | Required field for every file-input document and target Cosmos container partition key path, without the leading slash. Used in diagnostics, must match the existing container policy, and is copied to Cosmos `id` when a source document is missing `id`. |
| `REPLACE_PARTITION_KEY_WITH_GUID` | bool | `false` | When `true`, replaces the configured partition key field with a generated GUID for each loaded JSON/JSONL/.bz2 file document before upload. |
| `COSMOS_ERROR_SAMPLE_LIMIT` | int | `3` | Number of detailed Cosmos write failures to print per worker. |
| `MAX_CONCURRENCY` / `MAX_IN_FLIGHT` | int | `30` | Max concurrent `create_item` calls per worker process. Total possible in-flight writes are roughly `NUM_CLIENTS * MAX_CONCURRENCY`. |
| `MAX_INSERT_RETRIES` | int | `3` | Number of quick retries for throttled or transient Cosmos write failures. Non-transient failures such as duplicate item conflicts fail fast. |
| `INSERT_RETRY_DELAY_MS` | int | `50` | Base retry delay in milliseconds when Cosmos does not return retry-after guidance. Retry-after headers are honored when present. |
| `CAPTURE_RU_CHARGES` | bool | `true` | Captures `x-ms-request-charge` through a per-request response hook. Set to `false` to reduce hot-path overhead; RU metrics will report zero. |
| `PARTITION_KEY_RANGE_RPS_ENABLED` | bool | `false` | Prints live `create_item` requests/sec by `x-ms-partition-key-range-id` when Cosmos returns that response header. Enables a response hook even when `CAPTURE_RU_CHARGES=false`. |
| `TOTAL_DOCS` | int | `1000000` | Number of fake docs generated when `DATA_TYPE=fake`. Also bounded by `MAX_TOTAL_DOCS` if set. |
| `PAYLOAD_BYTES` | int | `5000` | Synthetic payload size for fake docs only. |
| `MAX_PENDING_BULKS` | int | auto | Maximum pending batch tasks per worker. Defaults from concurrency and batch size. |
| `LIVE_INTERVAL_SEC` | float | `1.0` | Backward-compatible default for `METRICS_SAMPLE_INTERVAL_SEC` when the newer setting is not present. |
| `METRICS_SAMPLE_INTERVAL_SEC` | float | `1.0` | Seconds between live metric refreshes and periodic throughput samples. |
| `METRICS_TIMING_SAMPLE_INTERVAL` | int | `1` | Records one service/latency/processing timing sample every N completed local bulks. Higher values reduce metrics overhead. |
| `METRICS_WARMUP_SEC` | float | `0.0` | Warmup duration after the first write request starts. Throughput and timing samples before this cutoff are excluded from final  summaries. |
| `CSV_OUTPUT_ENABLED` | bool | `true` | Writes final metrics to a CSV file when enabled. Set to `false` to disable CSV output. |
| `TEST_RESULTS_ROOT` | path string | `results` | Optional root folder for metrics CSV output. Defaults to `results`. |

## Provisioning Cosmos DB Throughput

For vector write tests, size autoscale throughput from the desired sustained writes per second and the approximate RU cost per document. Then add headroom for larger metadata, document-size variance, uneven partition distribution, indexing overhead, retries, and other factors that can increase RU consumption.

Approximate write RU assumptions:

| Vector index type | Approx RU per inserted document | Notes |
|---|---:|---|
| Quantized flat vector index | ~35 RU/doc | Lower write cost; good first estimate for quantized flat. |
| DiskANN vector index | ~65 RU/doc | Higher write/indexing cost; use a larger budget. |

Formula:

```text
required_RU_per_second = target_docs_per_second * RU_per_doc
recommended_autoscale_max_RU = required_RU_per_second * 1.2
```

The `1.2` multiplier is a 20% buffer. Use more buffer if documents are large, vectors are high-dimensional, partitions are uneven, etc.

Examples:

| Target writes/sec | Quantized flat base RU/s | Quantized flat +20% autoscale max | DiskANN base RU/s | DiskANN +20% autoscale max |
|---:|---:|---:|---:|---:|
| 500 | 17,500 | 21,000 | 32,500 | 39,000 |
| 1,000 | 35,000 | 42,000 | 65,000 | 78,000 |
| 2,000 | 70,000 | 84,000 | 130,000 | 156,000 |
| 5,000 | 175,000 | 210,000 | 325,000 | 390,000 |

Because Cosmos DB autoscale max throughput is provisioned as a maximum RU/s, set the autoscale max at or above the buffered value. For example, for 2,000 writes/sec with DiskANN:

```text
2,000 docs/sec * 65 RU/doc = 130,000 RU/s
130,000 RU/s * 1.2 = 156,000 autoscale max RU/s
```

During runs, watch these final CSV fields. Terminal live output uses the same concepts but renders `_per_` as `/` for readability, such as `current_docs/sec_total` and `avg_ru/operation`.

- `avg_ru_per_operation`: actual average RU charged per write.
- `throttles_total`: if this rises, the workload is exceeding available RU or hitting partition limits.
- `throughput_docs_per_sec_current`: successful insert throughput from the latest sample window.
- `throughput_docs_per_sec_per_client_current`: latest successful insert throughput divided by configured client count.
- `throughput_docs_per_sec_mean` / `throughput_docs_per_sec_per_client_mean` / `throughput_docs_per_sec_max`: mean and peak successful insert throughput from sampled windows after warmup.
- `Partition key range stats`: live terminal-only diagnostics enabled by `PARTITION_KEY_RANGE_RPS_ENABLED=true`. Observed ranges are printed on one line, such as `pkrange_0=ops/sec=500.00 , pkrange_1=ops/sec=450.00`.
- `service_time_ms_p90` / `service_time_ms_p99`: time from each individual `create_item` request send until that request receives a response or error.
- `capture_ru_charges`: whether RU capture was enabled for the run. When `false`, RU metrics are intentionally zero.
- `metrics_timing_sample_interval`: how often bulk timing samples were retained for percentile metrics.

If `avg_ru_per_operation` differs from the estimates, re-size from the measured value:

```text
recommended_autoscale_max_RU = target_docs_per_second * measured_avg_ru_per_operation * 1.2
```

## Tuning Notes

- Increase `NUM_CLIENTS` to add more worker client processes.
- Increase `MAX_CONCURRENCY` to allow more simultaneous writes per process.
- Keep `BULK_SIZE` large enough that workers do not schedule tiny waves of work.
- Keep `DOC_QUEUE_MULTIPLIER` high enough that workers do not starve while the producer reads the JSON/JSONL file from disk. Increase it to reduce disk-loading bottlenecks, but remember that larger queues consume more RAM.
- If throttles rise, reduce client pressure or increase autoscale max RU/s.
- If errors show vector policy issues, verify the target container vector policy. For example, some Cosmos API paths reject `float16` as a vector `dataType`; use a supported policy such as `float32` where required.