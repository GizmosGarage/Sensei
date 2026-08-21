#!/usr/bin/env python3
"""Download pinned GGUF candidates with resumable HTTP range requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "config" / "model_candidates.json"
DEFAULT_MODEL_DIRECTORY = REPOSITORY_ROOT / "models"
USER_AGENT = "Sensei-model-downloader/0.1"


def load_candidates(manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported model manifest schema version.")
    return {model["id"]: model for model in manifest["models"]}


def model_url(candidate: dict[str, Any]) -> str:
    repository = candidate["repository"]
    revision = candidate["revision"]
    filename = candidate["filename"]
    return f"https://huggingface.co/{repository}/resolve/{revision}/{filename}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def format_gib(byte_count: int) -> str:
    return f"{byte_count / (1024**3):.2f} GiB"


def download_candidate(
    candidate: dict[str, Any],
    model_directory: Path,
    chunk_bytes: int,
    max_retries: int,
) -> None:
    model_directory.mkdir(parents=True, exist_ok=True)
    final_path = model_directory / candidate["filename"]
    partial_path = final_path.with_name(f"{final_path.name}.part")
    expected_size = int(candidate["size_bytes"])
    expected_hash = candidate["sha256"].lower()

    if final_path.exists():
        if final_path.stat().st_size != expected_size:
            raise RuntimeError(f"Existing file has the wrong size: {final_path}")
        print(f"Verifying existing {candidate['id']} ...", flush=True)
        if sha256_file(final_path) != expected_hash:
            raise RuntimeError(f"Existing file failed SHA-256 verification: {final_path}")
        print(f"Verified {final_path.name}; download skipped.", flush=True)
        return

    if partial_path.exists() and partial_path.stat().st_size > expected_size:
        raise RuntimeError(f"Partial file is larger than expected: {partial_path}")

    source_url = model_url(candidate)
    print(
        f"Downloading {candidate['id']} ({format_gib(expected_size)}) "
        f"to {partial_path.name}",
        flush=True,
    )

    consecutive_failures = 0
    while True:
        current_size = partial_path.stat().st_size if partial_path.exists() else 0
        if current_size == expected_size:
            break

        end_byte = min(current_size + chunk_bytes, expected_size) - 1
        request = urllib.request.Request(
            source_url,
            headers={
                "Accept-Encoding": "identity",
                "Range": f"bytes={current_size}-{end_byte}",
                "User-Agent": USER_AGENT,
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                if response.status != 206:
                    raise RuntimeError(
                        f"Expected HTTP 206 for range request; received {response.status}."
                    )
                content_range = response.headers.get("Content-Range", "")
                expected_range = f"bytes {current_size}-{end_byte}/{expected_size}"
                if content_range != expected_range:
                    raise RuntimeError(
                        f"Unexpected Content-Range {content_range!r}; "
                        f"expected {expected_range!r}."
                    )

                bytes_written = 0
                with partial_path.open("ab") as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        bytes_written += len(block)

                expected_chunk_size = end_byte - current_size + 1
                if bytes_written != expected_chunk_size:
                    raise RuntimeError(
                        f"Range returned {bytes_written} bytes; "
                        f"expected {expected_chunk_size}."
                    )
            consecutive_failures = 0
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            consecutive_failures += 1
            if consecutive_failures > max_retries:
                raise RuntimeError(
                    f"Download failed after {max_retries} retries at byte {current_size}."
                ) from error
            delay = min(2**consecutive_failures, 30)
            print(f"Range failed ({error}); retrying in {delay}s ...", flush=True)
            time.sleep(delay)
            continue

        completed = partial_path.stat().st_size
        percentage = 100 * completed / expected_size
        print(
            f"  {percentage:5.1f}%  {format_gib(completed)} / "
            f"{format_gib(expected_size)}",
            flush=True,
        )

    print(f"Verifying SHA-256 for {partial_path.name} ...", flush=True)
    actual_hash = sha256_file(partial_path)
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"SHA-256 mismatch for {partial_path}: expected {expected_hash}, "
            f"received {actual_hash}."
        )
    os.replace(partial_path, final_path)
    print(f"Ready: {final_path}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the pinned model manifest.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODEL_DIRECTORY,
        help="Directory for ignored local model weights.",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="model_ids",
        help="Candidate ID to download; repeat to select multiple models.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download every candidate in the manifest.",
    )
    parser.add_argument(
        "--chunk-mib",
        type=int,
        default=64,
        help="HTTP range chunk size in MiB (default: 64).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Consecutive retries allowed for a range (default: 5).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates = load_candidates(args.manifest.resolve())
    if args.all == bool(args.model_ids):
        print("Choose either --all or one or more --model values.", file=sys.stderr)
        return 2
    if args.chunk_mib < 1:
        print("--chunk-mib must be positive.", file=sys.stderr)
        return 2

    selected_ids = list(candidates) if args.all else args.model_ids
    unknown = [model_id for model_id in selected_ids if model_id not in candidates]
    if unknown:
        print(f"Unknown model IDs: {', '.join(unknown)}", file=sys.stderr)
        print(f"Available IDs: {', '.join(candidates)}", file=sys.stderr)
        return 2

    model_directory = args.models_dir.resolve()
    chunk_bytes = args.chunk_mib * 1024 * 1024
    for model_id in selected_ids:
        download_candidate(
            candidates[model_id],
            model_directory,
            chunk_bytes,
            args.max_retries,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
