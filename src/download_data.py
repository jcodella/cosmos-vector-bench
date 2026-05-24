"""Download the configured corpus file into data/."""

from __future__ import annotations

import argparse
import bz2
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

from dotenv import load_dotenv


DEFAULT_DATA_URL = "https://rally-tracks.elastic.co/openai_vector/open_ai_corpus-initial-indexing.json.bz2"
CHUNK_SIZE = 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def _data_filename(url: str) -> str:
    """Extract the local filename from a download URL.

    The downloader uses this to map `DATA_URL` to a stable file path under `DATA_DIR`.
    URL decoding handles source URLs that include escaped characters in the filename.
    Raising on an empty path avoids writing ambiguous or directory-only download targets.
    """
    path = urlparse(url).path
    name = unquote(Path(path).name)
    if not name:
        raise ValueError(f"Could not determine a file name from DATA_URL={url!r}")
    return name


def _progress(label: str, bytes_done: int, total_bytes: int | None, started_at: float) -> None:
    """Print transfer progress and throughput for downloads or decompression.

    Download and decompression loops call this periodically and at completion.
    It reports MiB processed and MiB/sec, with percentage when the source provides a content length.
    Progress goes to stderr so scripts can still consume normal stdout key-value output if needed.
    """
    elapsed = max(time.perf_counter() - started_at, 0.000001)
    mb_done = bytes_done / (1024 * 1024)
    mb_per_sec = mb_done / elapsed
    if total_bytes:
        percent = bytes_done / total_bytes * 100
        total_mb = total_bytes / (1024 * 1024)
        print(f"{label}: {mb_done:.1f}/{total_mb:.1f} MB {percent:.1f}% {mb_per_sec:.1f} MB/s", file=sys.stderr, flush=True)
    else:
        print(f"{label}: {mb_done:.1f} MB {mb_per_sec:.1f} MB/s", file=sys.stderr, flush=True)


def download_file(url: str, output_path: Path) -> Path:
    """Download a source file to the requested local path.

    This is the main network transfer step used by `src/download_data.py` after loading `.env` configuration.
    It streams the response in fixed-size chunks to avoid holding large corpus files in memory.
    Printing the source URL and target path makes downloaded inputs easy to verify before benchmark runs.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"download_url={url}")
    print(f"download_path={output_path}")

    started_at = time.perf_counter()
    bytes_done = 0
    next_report = CHUNK_SIZE * 25
    with urlopen(url) as response:
        content_length = response.headers.get("Content-Length")
        total_bytes = int(content_length) if content_length else None
        with output_path.open("wb") as target:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                bytes_done += len(chunk)
                if bytes_done >= next_report:
                    _progress("download", bytes_done, total_bytes, started_at)
                    next_report += CHUNK_SIZE * 25

    _progress("download_done", bytes_done, total_bytes, started_at)
    return output_path


def decompress_bz2(input_path: Path) -> Path:
    """Decompress a bz2 file next to the archive when needed.

    The downloader calls this unless `--no-decompress` is provided.
    Non-bz2 inputs are returned unchanged so the caller can treat all data sources uniformly.
    Keeping decompression optional lets scenarios choose between direct compressed streaming and a steadier pre-expanded input file.
    """
    if input_path.suffix.lower() != ".bz2":
        print(f"decompressed_path={input_path}")
        return input_path

    output_path = input_path.with_suffix("")
    print(f"decompress_input={input_path}")
    print(f"decompressed_path={output_path}")
    started_at = time.perf_counter()
    bytes_done = 0
    next_report = CHUNK_SIZE * 100
    with bz2.open(input_path, "rb") as source:
        with output_path.open("wb") as target:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                bytes_done += len(chunk)
                if bytes_done >= next_report:
                    _progress("decompress", bytes_done, None, started_at)
                    next_report += CHUNK_SIZE * 100

    _progress("decompress_done", bytes_done, None, started_at)
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for dataset download and decompression.

    This defines the small CLI surface for the data downloader.
    The mutually exclusive decompression flags make the default behavior explicit while allowing scenarios to keep `.bz2` files compressed.
    Returning an argparse namespace keeps `main` focused on executing the selected behavior.
    """
    parser = argparse.ArgumentParser(description="Download the configured benchmark data file.")
    decompress_group = parser.add_mutually_exclusive_group()
    decompress_group.add_argument(
        "--decompress",
        dest="decompress",
        action="store_true",
        default=True,
        help="Decompress .bz2 files after download. This is the default.",
    )
    decompress_group.add_argument(
        "--no-decompress",
        dest="decompress",
        action="store_false",
        help="Download only and leave .bz2 files compressed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Download the configured dataset and optionally decompress it.

    This is the command entrypoint for `python src/download_data.py`.
    It loads the repo `.env`, resolves the configured URL and data directory, downloads the file, and optionally expands `.bz2` content.
    The final `data_file_path` output tells the user or scripts which local file is ready for benchmark input.
    """
    args = parse_args(argv)
    load_dotenv(ENV_PATH, override=False)
    data_url = os.getenv("DATA_URL", DEFAULT_DATA_URL).strip() or DEFAULT_DATA_URL
    data_dir = Path(os.getenv("DATA_DIR", "data").strip() or "data")
    downloaded_path = data_dir / _data_filename(data_url)

    download_file(data_url, downloaded_path)
    data_file_path = decompress_bz2(downloaded_path) if args.decompress else downloaded_path

    print(f"data_file_path={data_file_path}")


if __name__ == "__main__":
    main()