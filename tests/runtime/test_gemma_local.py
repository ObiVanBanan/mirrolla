from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent.runtime.gemma_local import (
    GemmaLocalConfigError,
    build_runtime_config,
    guess_quantization,
    normalize_runtime_path,
    resolve_gguf_file,
    windows_to_wsl_path,
)

TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp-tests"
TMP_ROOT.mkdir(exist_ok=True)


def test_resolve_gguf_file_requires_explicit_env_when_multiple_candidates() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "gemma-4-12B-it-Q4_K_M.gguf").write_text("model", encoding="utf-8")
        (tmp_path / "mmproj-gemma-4-12B-it-BF16.gguf").write_text("projector", encoding="utf-8")

        with pytest.raises(GemmaLocalConfigError) as exc_info:
            resolve_gguf_file(tmp_path)

        assert "GEMMA_GGUF_FILE" in str(exc_info.value)


def test_build_runtime_config_accepts_relative_explicit_file() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmp_dir:
        tmp_path = Path(tmp_dir)
        model_file = tmp_path / "gemma-4-12B-it-Q4_K_M.gguf"
        model_file.write_text("model", encoding="utf-8")

        config = build_runtime_config(
            {
                "GEMMA_MODEL_DIR": str(tmp_path),
                "GEMMA_GGUF_FILE": model_file.name,
                "GEMMA_TOKENIZER_PATH": "google/gemma-4-12b-it",
                "GEMMA_HF_CONFIG_PATH": "google/gemma-4-12b-it",
            }
        )

        assert config.gguf_file == str(model_file.resolve())
        assert config.quantization == "Q4_K_M"


def test_build_runtime_config_requires_tokenizer_and_config() -> None:
    with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmp_dir:
        tmp_path = Path(tmp_dir)
        model_file = tmp_path / "gemma-4-12B-it-Q4_K_M.gguf"
        model_file.write_text("model", encoding="utf-8")

        with pytest.raises(GemmaLocalConfigError) as exc_info:
            build_runtime_config(
                {
                    "GEMMA_MODEL_DIR": str(tmp_path),
                    "GEMMA_GGUF_FILE": str(model_file),
                }
            )

        message = str(exc_info.value)
        assert "GEMMA_TOKENIZER_PATH" in message
        assert "GEMMA_HF_CONFIG_PATH" in message


def test_guess_quantization_handles_missing_hint() -> None:
    assert guess_quantization("gemma-custom.gguf") == "unknown"


def test_windows_to_wsl_path_converts_drive_paths() -> None:
    assert windows_to_wsl_path(r"C:\Users\theso\Desktop\job\Mirrolla") == "/mnt/c/Users/theso/Desktop/job/Mirrolla"


def test_normalize_runtime_path_keeps_hf_repo_id() -> None:
    assert normalize_runtime_path("google/gemma-4-12b-it") == "google/gemma-4-12b-it"
