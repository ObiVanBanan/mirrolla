#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export PYTHONPATH="${PYTHONPATH:-$ROOT_DIR}"
WSL_LOCAL_CACHE_DIR="${WSL_LOCAL_CACHE_DIR:-/var/tmp/mirrolla-vllm}"

CONFIG_JSON="$(python - <<'PY'
from agent.runtime.gemma_local import GemmaLocalConfigError, build_runtime_config
import json
try:
    print(json.dumps(build_runtime_config().__dict__))
except GemmaLocalConfigError as exc:
    raise SystemExit(str(exc))
PY
)"

export GEMMA_GGUF_FILE="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['gguf_file'])" "$CONFIG_JSON")"
export GEMMA_TOKENIZER_PATH="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['tokenizer_path'])" "$CONFIG_JSON")"
export GEMMA_HF_CONFIG_PATH="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['hf_config_path'])" "$CONFIG_JSON")"
export VLLM_SERVED_MODEL_NAME="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['served_model_name'])" "$CONFIG_JSON")"
export VLLM_HOST="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['host'])" "$CONFIG_JSON")"
export VLLM_PORT="$(python -c "import json; import sys; print(json.loads(sys.argv[1])['port'])" "$CONFIG_JSON")"
export VLLM_API_KEY="${VLLM_API_KEY:-mirrolla-local}"
export VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"

localize_runtime_path() {
  local source_path="$1"
  local target_root="$2"

  if [[ "$source_path" != /mnt/* ]]; then
    printf '%s\n' "$source_path"
    return 0
  fi

  mkdir -p "$target_root"

  if [[ -d "$source_path" ]]; then
    local dir_name
    dir_name="$(basename "$source_path")"
    local target_dir="$target_root/$dir_name"
    mkdir -p "$target_dir"
    cp -a "$source_path"/. "$target_dir"/
    printf '%s\n' "$target_dir"
    return 0
  fi

  local file_name
  file_name="$(basename "$source_path")"
  local target_file="$target_root/$file_name"
  cp -f "$source_path" "$target_file"
  printf '%s\n' "$target_file"
}

if [[ "$(uname -r)" == *WSL* ]]; then
  echo "[vLLM] WSL detected, localizing DrvFS assets into ext4 cache at $WSL_LOCAL_CACHE_DIR"
  GEMMA_GGUF_FILE="$(localize_runtime_path "$GEMMA_GGUF_FILE" "$WSL_LOCAL_CACHE_DIR/model")"
  GEMMA_TOKENIZER_PATH="$(localize_runtime_path "$GEMMA_TOKENIZER_PATH" "$WSL_LOCAL_CACHE_DIR/tokenizer")"
  GEMMA_HF_CONFIG_PATH="$(localize_runtime_path "$GEMMA_HF_CONFIG_PATH" "$WSL_LOCAL_CACHE_DIR/config")"
  export GEMMA_GGUF_FILE GEMMA_TOKENIZER_PATH GEMMA_HF_CONFIG_PATH
fi

python - <<'PY'
import os
from agent.runtime.gemma_local import build_runtime_config

config = build_runtime_config()
print("[vLLM] Gemma runtime configuration")
print(f"  gguf: {config.gguf_filename}")
print(f"  size_bytes: {config.gguf_size_bytes}")
print(f"  quantization: {config.quantization}")
print(f"  file: {config.gguf_file}")
print(f"  tokenizer: {config.tokenizer_path}")
print(f"  hf_config: {config.hf_config_path}")
print(f"  served_model_name: {config.served_model_name}")
print(f"  host: {config.host}:{config.port}")
print(f"  localized_gguf: {os.environ.get('GEMMA_GGUF_FILE')}")
print(f"  localized_tokenizer: {os.environ.get('GEMMA_TOKENIZER_PATH')}")
print(f"  localized_hf_config: {os.environ.get('GEMMA_HF_CONFIG_PATH')}")
PY

exec vllm serve "$GEMMA_GGUF_FILE" \
  --tokenizer "$GEMMA_TOKENIZER_PATH" \
  --hf-config-path "$GEMMA_HF_CONFIG_PATH" \
  --served-model-name "$VLLM_SERVED_MODEL_NAME" \
  --host "$VLLM_HOST" \
  --port "$VLLM_PORT" \
  --max-model-len "$VLLM_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$VLLM_GPU_MEMORY_UTILIZATION" \
  --api-key "$VLLM_API_KEY"
