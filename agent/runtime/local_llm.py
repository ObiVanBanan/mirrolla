from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass

from openai import OpenAI


DEFAULT_BASE_URL = "http://127.0.0.1:8010/v1"
DEFAULT_API_KEY = "mirrolla-local"
DEFAULT_MODEL = "qwen-coder-local"
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_PROMPT_CHARS = 22000


@dataclass(frozen=True)
class LocalLLMConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_tokens: int
    temperature: float
    max_prompt_chars: int


def _normalize_base_url(raw_url: str) -> str:
    value = raw_url.strip().rstrip("/")
    if not value:
        raise ValueError("LOCAL_LLM_BASE_URL must not be empty")
    return value


def _load_float(env_name: str, default_value: float) -> float:
    raw_value = os.getenv(env_name, str(default_value))
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a number") from exc


def _load_int(env_name: str, default_value: int) -> int:
    raw_value = os.getenv(env_name, str(default_value))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer") from exc


def load_local_llm_config() -> LocalLLMConfig:
    base_url = _normalize_base_url(os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL))
    api_key = os.getenv("LOCAL_LLM_API_KEY", DEFAULT_API_KEY).strip()
    model = os.getenv("LOCAL_LLM_MODEL", DEFAULT_MODEL).strip()
    timeout_seconds = _load_float("LOCAL_LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    max_tokens = _load_int("LOCAL_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS)
    temperature = _load_float("LOCAL_LLM_TEMPERATURE", DEFAULT_TEMPERATURE)
    max_prompt_chars = _load_int("LOCAL_LLM_MAX_PROMPT_CHARS", DEFAULT_MAX_PROMPT_CHARS)

    if not api_key:
        raise ValueError("LOCAL_LLM_API_KEY must not be empty")
    if not model:
        raise ValueError("LOCAL_LLM_MODEL must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("LOCAL_LLM_TIMEOUT_SECONDS must be greater than 0")
    if max_tokens < 256:
        raise ValueError("LOCAL_LLM_MAX_TOKENS must be at least 256")
    if not 0 <= temperature <= 1:
        raise ValueError("LOCAL_LLM_TEMPERATURE must be between 0 and 1")
    if max_prompt_chars < 4000:
        raise ValueError("LOCAL_LLM_MAX_PROMPT_CHARS must be at least 4000")

    return LocalLLMConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        max_prompt_chars=max_prompt_chars,
    )


class LocalLLMClient:
    def __init__(
        self,
        config: LocalLLMConfig | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.config = config or load_local_llm_config()
        self.client = client or OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout_seconds,
        )

    def healthcheck(self) -> None:
        self.client.models.list()

    def generate_code(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        message = response.choices[0].message.content
        if not message:
            raise ValueError("Local LLM returned an empty response")
        return message


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect local LLM config.")
    parser.add_argument("--format", choices=("json",), default="json", help="Output format.")
    return parser


def _redact_config(config: LocalLLMConfig) -> dict[str, object]:
    payload = asdict(config)
    payload["api_key"] = "***redacted***"
    return payload


def main() -> int:
    parser = _build_arg_parser()
    parser.parse_args()
    config = load_local_llm_config()
    print(json.dumps(_redact_config(config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
