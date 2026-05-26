# Data Folder

This folder is the local cache for benchmark input data. The downloader writes the configured source file into this folder and can optionally decompress `.bz2` files next to the downloaded archive.

Generated and downloaded data files in this folder are ignored by Git. Keep this README tracked, but do not commit the large corpus files.

## Configure `.env`

Set these values before loading the ESRally OpenAI vector corpus:

```dotenv
DATA_URL=https://rally-tracks.elastic.co/openai_vector/open_ai_corpus-initial-indexing.json.bz2
DATA_DIR=./data
DATA_TYPE=file
DOC_JSON_PATH=./data/open_ai_corpus-initial-indexing.json
DOC_JSON_FORMAT=jsonl
PARTITION_KEY_FIELD=docid
REPLACE_PARTITION_KEY_WITH_GUID=false
```

`DATA_URL` is the remote file to download. `DATA_DIR` is where the downloaded and optionally decompressed files are written. `DOC_JSON_PATH` can point to either the plain JSON/JSONL file or the `.bz2` compressed file that the benchmark should upload. Every loaded document must contain `PARTITION_KEY_FIELD`. If `REPLACE_PARTITION_KEY_WITH_GUID=true`, the writer replaces that field with a generated GUID before upload. If a source document is missing `id`, the writer copies the final `PARTITION_KEY_FIELD` value into `id` before upload.

## Download Data

Run the downloader before running the benchmark. It decompresses `.bz2` files by default.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\src\download_data.py
```

macOS/Linux:

```bash
./.venv/bin/python ./src/download_data.py
```

To download only and skip decompression:

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe .\src\download_data.py --no-decompress
```

macOS/Linux:

```bash
./.venv/bin/python ./src/download_data.py --no-decompress
```

With the default URL, the loader creates these files:

```text
data/open_ai_corpus-initial-indexing.json.bz2
data/open_ai_corpus-initial-indexing.json
```

Run the benchmark with `DATA_TYPE=file` and `DOC_JSON_PATH` pointing at one of the local files:

```dotenv
DOC_JSON_PATH=./data/open_ai_corpus-initial-indexing.json
```

or:

```dotenv
DOC_JSON_PATH=./data/open_ai_corpus-initial-indexing.json.bz2
```

The benchmark reader infers compression from the `.bz2` file name. Reading the compressed file directly avoids keeping a decompressed copy, but it uses CPU to decompress during each benchmark run.