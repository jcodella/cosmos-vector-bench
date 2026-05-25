"""Rally-style metrics tracking and reporting for the Cosmos DB write benchmark."""

from __future__ import annotations

import math
import shutil
import time
from itertools import zip_longest

from config import (
    BULK_SIZE,
    CAPTURE_RU_CHARGES,
    CLIENT_PROCESSES,
    MAX_IN_FLIGHT,
    MAX_PENDING_BULKS,
    METRICS_SAMPLE_INTERVAL_SEC,
    METRICS_TIMING_SAMPLE_INTERVAL,
    METRICS_WARMUP_SEC,
    PARTITION_KEY_RANGE_RPS_ENABLED,
    PAYLOAD_BYTES,
    _write_metrics_csv,
)

FINAL_METRIC_INDENT = " " * 5
TERMINAL_SECTION_MARKER = "section:"
TERMINAL_VALUE_MARKER = "value:"
PERCENTILE_RATIOS = {
    "p50": 0.50,
    "p90": 0.90,
    "p99": 0.99,
    "p999": 0.999,
}


def _display_metric_name(name: str) -> str:
    return name.replace("_per_", "/")


def _format_metric_text(text: str) -> str:
    return text.replace("_per_", "/")


def _format_terminal_metrics(prefix: str, metrics: list[str]) -> str:
    formatted_metrics = []
    for metric in metrics:
        if metric.startswith(TERMINAL_SECTION_MARKER):
            formatted_metrics.append(f"  {metric.removeprefix(TERMINAL_SECTION_MARKER)}")
        elif metric.startswith(TERMINAL_VALUE_MARKER):
            formatted_metrics.append(f"    {_format_metric_text(metric.removeprefix(TERMINAL_VALUE_MARKER))}")
        else:
            formatted_metrics.append(f"  {_format_metric_text(metric)}")
    return "\n".join([prefix, *formatted_metrics])


def _print_completion_banner() -> None:
    print("\n***Benchmark completed!***\n", flush=True)


FINAL_METRIC_SECTIONS = {
    "Progress": (
        "total_elapsed_time_sec",
        "insert_time_sec",
        "data_load_time_sec",
        "other_overhead_sec",
        "docs_completed",
    ),
    "Throughput": (
        "throughput_docs_per_sec_current",
        "throughput_docs_per_sec_per_client_current",
        "throughput_docs_per_sec_p50",
        "throughput_docs_per_sec_p90",
        "throughput_docs_per_sec_p99",
        "throughput_docs_per_sec_max",
    ),
    "Timing": (
        "service_time_ms_p50",
        "service_time_ms_p90",
        "service_time_ms_p99",
        "service_time_ms_p999",
    ),
    "Responses": (
        "success",
        "success_total",
        "errors",
        "errors_total",
        "throttles",
        "throttles_total",
        "create_item_attempts",
        "create_item_attempts_total",
        "create_item_failure_attempts",
        "create_item_failure_attempts_total",
        "request_charge_total",
        "request_charge_observations",
        "avg_ru_per_operation",
    ),
}


def _print_final_metric_row(name: str, value: object) -> None:
    print(f"{FINAL_METRIC_INDENT}{_display_metric_name(name)}={value}")


def _emit_final_metrics(metrics: dict) -> None:
    _print_completion_banner()
    printed = set()
    for section_name, field_names in FINAL_METRIC_SECTIONS.items():
        section_values = [(name, metrics[name]) for name in field_names if name in metrics]
        if not section_values:
            continue
        print(f"  {section_name}")
        for name, value in section_values:
            _print_final_metric_row(name, value)
            printed.add(name)

    detail_values = [(name, value) for name, value in metrics.items() if name not in printed]
    if detail_values:
        print("  Details")
        for name, value in detail_values:
            _print_final_metric_row(name, value)
    _write_metrics_csv(metrics)


def _fit_terminal_line(line: str) -> str:
    width = shutil.get_terminal_size(fallback=(120, 20)).columns
    if width <= 0 or len(line) < width:
        return line
    if width <= 3:
        return line[:width]
    return f"{line[:width - 3]}..."


