#!/usr/bin/env python3
"""Run reproducible performance and calculus-tutoring benchmarks locally."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "config" / "model_candidates.json"
DEFAULT_CASES = REPOSITORY_ROOT / "config" / "benchmark_cases.json"
DEFAULT_MODELS = REPOSITORY_ROOT / "models"
DEFAULT_RUNTIME = REPOSITORY_ROOT / ".local" / "llama.cpp" / "b10549"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "benchmarks" / "results" / "baseline-2026-08-21.json"
DEFAULT_RAW_ROOT = REPOSITORY_ROOT / "benchmarks" / "raw"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str) -> str:
    value = value.lower().replace("\\", "")
    return re.sub(r"\s+", " ", value).strip()


def contains_normalized(content: str, value: str) -> bool:
    normalized_content = normalize_text(content)
    normalized_value = normalize_text(value)
    return normalized_value in normalized_content or normalized_value.replace(
        " ", ""
    ) in normalized_content.replace(" ", "")


def parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1)
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Structured response is not a JSON object.")
    return parsed


def evaluate_check(check: dict[str, Any], content: str) -> tuple[bool, str]:
    check_type = check["type"]
    if check_type == "contains_any":
        passed = any(contains_normalized(content, value) for value in check["values"])
        return passed, "matched an accepted value" if passed else "no accepted value found"
    if check_type == "contains_all":
        missing = [value for value in check["values"] if not contains_normalized(content, value)]
        return not missing, "all values found" if not missing else f"missing: {missing}"
    if check_type == "excludes_all":
        found = [value for value in check["values"] if contains_normalized(content, value)]
        return not found, "excluded values absent" if not found else f"found: {found}"
    if check_type == "json_exact_fields":
        try:
            parsed = parse_json_object(content)
        except (ValueError, json.JSONDecodeError) as error:
            return False, f"invalid JSON object: {error}"
        required = set(check["required_fields"])
        actual = set(parsed)
        if actual != required:
            return False, f"fields differ: expected {sorted(required)}, received {sorted(actual)}"
        mismatches = {
            key: {"expected": expected, "actual": parsed.get(key)}
            for key, expected in check.get("expected_values", {}).items()
            if parsed.get(key) != expected
        }
        return not mismatches, "valid exact JSON" if not mismatches else f"mismatches: {mismatches}"
    raise ValueError(f"Unknown check type: {check_type}")


def evaluate_case(case: dict[str, Any], content: str) -> dict[str, Any]:
    checks = []
    earned = 0
    possible = 0
    for check in case["checks"]:
        points = int(check["points"])
        passed, detail = evaluate_check(check, content)
        possible += points
        if passed:
            earned += points
        checks.append(
            {
                "id": check["id"],
                "description": check["description"],
                "passed": passed,
                "points_earned": points if passed else 0,
                "points_possible": points,
                "detail": detail,
            }
        )
    return {
        "points_earned": earned,
        "points_possible": possible,
        "score": earned / possible if possible else 0,
        "checks": checks,
    }


def extract_json_lines(output: str) -> list[dict[str, Any]]:
    records = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            records.append(json.loads(line))
    return records


def run_performance_benchmark(
    bench_path: Path,
    model_path: Path,
    raw_directory: Path,
) -> list[dict[str, Any]]:
    command = [
        str(bench_path),
        "--model",
        str(model_path),
        "--n-prompt",
        "512",
        "--n-gen",
        "128",
        "--repetitions",
        "3",
        "--output",
        "jsonl",
        "--fit-target",
        "512",
        "--fit-ctx",
        "4096",
        "--threads",
        "8",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
    (raw_directory / f"{model_path.stem}-performance.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    (raw_directory / f"{model_path.stem}-performance.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"llama-bench failed for {model_path.name} with code {completed.returncode}."
        )
    records = extract_json_lines(completed.stdout)
    if len(records) != 2:
        raise RuntimeError(
            f"Expected two llama-bench records for {model_path.name}; received {len(records)}."
        )
    for record in records:
        record["model_filename"] = model_path.name
    return records


def free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_server(process: subprocess.Popen[Any], port: int, timeout: int = 240) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited during startup with code {process.returncode}.")
        try:
            health = request_json(health_url, timeout=5)
            if health.get("status") == "ok":
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise TimeoutError("Timed out waiting for llama-server to become healthy.")


@contextmanager
def local_server(
    server_path: Path,
    model_path: Path,
    alias: str,
    raw_log_path: Path,
) -> Iterator[int]:
    port = free_local_port()
    command = [
        str(server_path),
        "--model",
        str(model_path),
        "--alias",
        alias,
        "--ctx-size",
        "4096",
        "--n-gpu-layers",
        "auto",
        "--fit",
        "on",
        "--fit-target",
        "512",
        "--fit-ctx",
        "4096",
        "--threads",
        "8",
        "--parallel",
        "1",
        "--reasoning",
        "off",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-webui",
    ]
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with raw_log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        try:
            wait_for_server(process, port)
            yield port
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def run_quality_benchmark(
    server_path: Path,
    model_path: Path,
    model_id: str,
    cases_document: dict[str, Any],
    raw_directory: Path,
) -> list[dict[str, Any]]:
    results = []
    server_log = raw_directory / f"{model_path.stem}-server.log"
    with local_server(server_path, model_path, model_id, server_log) as port:
        endpoint = f"http://127.0.0.1:{port}/v1/chat/completions"
        for case in cases_document["cases"]:
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": cases_document["system_prompt"]},
                    {"role": "user", "content": case["prompt"]},
                ],
                "temperature": 0,
                "top_p": 1,
                "seed": 42,
                "max_tokens": 512,
                "stream": False,
            }
            started = time.perf_counter()
            response = request_json(endpoint, payload)
            elapsed = time.perf_counter() - started
            choice_record = response["choices"][0]
            choice = choice_record["message"]
            content = choice.get("content") or ""
            evaluation = evaluate_case(case, content)
            response_completed = choice_record.get("finish_reason") == "stop"
            if not response_completed:
                evaluation["points_earned_before_completion_gate"] = evaluation[
                    "points_earned"
                ]
                evaluation["points_earned"] = 0
                evaluation["score"] = 0
                evaluation["completion_gate"] = (
                    "failed: response did not finish with stop"
                )
            else:
                evaluation["completion_gate"] = "passed"
            raw_response_path = raw_directory / f"{model_id}-{case['id']}.json"
            raw_response_path.write_text(
                json.dumps(response, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            results.append(
                {
                    "case_id": case["id"],
                    "category": case["category"],
                    "content": content,
                    "elapsed_seconds": elapsed,
                    "usage": response.get("usage"),
                    "timings": response.get("timings"),
                    "evaluation": evaluation,
                }
            )
    return results


def summarize_model(
    performance: list[dict[str, Any]], quality: list[dict[str, Any]]
) -> dict[str, Any]:
    prompt_record = next(record for record in performance if record["n_prompt"] > 0)
    generation_record = next(record for record in performance if record["n_gen"] > 0)
    earned = sum(result["evaluation"]["points_earned"] for result in quality)
    possible = sum(result["evaluation"]["points_possible"] for result in quality)
    return {
        "prompt_tokens_per_second": prompt_record["avg_ts"],
        "generation_tokens_per_second": generation_record["avg_ts"],
        "quality_points_earned": earned,
        "quality_points_possible": possible,
        "quality_score": earned / possible if possible else 0,
        "average_case_seconds": sum(result["elapsed_seconds"] for result in quality)
        / len(quality),
        "gpu_layers": generation_record["n_gpu_layers"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--model",
        action="append",
        dest="model_ids",
        help="Candidate ID to benchmark; repeat for multiple models (default: all).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_json(args.manifest.resolve())
    cases_document = load_json(args.cases.resolve())
    candidates = {candidate["id"]: candidate for candidate in manifest["models"]}
    selected_ids = args.model_ids or list(candidates)
    unknown = [model_id for model_id in selected_ids if model_id not in candidates]
    if unknown:
        print(f"Unknown model IDs: {', '.join(unknown)}", file=sys.stderr)
        return 2

    runtime_directory = args.runtime_dir.resolve()
    bench_path = runtime_directory / "llama-bench.exe"
    server_path = runtime_directory / "llama-server.exe"
    for executable in (bench_path, server_path):
        if not executable.is_file():
            raise FileNotFoundError(f"Required runtime executable is missing: {executable}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_directory = args.raw_root.resolve() / run_id
    raw_directory.mkdir(parents=True, exist_ok=False)
    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "name": "llama.cpp",
            "build": "b10549",
            "backend": "Vulkan",
        },
        "benchmark_config": {
            "context_size": 4096,
            "fit_target_mib": 512,
            "threads": 8,
            "prompt_tokens": 512,
            "generated_tokens": 128,
            "performance_repetitions": 3,
            "quality_temperature": 0,
            "quality_seed": 42,
            "quality_max_tokens": 512,
            "reasoning_mode": "off",
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "models": [],
    }

    for model_id in selected_ids:
        candidate = candidates[model_id]
        model_path = args.models_dir.resolve() / candidate["filename"]
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Model is missing: {model_path}. Run scripts/download_models.py first."
            )
        print(f"Benchmarking performance: {model_id}", flush=True)
        performance = run_performance_benchmark(bench_path, model_path, raw_directory)
        print(f"Benchmarking tutoring quality: {model_id}", flush=True)
        quality = run_quality_benchmark(
            server_path, model_path, model_id, cases_document, raw_directory
        )
        summary = summarize_model(performance, quality)
        result["models"].append(
            {
                "id": model_id,
                "vendor": candidate["vendor"],
                "filename": candidate["filename"],
                "revision": candidate["revision"],
                "quantization": candidate["quantization"],
                "license": candidate["license"],
                "size_bytes": candidate["size_bytes"],
                "performance": performance,
                "quality_cases": quality,
                "summary": summary,
            }
        )
        print(
            f"  quality={summary['quality_points_earned']}/"
            f"{summary['quality_points_possible']}, "
            f"generation={summary['generation_tokens_per_second']:.1f} tok/s",
            flush=True,
        )
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"Results written to {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
