#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x /opt/mirrolla-vllm/.venv/bin/python ]]; then
  echo "Missing vLLM virtualenv: /opt/mirrolla-vllm/.venv" >&2
  exit 1
fi

source /opt/mirrolla-vllm/.venv/bin/activate

export VLLM_PLUGINS=""
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME="${HF_HOME:-/var/tmp/huggingface}"

mkdir -p "$HF_HOME"

echo "[vLLM] Qwen runtime configuration"
echo "  model_source: Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
echo "  served_model_name: ${VLLM_MODEL_NAME:-qwen-coder-local}"
echo "  host: ${VLLM_HOST:-127.0.0.1}:${VLLM_PORT:-8010}"
echo "  hf_home: $HF_HOME"
echo "  max_model_len: ${VLLM_MAX_MODEL_LEN:-8192}"
echo "  gpu_memory_utilization: ${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"
echo "  max_num_seqs: ${VLLM_MAX_NUM_SEQS:-4}"
echo "  VLLM_USE_V2_MODEL_RUNNER: $VLLM_USE_V2_MODEL_RUNNER"
echo "  VLLM_USE_FLASHINFER_SAMPLER: $VLLM_USE_FLASHINFER_SAMPLER"

exec vllm serve "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ" \
  --host "${VLLM_HOST:-127.0.0.1}" \
  --port "${VLLM_PORT:-8010}" \
  --api-key "${VLLM_API_KEY:-mirrolla-local}" \
  --served-model-name "${VLLM_MODEL_NAME:-qwen-coder-local}" \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-8192}" \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.85}" \
  --max-num-seqs "${VLLM_MAX_NUM_SEQS:-4}"