def _fit_terminal_block(block: str) -> str:
    return "\n".join(_fit_terminal_line(line) for line in block.splitlines())


def _clear_previous_live_block(line_count: int) -> str:
    if line_count <= 0:
        return ""
    sequence = "\r\x1b[2K"
    for _ in range(line_count - 1):
        sequence += "\x1b[1A\r\x1b[2K"
    return sequence


def _print_live_line(line: str, last_len: int, *, final: bool = False) -> int:
    line = _fit_terminal_block(line)
    line_count = max(1, line.count("\n") + 1)
    clear_previous = _clear_previous_live_block(last_len)
    if final:
        print(f"{clear_previous}{line}")
    else:
        print(f"{clear_previous}{line}", end="", flush=True)
    return line_count


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    if ratio >= 1:
        return sorted_values[-1]
    index = min(max(math.ceil(len(sorted_values) * ratio) - 1, 0), len(sorted_values) - 1)
    return sorted_values[index]


def _throughput_percentile_summary(values: list[float], prefix: str) -> dict:
    sorted_values = sorted(values)
    return {
        f"{prefix}_p50": f"{_percentile(sorted_values, 0.50):.2f}",
        f"{prefix}_p90": f"{_percentile(sorted_values, 0.90):.2f}",
        f"{prefix}_p99": f"{_percentile(sorted_values, 0.99):.2f}",
        f"{prefix}_max": f"{(max(sorted_values) if sorted_values else 0.0):.2f}",
    }


def _float_throughput_percentile_summary(values: list[float], prefix: str) -> dict:
    return {name: float(value) for name, value in _throughput_percentile_summary(values, prefix).items()}


def _percentile_summary(values: list[float], prefix: str) -> dict:
    sorted_values = sorted(values)
    return {f"{prefix}_{name}": f"{_percentile(sorted_values, ratio):.2f}" for name, ratio in PERCENTILE_RATIOS.items()}


def _completed_docs(metrics: dict) -> int:
    return metrics["success"] + metrics["errors"]


def _record_request_charge(metrics: dict, request_charge: float) -> None:
    if request_charge <= 0:
        return
    metrics["request_charge_total"] += request_charge
    metrics["request_charge_observations"] += 1


def _record_create_item_attempt(metrics: dict) -> None:
    metrics["create_item_attempts"] += 1


def _record_create_item_failure(metrics: dict) -> None:
    metrics["create_item_failure_attempts"] += 1


def _record_partition_key_range_request(metrics: dict, partition_key_range_id: str | None) -> None:
    if not PARTITION_KEY_RANGE_RPS_ENABLED:
        return
    if not partition_key_range_id:
        metrics["partition_key_range_missing_header_count"] += 1
        return
    counts = metrics["partition_key_range_request_counts"]
    counts[partition_key_range_id] = counts.get(partition_key_range_id, 0) + 1


def _record_upload_started(metrics: dict, started_at: float, started_epoch: float) -> None:
    if metrics["started_at"] is None:
        metrics["started_at"] = started_at
        metrics["started_epoch"] = started_epoch
        metrics["throughput_last_sample_at"] = started_at
        metrics["throughput_last_sample_success"] = metrics["success"]
        metrics["partition_key_range_last_sample_counts"] = dict(metrics["partition_key_range_request_counts"])


def _record_upload_finished(metrics: dict, finished_at: float, finished_epoch: float) -> None:
    metrics["finished_at"] = finished_at
    metrics["finished_epoch"] = finished_epoch


def _elapsed_upload_time(metrics: dict, *, live: bool = False) -> float:
    if metrics["started_at"] is None:
        return 0.0

    finished_at = metrics.get("finished_at")
    endpoint = time.perf_counter() if live or finished_at is None else finished_at
    return max(endpoint - metrics["started_at"], 0.000001)


