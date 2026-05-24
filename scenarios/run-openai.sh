#!/usr/bin/env bash
set -euo pipefail

index_type="${1:-quantizedFlat}"
index_type_lower="$(printf '%s' "$index_type" | tr '[:upper:]' '[:lower:]')"

case "$index_type_lower" in
  quantizedflat)
    normalized_index_type="quantizedFlat"
    container_index_suffix="quantizedflat"
    ;;
  diskann)
    normalized_index_type="diskANN"
    container_index_suffix="diskann"
    ;;
  *)
    echo "Usage: $0 [quantizedFlat|diskANN]" >&2
    exit 2
    ;;
esac

resource_group="${AZURE_RESOURCE_GROUP:-}"
if [[ -z "$resource_group" ]]; then
  echo "Set AZURE_RESOURCE_GROUP before running this script." >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"

if [[ -x "./.venv/bin/python" ]]; then
  python_bin="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
else
  python_bin="python"
fi

scenarios=(
  "1 18 10 180000"
  "2 20 20 300000"
  "3 30 30 1200000"
  "4 40 10 400000"
  "5 10 40 90000"
)

for scenario in "${scenarios[@]}"; do
  read -r config bulk_size num_clients total_docs <<< "$scenario"
  param_file="./scenarios/infra/config-${config}-${normalized_index_type}.bicepparam"
  container_name="benchmark-openai-c${config}-${container_index_suffix}"

  echo
  echo "=== OpenAI config ${config} (${normalized_index_type}) ==="
  echo "Provisioning ${container_name}"
  az deployment group create --resource-group "$resource_group" --parameters "$param_file"

  export COSMOS_CONTAINER_NAME="$container_name"
  echo "Running benchmark against ${COSMOS_CONTAINER_NAME}"
  "$python_bin" ./main.py \
    --bulk-size "$bulk_size" \
    --num-clients "$num_clients" \
    --total-docs "$total_docs" \
    --data-path ./data/open_ai_corpus-initial-indexing.json.bz2
done