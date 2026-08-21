# Local inference setup

This setup runs Sensei entirely on the target Windows computer. Model weights, caches, and raw logs are ignored by Git.

## Prerequisites

Install the Microsoft Visual C++ x64 runtime if it is not already present:

```powershell
winget install --id Microsoft.VCRedist.2015+.x64 --exact
```

A UAC prompt may appear. The portable `llama.cpp` binaries will exit before printing help if the runtime DLLs are missing.

## Runtime

The benchmark used the official `llama.cpp` b10549 Windows Vulkan archive:

- Archive: `llama-b10549-bin-win-vulkan-x64.zip`
- SHA-256: `8e7b0e6382a5bcbf57c79cf54b61483e9f7b26561d4413f28095cdaee256207b`
- Release: [llama.cpp b10549](https://github.com/ggml-org/llama.cpp/releases/tag/b10549)

Extract it to `.local/llama.cpp/b10549`, then verify GPU discovery:

```powershell
.\.local\llama.cpp\b10549\llama-cli.exe --list-devices
```

The target output includes `Vulkan0: AMD Radeon RX 5700 XT`.

## Model download

Download and verify the default model from the pinned manifest:

```powershell
python scripts\download_models.py --model qwen-3.5-9b-q4-k-m
```

The downloader uses explicit HTTP range requests, resumes `.part` files, validates each returned byte range, and verifies the final SHA-256 hash before renaming the file.

To download every benchmark candidate:

```powershell
python scripts\download_models.py --all
```

## Start the local server

```powershell
.\.local\llama.cpp\b10549\llama-server.exe `
  --model .\models\Qwen_Qwen3.5-9B-Q4_K_M.gguf `
  --alias sensei-local `
  --ctx-size 4096 `
  --n-gpu-layers auto `
  --fit on `
  --fit-target 512 `
  --fit-ctx 4096 `
  --threads 8 `
  --parallel 1 `
  --reasoning off `
  --host 127.0.0.1 `
  --port 8080 `
  --no-webui
```

The server exposes an OpenAI-compatible API at `http://127.0.0.1:8080/v1`. It is bound only to localhost and does not require hosted inference credits.

## Run Sensei

Sensei can manage the local server lifecycle automatically, so starting a server by hand is optional:

```powershell
python -m sensei
```

Use `python -m sensei --fast` for the 4B fallback. See the [terminal tutor guide](TEXT_TUTOR.md) for commands, one-shot mode, context behavior, and troubleshooting.

## Reproduce the benchmark

After the candidates are present:

```powershell
python scripts\run_model_benchmarks.py
python -m unittest discover -s tests -v
```

The sanitized result is written to `benchmarks/results/baseline-2026-08-21.json`. Timestamped raw logs are written under `benchmarks/raw/` and are intentionally ignored.