def _after_warmup(metrics: dict, sample_at: float) -> bool:
    started_at = metrics.get("started_at")
    if started_at is None:
        return False
    return sample_at >= started_at + METRICS_WARMUP_SEC


def _record_throughput_sample(metrics: dict, *, now: float | None = None, force: bool = False) -> None:
    if metrics["started_at"] is None:
        return

    now = time.perf_counter() if now is None else now
    successful = metrics["success"]
    partition_key_range_counts = metrics["partition_key_range_request_counts"]
    last_sample_at = metrics.get("throughput_last_sample_at")
    if last_sample_at is None:
        metrics["throughput_last_sample_at"] = now
        metrics["throughput_last_sample_success"] = successful
        metrics["partition_key_range_last_sample_counts"] = dict(partition_key_range_counts)
        return

    if not _after_warmup(metrics, now):
        metrics["throughput_last_sample_at"] = now
        metrics["throughput_last_sample_success"] = successful
        metrics["partition_key_range_last_sample_counts"] = dict(partition_key_range_counts)
        metrics["partition_key_range_requests_per_sec"] = {}
        return

    if not _after_warmup(metrics, last_sample_at):
        metrics["throughput_last_sample_at"] = now
        metrics["throughput_last_sample_success"] = successful
        metrics["partition_key_range_last_sample_counts"] = dict(partition_key_range_counts)
        metrics["partition_key_range_requests_per_sec"] = {}
        return

    elapsed = now - last_sample_at
    if elapsed < METRICS_SAMPLE_INTERVAL_SEC and not force:
        return

    successful_delta = successful - metrics.get("throughput_last_sample_success", successful)
    if elapsed > 0:
        metrics["throughput_docs_per_sec_samples"].append(successful_delta / elapsed)
    if PARTITION_KEY_RANGE_RPS_ENABLED and elapsed > 0:
        last_range_counts = metrics.get("partition_key_range_last_sample_counts", {})
        metrics["partition_key_range_requests_per_sec"] = {
            range_id: (count - last_range_counts.get(range_id, 0)) / elapsed
            for range_id, count in partition_key_range_counts.items()
            if count - last_range_counts.get(range_id, 0) > 0
        }

    metrics["throughput_last_sample_at"] = now
    metrics["throughput_last_sample_success"] = successful
    metrics["partition_key_range_last_sample_counts"] = dict(partition_key_range_counts)


def _record_bulk_sample(
    metrics: dict,
    docs_count: int,
    service_time_ms_samples: list[float],
    finished_at: float,
) -> None:
    metrics["bulk_timing_observations"] += 1
    if not _after_warmup(metrics, finished_at):
        return

    if metrics["bulk_timing_observations"] % METRICS_TIMING_SAMPLE_INTERVAL != 0:
        return

    metrics["bulk_docs_sampled"] += docs_count
    metrics["service_time_ms_samples"].extend(service_time_ms_samples)


def _format_completed(completed: int, total_docs: int | None) -> str:
    if total_docs is None:
        return str(completed)
    return f"{completed}/{total_docs}"


def _samples_or_fallback(samples: list[float], fallback: float) -> list[float]:
    if samples:
        return samples
    if METRICS_WARMUP_SEC > 0:
        return []
    return [fallback] if fallback > 0 else []


