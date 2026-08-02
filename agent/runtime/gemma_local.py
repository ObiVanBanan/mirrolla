from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath


DEFAULT_MODEL_DIR = Path(
    r"C:\Users\theso\.lmstudio\models\lmstudio-community\gemma-4-12B-it-GGUF"
)
DEFAULT_SERVED_MODEL_NAME = "gemma-4-12b-local"
DEFAULT_PORT = 8010


class GemmaLocalConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class GemmaRuntimeConfig:
    model_dir: str
    gguf_file: str
    gguf_filename: str
    gguf_size_bytes: int
    quantization: str
    tokenizer_path: str
    hf_config_path: str
    served_model_name: str
    host: str
    port: int
    api_key: str
    max_model_len: int
    gpu_memory_utilization: float


def discover_gguf_files(model_dir: Path) -> list[Path]:
    if not model_dir.exists():
        raise GemmaLocalConfigError(f"Model directory not found: {model_dir}")
    return sorted(path for path in model_dir.rglob("*.gguf") if path.is_file())


def _looks_like_windows_drive_path(value: str) -> bool:
    return len(value) >= 3 and value[1:3] == ":\\" and value[0].isalpha()


def guess_quantization(file_name: str) -> str:
    stem = Path(file_name).stem
    parts = stem.split("-")
    for part in reversed(parts):
        upper = part.upper()
        if upper.startswith("Q") or upper in {"BF16", "FP16", "F16", "F32"}:
            return part
    return "unknown"


def resolve_gguf_file(model_dir: Path, explicit_file: str | None = None) -> Path:
    candidates = discover_gguf_files(model_dir)
    if explicit_file:
        selected = Path(explicit_file)
        if not selected.is_absolute():
            selected = (model_dir / selected).resolve()
        if not selected.exists():
            raise GemmaLocalConfigError(
                f"GEMMA_GGUF_FILE points to a missing file: {selected}"
            )
        if selected.suffix.lower() != ".gguf":
            raise GemmaLocalConfigError("GEMMA_GGUF_FILE must point to a .gguf file")
        return selected

    if not candidates:
        raise GemmaLocalConfigError(
            "No .gguf files were found in the Gemma model directory."
        )
    if len(candidates) > 1:
        options = "\n".join(f"- {path}" for path in candidates)
        raise GemmaLocalConfigError(
            "Multiple .gguf files found. Set GEMMA_GGUF_FILE explicitly.\n"
            f"{options}"
        )
    return candidates[0]


def _resolve_support_path(value: str | None, env_name: str) -> str:
    if not value:
        raise GemmaLocalConfigError(
            "GGUF found, but Gemma tokenizer/config is missing for vLLM. "
            "Set GEMMA_TOKENIZER_PATH and GEMMA_HF_CONFIG_PATH."
        )
    return value


def normalize_runtime_path(raw_path: str) -> str:
    if os.name != "nt" and _looks_like_windows_drive_path(raw_path):
        return windows_to_wsl_path(raw_path)
    return raw_path


def build_runtime_config(environ: dict[str, str] | None = None) -> GemmaRuntimeConfig:
    env = os.environ if environ is None else environ
    model_dir = Path(normalize_runtime_path(env.get("GEMMA_MODEL_DIR", str(DEFAULT_MODEL_DIR))))
    gguf_file = resolve_gguf_file(
        model_dir,
        normalize_runtime_path(env.get("GEMMA_GGUF_FILE")) if env.get("GEMMA_GGUF_FILE") else None,
    )
    tokenizer_path = normalize_runtime_path(
        _resolve_support_path(env.get("GEMMA_TOKENIZER_PATH"), "GEMMA_TOKENIZER_PATH")
    )
    hf_config_path = normalize_runtime_path(
        _resolve_support_path(env.get("GEMMA_HF_CONFIG_PATH"), "GEMMA_HF_CONFIG_PATH")
    )

    return GemmaRuntimeConfig(
        model_dir=str(model_dir),
        gguf_file=str(gguf_file),
        gguf_filename=gguf_file.name,
        gguf_size_bytes=gguf_file.stat().st_size,
        quantization=guess_quantization(gguf_file.name),
        tokenizer_path=tokenizer_path,
        hf_config_path=hf_config_path,
        served_model_name=env.get("VLLM_SERVED_MODEL_NAME", DEFAULT_SERVED_MODEL_NAME),
        host=env.get("VLLM_HOST", "0.0.0.0"),
        port=int(env.get("VLLM_PORT", str(DEFAULT_PORT))),
        api_key=env.get("VLLM_API_KEY", "mirrolla-local"),
        max_model_len=int(env.get("VLLM_MAX_MODEL_LEN", "8192")),
        gpu_memory_utilization=float(env.get("VLLM_GPU_MEMORY_UTILIZATION", "0.85")),
    )


def windows_to_wsl_path(path: str) -> str:
    raw = str(PureWindowsPath(path))
    drive, _, rest = raw.partition(":")
    if not drive:
        return raw.replace("\\", "/")
    normalized_rest = rest.replace("\\", "/").lstrip("/")
    return f"/mnt/{drive.lower()}/{normalized_rest}"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Gemma local runtime config.")
    parser.add_argument(
        "--format",
        choices=("json", "shell"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--wsl-path",
        help="Convert a Windows path to a WSL path and print it.",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        if args.wsl_path:
            print(windows_to_wsl_path(args.wsl_path))
            return 0

        config = build_runtime_config()
        payload = asdict(config)
        if args.format == "shell":
            for key, value in payload.items():
                env_key = key.upper()
                print(f"{env_key}={json.dumps(value)}")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except GemmaLocalConfigError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
