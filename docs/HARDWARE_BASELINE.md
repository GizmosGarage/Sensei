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

## Reproduce the inventory

Future automation should capture at least:

- CPU name, physical cores, and logical processors
- GPU name and dedicated memory
- total system memory
- operating system and architecture
- free storage
- inference runtime and graphics-driver versions

Runtime versions will be added once candidates are installed.