def _metric_snapshot(metrics: dict, total_docs: int | None, client_count: int, worker_index: int) -> dict:
    elapsed = _elapsed_upload_time(metrics, live=True)
    completed = _completed_docs(metrics)
    current_throughput = metrics["throughput_docs_per_sec_samples"][-1] if metrics["throughput_docs_per_sec_samples"] else _safe_div(metrics["success"], elapsed)
    throughput_samples = _samples_or_fallback(metrics["throughput_docs_per_sec_samples"], current_throughput)
    avg_ru_per_operation = _safe_div(metrics["request_charge_total"], metrics["request_charge_observations"])
    service_times = sorted(metrics["service_time_ms_samples"])
    throughput_summary = _float_throughput_percentile_summary(throughput_samples, "throughput_docs_per_sec")

    return {
        "client_process_index": worker_index,
        "client_process_count": client_count,
        "started": metrics["started_at"] is not None,
        "started_epoch": metrics["started_epoch"],
        "elapsed_sec": elapsed,
        "completed": completed,
        "total_docs": total_docs,
        "success": metrics["success"],
        "errors": metrics["errors"],
        "throttles": metrics["throttles"],
        "create_item_attempts": metrics["create_item_attempts"],
        "create_item_failure_attempts": metrics["create_item_failure_attempts"],
        "throughput_docs_per_sec_current": current_throughput,
        "throughput_docs_per_sec_per_client_current": _safe_div(current_throughput, max(client_count, 1)),
        **throughput_summary,
        "partition_key_range_requests_per_sec": dict(metrics["partition_key_range_requests_per_sec"]),
        "partition_key_range_missing_header_count": metrics["partition_key_range_missing_header_count"],
        "throughput_sample_count": len(metrics["throughput_docs_per_sec_samples"]),
        "service_time_p50_ms": _percentile(service_times, 0.50),
        "service_time_p99_ms": _percentile(service_times, 0.99),
        "bulks_started": metrics["bulks_started"],
        "bulks_completed": metrics["bulks_completed"],
        "bulk_errors": metrics["bulk_errors"],
        "bulk_size": BULK_SIZE,
        "request_charge_total": metrics["request_charge_total"],
        "request_charge_observations": metrics["request_charge_observations"],
        "avg_ru_per_operation": avg_ru_per_operation,
    }


def _live_line(metrics: dict, total_docs: int | None, client_count: int, worker_index: int) -> str:
    snapshot = _metric_snapshot(metrics, total_docs, client_count, worker_index)
    lines = [
        "section:Progress",
        f"value:elapsed={snapshot['elapsed_sec']:.1f}s",
        f"value:completed={_format_completed(snapshot['completed'], total_docs)}",
        "section:Throughput",
        f"value:current_docs_per_sec={snapshot['throughput_docs_per_sec_current']:.2f}",
        f"value:current_docs_per_sec_per_client={snapshot['throughput_docs_per_sec_per_client_current']:.2f}",
        f"value:p50_docs_per_sec={snapshot['throughput_docs_per_sec_p50']:.2f}",
        f"value:p90_docs_per_sec={snapshot['throughput_docs_per_sec_p90']:.2f}",
        f"value:p99_docs_per_sec={snapshot['throughput_docs_per_sec_p99']:.2f}",
        f"value:max_docs_per_sec={snapshot['throughput_docs_per_sec_max']:.2f}",
    ]
    if PARTITION_KEY_RANGE_RPS_ENABLED:
        lines.append("section:Partition key range stats")
        if snapshot["partition_key_range_requests_per_sec"]:
            for range_id, requests_per_sec in sorted(snapshot["partition_key_range_requests_per_sec"].items(), key=lambda item: item[0]):
                lines.append(f"value:pkrange_{range_id}=ops_per_sec={requests_per_sec:.2f}")
        else:
            lines.append("value:observed_ranges=0")
        lines.append(f"value:missing_header_count={snapshot['partition_key_range_missing_header_count']}")
    lines.extend(
        [
            "section:Timing",
            f"value:service_p50_ms={snapshot['service_time_p50_ms']:.2f}",
            f"value:service_p99_ms={snapshot['service_time_p99_ms']:.2f}",
            "section:Responses",
            f"value:success={snapshot['success']}, errors={snapshot['errors']}, throttles={snapshot['throttles']}",
            f"value:avg_ru_per_operation={snapshot['avg_ru_per_operation']:.2f}",
        ]
    )
    return _format_terminal_metrics(f"clients_active=1/{client_count}", lines)


