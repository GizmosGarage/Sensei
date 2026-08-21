# Hardware baseline

Recorded on 2026-08-21 before selecting a local inference runtime or model.

## Target computer

| Component | Baseline |
| --- | --- |
| Operating system | Windows 11 Pro, 64-bit |
| CPU | AMD Ryzen 7 3800XT, 8 cores / 16 logical processors |
| GPU | AMD Radeon RX 5700 XT |
| Dedicated GPU memory | 8 GB |
| System memory | 16 GB |
| Storage | Approximately 1 TB total, 939 GB free at capture time |

The values were collected locally through Windows CIM and registry queries. The registry-reported GPU memory was used because `Win32_VideoController.AdapterRAM` is capped by its data type and reported only about 4 GB.

## Initial implications

- GPU memory is the primary constraint for accelerated inference.
- Quantized 7B-9B-class models are the safest first benchmark tier.
- Selected 12B-14B-class models may be tested with partial CPU offload if latency remains suitable for interactive tutoring.
- Models around 20B parameters or larger are not assumed viable; they must earn inclusion through measured memory use and response time.
- AMD compatibility on Windows must be validated for each inference runtime rather than assumed.
- The large amount of free storage is sufficient for several quantized candidate models, but model weights will remain outside Git.

These are starting hypotheses, not final model requirements. Actual benchmark results will control the decision.

## Validated inference path

The installed AMD driver exposes the RX 5700 XT as a Vulkan 1.4 device. `llama.cpp` b10549 detected 8,176 MiB total device memory and 7,382 MiB free during setup, then fully offloaded every selected Q4 model in the benchmark.

The RX 5700 XT is not listed in AMD's current Windows HIP SDK consumer-GPU compatibility table. ROCm-dependent runtimes were therefore not selected as the reproducible baseline. A Vulkan backend avoids relying on unsupported ROCm hardware while still using the GPU.

Sources:

- [llama.cpp Vulkan build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#vulkan)
- [AMD HIP SDK for Windows system requirements](https://rocm.docs.amd.com/projects/install-on-windows/en/latest/reference/system-requirements.html)

## Reproduce the inventory

Future automation should capture at least:

- CPU name, physical cores, and logical processors
- GPU name and dedicated memory
- total system memory
- operating system and architecture
- free storage
- inference runtime and graphics-driver versions

Pinned runtime and model details are recorded in the [local inference setup](LOCAL_INFERENCE_SETUP.md).
