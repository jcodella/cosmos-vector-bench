# Results Folder

Completed benchmark runs write final metrics CSV files in this folder when `CSV_OUTPUT_ENABLED=true`.

Each CSV file name uses this format:

```text
MMDDYY-HHMMSS-clients-<numclients>-bulk-<bulksize>-maxdocs-<maxdocs>.csv
```

For example:

```text
052326-143508-clients-40-bulk-30-maxdocs-all.csv
```

The timestamp is captured at the start of the run. `clients` comes from `NUM_CLIENTS`, `bulk` comes from `BULK_SIZE`, and `maxdocs` comes from `MAX_TOTAL_DOCS`. When `MAX_TOTAL_DOCS` is blank for JSON input, `maxdocs` is `all`.

Generated CSV files are ignored by Git. Keep this README tracked, but do not commit result CSVs.