def _result_snapshot(metrics: dict, total_docs: int | None, client_count: int, worker_index: int) -> dict:
    _record_throughput_sample(metrics, force=True)
    insert_time_sec = _elapsed_upload_time(metrics)
    total_finished_at = time.perf_counter()
    total_elapsed_time_sec = max(total_finished_at - metrics["total_started_at"], 0.000001)
    completed = _completed_docs(metrics)
    fallback_throughput = _safe_div(metrics["success"], insert_time_sec)
    throughput_samples = _samples_or_fallback(metrics["throughput_docs_per_sec_samples"], fallback_throughput)
    avg_ru_per_operation = _safe_div(metrics["request_charge_total"], metrics["request_charge_observations"])

    return {
        "client_process_index": worker_index,
        "client_process_count": client_count,
        "started": metrics["started_at"] is not None,
        "started_epoch": metrics["started_epoch"],
        "finished_epoch": metrics["finished_epoch"],
        "total_elapsed_time_sec": total_elapsed_time_sec,
        "insert_time_sec": insert_time_sec,
        "data_load_time_sec": 0.0,
        "other_overhead_sec": total_elapsed_time_sec - insert_time_sec,
        "total_docs": total_docs,
        "docs_completed": completed,
        "success": metrics["success"],
        "errors": metrics["errors"],
        "throttles": metrics["throttles"],
        "create_item_attempts": metrics["create_item_attempts"],
        "create_item_failure_attempts": metrics["create_item_failure_attempts"],
        "throughput_docs_per_sec_samples": throughput_samples,
        "service_time_ms_samples": list(metrics["service_time_ms_samples"]),
        "throughput_sample_count": len(throughput_samples),
        "timing_sample_count": len(metrics["service_time_ms_samples"]),
        "bulk_size": BULK_SIZE,
        "bulks_started": metrics["bulks_started"],
        "bulks_completed": metrics["bulks_completed"],
        "bulk_success": metrics["bulk_success"],
        "bulk_errors": metrics["bulk_errors"],
        "bulk_docs_attempted": metrics["bulk_docs_attempted"],
        "bulk_docs_sampled": metrics["bulk_docs_sampled"],
        "bulk_timing_observations": metrics["bulk_timing_observations"],
        "max_pending_bulks": MAX_PENDING_BULKS,
        "max_in_flight": MAX_IN_FLIGHT,
        "payload_bytes": PAYLOAD_BYTES,
        "request_charge_total": metrics["request_charge_total"],
        "request_charge_observations": metrics["request_charge_observations"],
        "avg_ru_per_operation": avg_ru_per_operation,
    }


def _common_final_metrics(result: dict) -> dict:
    metrics = {
        "total_elapsed_time_sec": f"{result['total_elapsed_time_sec']:.2f}",
        "insert_time_sec": f"{result['insert_time_sec']:.2f}",
        "data_load_time_sec": f"{result['data_load_time_sec']:.2f}",
        "other_overhead_sec": f"{result['other_overhead_sec']:.2f}",
        "metrics_sample_interval_sec": f"{METRICS_SAMPLE_INTERVAL_SEC:.2f}",
        "metrics_timing_sample_interval": METRICS_TIMING_SAMPLE_INTERVAL,
        "capture_ru_charges": str(CAPTURE_RU_CHARGES).lower(),
        "docs_completed": result["docs_completed"],
        "success": result["success"],
        "errors": result["errors"],
        "throttles": result["throttles"],
        "create_item_attempts": result["create_item_attempts"],
        "create_item_failure_attempts": result["create_item_failure_attempts"],
        "throughput_sample_count": result["throughput_sample_count"],
        "timing_sample_count": result["timing_sample_count"],
    }
    current_throughput = result["throughput_docs_per_sec_samples"][-1] if result["throughput_docs_per_sec_samples"] else 0.0
    metrics.update(
        {
            "throughput_docs_per_sec_current": f"{current_throughput:.2f}",
            "throughput_docs_per_sec_per_client_current": f"{_safe_div(current_throughput, max(result['client_process_count'], 1)):.2f}",
        }
    )
    metrics.update(_throughput_percentile_summary(result["throughput_docs_per_sec_samples"], "throughput_docs_per_sec"))
    metrics.update(_percentile_summary(result["service_time_ms_samples"], "service_time_ms"))
    return metrics


