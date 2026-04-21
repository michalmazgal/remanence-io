# Remanence.io

Remanence.io is a high-performance video processing pipeline designed to optimize AV1 encoding by leveraging AV1's native grain synthesis capabilities.

## Core Objective
The goal of the project is to reduce the bitrate and file size of high-grain videos without losing visual quality. Instead of encoding random noise (grain) as complex temporal data, Remanence.io "discovers" the synthetic grain parameters that best match the original video, removes the grain from the source, and encodes the result with instructions for the AV1 decoder to regenerate the grain synthetically.

## Technical Workflow

### 1. Grain Discovery (The "Reverse Engineering" Phase)
The system attempts to find the specific AV1 grain seed that most closely resembles the original video's noise pattern.
- **GPU Acceleration**: Uses NVIDIA Tensor cores on ADA6000/A100/H100 GPUs.
- **Method**: The worker generates a matrix $G$ of candidate synthetic grains (based on the AV1 spec) and computes the correlation $R = G^T V$ against the normalized video frame $V$ using half-precision (FP16) matrix multiplication.
- **Optimization**: By using `cp.dot` (cuBLAS), the system achieves massive throughput, allowing thousands of seed candidates to be tested per frame.

### 2. Grain Subtraction
Once the optimal seed is found:
- A custom CUDA kernel subtracts the synthetic grain from the original frames.
- This results in a "clean" version of the video that is significantly easier for the AV1 encoder to compress (lower entropy).

### 3. AV1 Encoding with Synthesis
The clean video is passed to the `SVT-AV1` encoder with specific parameters:
- `grain-synthesis=1`
- `grain-seed=[discovered_seed]`
The encoder produces a bitstream that is small (because the noise is gone) but instructs the player to add the noise back during playback.

### 4. Automated Infrastructure
- **Orchestrator**: A Python-based control plane that monitors a Cloudflare R2 bucket.
- **Vast.ai Integration**: Automatically rents the cheapest available ECC-enabled GPU (RTX A6000, A100, H100), deploys the specific Docker image for that GPU, and destroys the instance immediately after processing.
- **Cloud Storage**: End-to-end automation from R2 (pending) $\rightarrow$ Vast.ai $\rightarrow$ R2 (processed).

## Benchmarking & Validation
The system includes a built-in benchmark mode that compares the **Optimized Pipeline** against a **Standard AV1 Pipeline** (direct encoding). It measures:
- **Processing Time**: Total seconds to encode.
- **Final File Size**: Bitrate reduction efficiency.
- **Resource Cost**: GPU rental time on Vast.ai.

## Architecture
- **Worker**: CUDA / CuPy / Python / FFmpeg (SVT-AV1).
- **Orchestrator**: Python / Boto3 / Vast.ai CLI.
- **CI/CD**: GitHub Actions pushing GPU-specific images to GHCR.
