#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export VLLM_PLUGINS="${VLLM_PLUGINS:-}"
export VLLM_USE_V2_MODEL_RUNNER="${VLLM_USE_V2_MODEL_RUNNER:-0}"
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
export HF_HOME="${HF_HOME:-/var/tmp/huggingface}"

CONFIG_JSON="$(python - <<'PY'
from agent.runtime.local_llm import load_local_llm_config
import json

print(json.dumps(load_local_llm_config().__dict__))
PY
)"

export LOCAL_LLM_BASE_URL="$(python -c "import json,sys; print(json.loads(sys.argv[1])['base_url'])" "$CONFIG_JSON")"
export LOCAL_LLM_API_KEY="${LOCAL_LLM_API_KEY:-$(python -c "import json,sys; print(json.loads(sys.argv[1])['api_key'])" "$CONFIG_JSON")}"
export LOCAL_LLM_MODEL="$(python -c "import json,sys; print(json.loads(sys.argv[1])['model'])" "$CONFIG_JSON")"
export LOCAL_LLM_TIMEOUT_SECONDS="$(python -c "import json,sys; print(json.loads(sys.argv[1])['timeout_seconds'])" "$CONFIG_JSON")"
export LOCAL_LLM_MAX_TOKENS="${LOCAL_LLM_MAX_TOKENS:-$(python -c "import json,sys; print(json.loads(sys.argv[1])['max_tokens'])" "$CONFIG_JSON")}"
export LOCAL_LLM_TEMPERATURE="${LOCAL_LLM_TEMPERATURE:-$(python -c "import json,sys; print(json.loads(sys.argv[1])['temperature'])" "$CONFIG_JSON")}"

HOST_AND_PATH="${LOCAL_LLM_BASE_URL#http://}"
HOST_AND_PATH="${HOST_AND_PATH#https://}"
HOST="${HOST_AND_PATH%%/*}"
PORT="${HOST##*:}"
HOST="${HOST%:*}"

if [[ "$HOST" == "$PORT" ]]; then
  HOST="127.0.0.1"
  PORT="8010"
fi

export VLLM_HOST="${VLLM_HOST:-$HOST}"
export VLLM_PORT="${VLLM_PORT:-$PORT}"
export VLLM_SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-$LOCAL_LLM_MODEL}"
export VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"
export VLLM_MAX_NUM_SEQS="${VLLM_MAX_NUM_SEQS:-4}"
export VLLM_MODEL_SOURCE="${VLLM_MODEL_SOURCE:-Qwen/Qwen2.5-Coder-7B-Instruct-AWQ}"

mkdir -p "$HF_HOME"

echo "[vLLM] Qwen runtime configuration"
echo "  model_source: $VLLM_MODEL_SOURCE"
echo "  served_model_name: $VLLM_SERVED_MODEL_NAME"
echo "  host: $VLLM_HOST:$VLLM_PORT"
echo "  hf_home: $HF_HOME"
echo "  max_model_len: $VLLM_MAX_MODEL_LEN"
echo "  gpu_memory_utilization: $VLLM_GPU_MEMORY_UTILIZATION"
echo "  max_num_seqs: $VLLM_MAX_NUM_SEQS"
echo "  VLLM_USE_V2_MODEL_RUNNER: $VLLM_USE_V2_MODEL_RUNNER"
echo "  VLLM_USE_FLASHINFER_SAMPLER: $VLLM_USE_FLASHINFER_SAMPLER"

exec vllm serve "$VLLM_MODEL_SOURCE" \
  --host "$VLLM_HOST" \
  --port "$VLLM_PORT" \
  --api-key "$LOCAL_LLM_API_KEY" \
  --served-model-name "$VLLM_SERVED_MODEL_NAME" \
  --max-model-len "$VLLM_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$VLLM_GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$VLLM_MAX_NUM_SEQS"