def _print_result(result: dict) -> None:
    metrics = _common_final_metrics(result)
    metrics.update(
        {
            "bulk_size": result["bulk_size"],
            "bulks_started": result["bulks_started"],
            "bulks_completed": result["bulks_completed"],
            "bulk_success": result["bulk_success"],
            "bulk_errors": result["bulk_errors"],
            "bulk_docs_attempted": result["bulk_docs_attempted"],
            "bulk_docs_sampled": result["bulk_docs_sampled"],
            "max_pending_bulks": result["max_pending_bulks"],
            "max_in_flight": result["max_in_flight"],
            "payload_bytes": result["payload_bytes"],
            "request_charge_total": f"{result['request_charge_total']:.2f}",
            "request_charge_observations": result["request_charge_observations"],
            "avg_ru_per_operation": f"{result['avg_ru_per_operation']:.2f}",
        }
    )
    _emit_final_metrics(metrics)


def _new_metrics() -> dict:
    return {
        "total_started_at": time.perf_counter(),
        "success": 0,
        "errors": 0,
        "throttles": 0,
        "create_item_attempts": 0,
        "create_item_failure_attempts": 0,
        "started_at": None,
        "started_epoch": None,
        "finished_at": None,
        "finished_epoch": None,
        "throughput_last_sample_at": None,
        "throughput_last_sample_success": 0,
        "throughput_docs_per_sec_samples": [],
        "partition_key_range_request_counts": {},
        "partition_key_range_last_sample_counts": {},
        "partition_key_range_requests_per_sec": {},
        "partition_key_range_missing_header_count": 0,
        "service_time_ms_samples": [],
        "bulk_timing_observations": 0,
        "bulk_docs_sampled": 0,
        "bulks_started": 0,
        "bulks_completed": 0,
        "bulk_success": 0,
        "bulk_errors": 0,
        "bulk_docs_attempted": 0,
        "cosmos_error_samples_logged": 0,
        "request_charge_total": 0.0,
        "request_charge_observations": 0,
    }


def _aggregate_elapsed(latest_metrics: dict[int, dict]) -> float:
    started_epochs = [metric["started_epoch"] for metric in latest_metrics.values() if metric.get("started_epoch")]
    if not started_epochs:
        return 0.0
    return max(time.time() - min(started_epochs), 0.000001)


def _result_elapsed(results: dict[int, dict]) -> float:
    started_epochs = [result["started_epoch"] for result in results.values() if result.get("started_epoch")]
    finished_epochs = [result["finished_epoch"] for result in results.values() if result.get("finished_epoch")]
    if not started_epochs or not finished_epochs:
        return 0.0
    return max(max(finished_epochs) - min(started_epochs), 0.000001)


