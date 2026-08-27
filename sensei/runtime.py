"""Lifecycle management for the bundled local llama.cpp server."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DIRECTORY = REPOSITORY_ROOT / ".local" / "llama.cpp" / "b10549"
DEFAULT_LOG_PATH = REPOSITORY_ROOT / "data" / "runtime" / "llama-server.log"
WINDOWS_APPLICATION_CONTROL_BLOCKED = 0xC0E90002


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass(frozen=True)
class RuntimeSettings:
    executable: Path
    model_path: Path
    model_alias: str
    log_path: Path = DEFAULT_LOG_PATH
    context_size: int = 4096
    fit_target_mib: int = 512
    threads: int = 8
    startup_timeout_seconds: int = 240


class LocalLlamaRuntime:
    """Starts one loopback-only llama.cpp server and reliably stops it."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.process: subprocess.Popen[str] | None = None
        self.port: int | None = None
        self._log = None

    @property
    def base_url(self) -> str:
        if self.port is None:
            raise RuntimeError("The local runtime has not been started.")
        return f"http://127.0.0.1:{self.port}"

    def command(self, port: int) -> list[str]:
        settings = self.settings
        return [
            str(settings.executable),
            "--model",
            str(settings.model_path),
            "--alias",
            settings.model_alias,
            "--ctx-size",
            str(settings.context_size),
            "--n-gpu-layers",
            "auto",
            "--fit",
            "on",
            "--fit-target",
            str(settings.fit_target_mib),
            "--fit-ctx",
            str(settings.context_size),
            "--threads",
            str(settings.threads),
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

    def __enter__(self) -> "LocalLlamaRuntime":
        settings = self.settings
        if not settings.executable.is_file():
            raise FileNotFoundError(
                f"llama-server is missing: {settings.executable}. "
                "Follow docs/LOCAL_INFERENCE_SETUP.md."
            )
        if not settings.model_path.is_file():
            raise FileNotFoundError(
                f"Model is missing: {settings.model_path}. "
                "Run scripts/download_models.py for the selected model."
            )
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = settings.log_path.open("w", encoding="utf-8")
        self.port = reserve_local_port()
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            self.command(self.port),
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        try:
            self._wait_until_healthy()
        except Exception:
            self.stop()
            raise
        return self

    def _wait_until_healthy(self) -> None:
        if self.process is None:
            raise RuntimeError("The server process has not been created.")
        deadline = time.monotonic() + self.settings.startup_timeout_seconds
        url = f"{self.base_url}/health"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return_code = int(self.process.returncode or 0)
                if (
                    os.name == "nt"
                    and return_code & 0xFFFFFFFF
                    == WINDOWS_APPLICATION_CONTROL_BLOCKED
                ):
                    raise RuntimeError(
                        "Windows Application Control blocked llama-server.exe. "
                        "Have a trusted administrator allow the pinned local runtime, "
                        "or start an approved llama.cpp server and pass --server-url."
                    )
                raise RuntimeError(
                    f"llama-server exited during startup with code "
                    f"{return_code}. See {self.settings.log_path}."
                )
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    status = json.loads(response.read().decode("utf-8"))
                    if status.get("status") == "ok":
                        return
            except (
                OSError,
                urllib.error.URLError,
                json.JSONDecodeError,
            ):
                pass
            time.sleep(0.5)
        raise TimeoutError(
            f"llama-server did not become ready within "
            f"{self.settings.startup_timeout_seconds} seconds. "
            f"See {self.settings.log_path}."
        )

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        self.process = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
