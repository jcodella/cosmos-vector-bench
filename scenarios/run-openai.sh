#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--index-type quantizedFlat|diskANN] [--resource-group name] [--account-name name]" >&2
}

index_type="quantizedFlat"
resource_group="${resourceGroup:-}"
account_name="${accountName:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --index-type|-i)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      index_type="$2"
      shift 2
      ;;
    --resource-group|-g)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      resource_group="$2"
      shift 2
      ;;
    --account-name|-a)
      if [[ $# -lt 2 ]]; then
        usage
        exit 2
      fi
      account_name="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

index_type_lower="$(printf '%s' "$index_type" | tr '[:upper:]' '[:lower:]')"

case "$index_type_lower" in
  quantizedflat)
    normalized_index_type="quantizedFlat"
    ;;
  diskann)
    normalized_index_type="diskANN"
    ;;
  *)
    usage
    exit 2
    ;;
esac

if [[ -z "$resource_group" ]]; then
  echo "Set resourceGroup or pass --resource-group before running this script." >&2
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
  container_name="s${config}-${normalized_index_type}"

  echo
  echo "=== OpenAI config ${config} (${normalized_index_type}) ==="
  echo "Provisioning ${container_name}"
  deployment_parameters=("$param_file")
  if [[ -n "$account_name" ]]; then
    deployment_parameters+=("accountName=$account_name")
  fi
  az deployment group create --resource-group "$resource_group" --parameters "${deployment_parameters[@]}"

  echo "Running benchmark against ${container_name}"
  "$python_bin" ./main.py \
    --bulk-size "$bulk_size" \
    --num-clients "$num_clients" \
    --total-docs "$total_docs" \
    --data-path ./data/open_ai_corpus-initial-indexing.json.bz2 \
    --container-name "$container_name"
done