def _aggregate_line(
    latest_metrics: dict[int, dict],
    total_docs: int | None,
    client_processes: int,
    aggregate_throughput_samples: list[float] | None = None,
) -> str:
    elapsed = _aggregate_elapsed(latest_metrics)
    active_clients = len(latest_metrics)
    success_total = sum(metric["success"] for metric in latest_metrics.values())
    errors_total = sum(metric["errors"] for metric in latest_metrics.values())
    throttles_total = sum(metric["throttles"] for metric in latest_metrics.values())
    completed_total = success_total + errors_total
    create_item_attempts = sum(metric.get("create_item_attempts", 0) for metric in latest_metrics.values())
    throughput_current = sum(metric.get("throughput_docs_per_sec_current", 0.0) for metric in latest_metrics.values())
    if aggregate_throughput_samples is not None and any(metric.get("started") for metric in latest_metrics.values()):
        aggregate_throughput_samples.append(throughput_current)
    throughput_summary = _float_throughput_percentile_summary(aggregate_throughput_samples or [], "throughput_docs_per_sec")
    partition_key_range_requests_per_sec = {}
    partition_key_range_missing_header_count = 0
    if PARTITION_KEY_RANGE_RPS_ENABLED:
        for metric in latest_metrics.values():
            partition_key_range_missing_header_count += metric.get("partition_key_range_missing_header_count", 0)
            for range_id, requests_per_sec in metric.get("partition_key_range_requests_per_sec", {}).items():
                partition_key_range_requests_per_sec[range_id] = partition_key_range_requests_per_sec.get(range_id, 0.0) + requests_per_sec
    request_charge_total = sum(metric.get("request_charge_total", 0.0) for metric in latest_metrics.values())
    request_charge_observations = sum(metric.get("request_charge_observations", 0) for metric in latest_metrics.values())
    avg_ru_per_operation = _safe_div(request_charge_total, request_charge_observations)
    service_p50 = max((metric.get("service_time_p50_ms", 0.0) for metric in latest_metrics.values()), default=0.0)
    service_p99 = max((metric.get("service_time_p99_ms", 0.0) for metric in latest_metrics.values()), default=0.0)
    throughput_samples = sum(metric.get("throughput_sample_count", 0) for metric in latest_metrics.values())

    lines = [
        "section:Progress",
        f"value:elapsed={elapsed:.1f}s",
        f"value:clients_active={active_clients}/{client_processes}",
        f"value:completed={_format_completed(completed_total, total_docs)}",
        "section:Throughput",
        f"value:current_docs_per_sec_total={throughput_current:.2f}",
        f"value:current_docs_per_sec_per_client={_safe_div(throughput_current, max(client_processes, 1)):.2f}",
        f"value:p50_docs_per_sec_total={throughput_summary['throughput_docs_per_sec_p50']:.2f}",
        f"value:p90_docs_per_sec_total={throughput_summary['throughput_docs_per_sec_p90']:.2f}",
        f"value:p99_docs_per_sec_total={throughput_summary['throughput_docs_per_sec_p99']:.2f}",
        f"value:max_docs_per_sec_total={throughput_summary['throughput_docs_per_sec_max']:.2f}",
    ]
    if PARTITION_KEY_RANGE_RPS_ENABLED:
        lines.append("section:Partition key range stats")
        if partition_key_range_requests_per_sec:
            for range_id, requests_per_sec in sorted(partition_key_range_requests_per_sec.items(), key=lambda item: item[0]):
                lines.append(f"value:pkrange_{range_id}=ops_per_sec={requests_per_sec:.2f}")
        else:
            lines.append("value:observed_ranges=0")
        lines.append(f"value:missing_header_count={partition_key_range_missing_header_count}")
    lines.extend(
        [
            "section:Timing",
            f"value:service_p50_ms={service_p50:.2f}",
            f"value:service_p99_ms={service_p99:.2f}",
            "section:Responses",
            f"value:success={success_total}, errors={errors_total}, throttles={throttles_total}",
            f"value:avg_ru_per_operation={avg_ru_per_operation:.2f}",
        ]
    )

    return _format_terminal_metrics(f"clients_active={active_clients}/{client_processes}", lines)


def _aggregate_throughput_samples(results: dict[int, dict]) -> list[float]:
    sample_lists = [result.get("throughput_docs_per_sec_samples", []) for result in results.values()]
    aggregate_samples = []
    for sample_group in zip_longest(*sample_lists, fillvalue=None):
        values = [value for value in sample_group if value is not None]
        if values:
            aggregate_samples.append(sum(values))
    return aggregate_samples


