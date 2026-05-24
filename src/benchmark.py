"""Command entrypoint for the Cosmos DB write benchmark."""

from __future__ import annotations

import asyncio
import multiprocessing as mp

from config import CLIENT_PROCESSES, DATA_TYPE, EFFECTIVE_TOTAL_DOCS
from core import run_json_parent, run_parent, run_worker


def _print_start_spacing() -> None:
    """Print spacing before the benchmark starts writing status output.

    This is called once from the command entrypoint before the warmup line.
    A single leading line break makes live metrics easier to distinguish from the shell prompt and previous commands.
    """
    print("\n", end="", flush=True)


async def main() -> None:
    """Select and run the configured benchmark mode.

    This is the async entrypoint used by `src/benchmark.py` after configuration has been loaded.
    It routes to file-input orchestration, multi-process fake-data orchestration, or a single worker based on the configured data type and client count.
    Keeping the dispatch here makes `main.py` a thin CLI wrapper while the benchmark module owns runtime behavior.
    """
    _print_start_spacing()
    print(f"Warming up {CLIENT_PROCESSES} client connection(s)...", flush=True)
    if DATA_TYPE == "file":
        await run_json_parent()
    elif CLIENT_PROCESSES > 1:
        await run_parent()
    else:
        await run_worker(0, EFFECTIVE_TOTAL_DOCS, 0, 1)


if __name__ == "__main__":
    mp.freeze_support()
    asyncio.run(main())
