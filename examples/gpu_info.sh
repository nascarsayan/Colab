#!/usr/bin/env bash
# Colab run examples/gpu_info.sh -- hello
set -euo pipefail
printf 'Bash on Colab: %s\n' "$(uname -s)"
printf 'Working directory: %s\n' "$PWD"
printf 'Argument: %s\n' "${1:-none}"
printf '\nGPU:\n'
nvidia-smi --query-gpu=name,memory.total,utilization.gpu --format=csv
printf '\nCUDA compiler:\n'
nvcc --version
printf 'Bash diagnostic on stderr\n' >&2