def _print_parent_result(
    results: dict[int, dict],
    extra: dict | None = None,
    *,
    total_elapsed_time_sec: float | None = None,
    data_load_time_sec: float = 0.0,
) -> None:
    success_total = sum(result["success"] for result in results.values())
    errors_total = sum(result["errors"] for result in results.values())
    docs_completed = success_total + errors_total
    throttles_total = sum(result["throttles"] for result in results.values())
    create_item_attempts = sum(result.get("create_item_attempts", 0) for result in results.values())
    create_item_failure_attempts = sum(result.get("create_item_failure_attempts", 0) for result in results.values())
    insert_time_sec = _result_elapsed(results)
    total_elapsed_time_sec = total_elapsed_time_sec if total_elapsed_time_sec is not None else insert_time_sec
    other_overhead_sec = total_elapsed_time_sec - insert_time_sec - data_load_time_sec
    completed_clients = len(results)
    fallback_throughput = _safe_div(success_total, insert_time_sec)
    throughput_samples = _samples_or_fallback(_aggregate_throughput_samples(results), fallback_throughput)
    service_times = [value for result in results.values() for value in result.get("service_time_ms_samples", [])]
    request_charge_total = sum(result.get("request_charge_total", 0.0) for result in results.values())
    request_charge_observations = sum(result.get("request_charge_observations", 0) for result in results.values())
    bulks_started = sum(result.get("bulks_started", 0) for result in results.values())
    bulks_completed = sum(result.get("bulks_completed", 0) for result in results.values())
    bulk_success = sum(result.get("bulk_success", 0) for result in results.values())
    bulk_errors = sum(result.get("bulk_errors", 0) for result in results.values())
    bulk_docs_attempted = sum(result.get("bulk_docs_attempted", 0) for result in results.values())
    bulk_docs_sampled = sum(result.get("bulk_docs_sampled", 0) for result in results.values())
    timing_sample_count = sum(result.get("timing_sample_count", 0) for result in results.values())

    metrics = {
        "total_elapsed_time_sec": f"{total_elapsed_time_sec:.2f}",
        "insert_time_sec": f"{insert_time_sec:.2f}",
        "data_load_time_sec": f"{data_load_time_sec:.2f}",
        "other_overhead_sec": f"{other_overhead_sec:.2f}",
        "metrics_sample_interval_sec": f"{METRICS_SAMPLE_INTERVAL_SEC:.2f}",
        "metrics_timing_sample_interval": METRICS_TIMING_SAMPLE_INTERVAL,
        "capture_ru_charges": str(CAPTURE_RU_CHARGES).lower(),
        "clients": CLIENT_PROCESSES,
        "clients_completed": completed_clients,
        "docs_completed": docs_completed,
        "success_total": success_total,
        "errors_total": errors_total,
        "throttles_total": throttles_total,
        "create_item_attempts_total": create_item_attempts,
        "create_item_failure_attempts_total": create_item_failure_attempts,
        "throughput_sample_count": len(throughput_samples),
        "timing_sample_count": timing_sample_count,
    }
    current_throughput = throughput_samples[-1] if throughput_samples else 0.0
    metrics.update(
        {
            "throughput_docs_per_sec_current": f"{current_throughput:.2f}",
            "throughput_docs_per_sec_per_client_current": f"{_safe_div(current_throughput, max(CLIENT_PROCESSES, 1)):.2f}",
        }
    )
    metrics.update(_throughput_percentile_summary(throughput_samples, "throughput_docs_per_sec"))
    metrics.update(_percentile_summary(service_times, "service_time_ms"))
    metrics.update(
        {
            "bulk_size": BULK_SIZE,
            "bulks_started": bulks_started,
            "bulks_completed": bulks_completed,
            "bulk_success": bulk_success,
            "bulk_errors": bulk_errors,
            "bulk_docs_attempted": bulk_docs_attempted,
            "bulk_docs_sampled": bulk_docs_sampled,
            "max_pending_bulks_per_client": MAX_PENDING_BULKS,
            "max_in_flight_per_client": MAX_IN_FLIGHT,
            "max_in_flight_total": MAX_IN_FLIGHT * CLIENT_PROCESSES,
            "payload_bytes": PAYLOAD_BYTES,
            "request_charge_total": f"{request_charge_total:.2f}",
            "request_charge_observations": request_charge_observations,
            "avg_ru_per_operation": f"{_safe_div(request_charge_total, request_charge_observations):.2f}",
        }
    )
    if extra:
        metrics.update(extra)

    _emit_final_metrics(metrics)
