from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.runtime.local_llm import LocalLLMClient, load_local_llm_config


class _FakeModels:
    def __init__(self) -> None:
        self.called = False

    def list(self):
        self.called = True
        return []


class _FakeChatCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="```python\nprint('ok')\n```")
                )
            ]
        )


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()
        self.chat_completions = _FakeChatCompletions()
        self.chat = SimpleNamespace(completions=self.chat_completions)


@pytest.fixture(autouse=True)
def _clear_local_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "LOCAL_LLM_BASE_URL",
        "LOCAL_LLM_API_KEY",
        "LOCAL_LLM_MODEL",
        "LOCAL_LLM_TIMEOUT_SECONDS",
        "LOCAL_LLM_MAX_TOKENS",
        "LOCAL_LLM_TEMPERATURE",
    ):
        monkeypatch.delenv(env_name, raising=False)


def test_load_local_llm_config_uses_defaults() -> None:
    config = load_local_llm_config()

    assert config.base_url == "http://127.0.0.1:8010/v1"
    assert config.api_key == "mirrolla-local"
    assert config.model == "qwen-coder-local"


def test_load_local_llm_config_normalizes_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8010/v1/")

    config = load_local_llm_config()

    assert config.base_url == "http://127.0.0.1:8010/v1"


def test_load_local_llm_config_rejects_invalid_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT_SECONDS", "0")

    with pytest.raises(ValueError) as exc_info:
        load_local_llm_config()

    assert "LOCAL_LLM_TIMEOUT_SECONDS" in str(exc_info.value)


def test_load_local_llm_config_rejects_invalid_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_TEMPERATURE", "1.5")

    with pytest.raises(ValueError) as exc_info:
        load_local_llm_config()

    assert "LOCAL_LLM_TEMPERATURE" in str(exc_info.value)


def test_healthcheck_calls_models_list() -> None:
    fake_client = _FakeClient()
    llm_client = LocalLLMClient(client=fake_client)

    llm_client.healthcheck()

    assert fake_client.models.called is True


def test_generate_code_uses_chat_completions_with_configured_model() -> None:
    fake_client = _FakeClient()
    llm_client = LocalLLMClient(client=fake_client)

    result = llm_client.generate_code("system", "user")

    assert "print('ok')" in result
    assert fake_client.chat_completions.calls[0]["model"] == "qwen-coder-local"
    assert not hasattr(fake_client, "files")
    assert not hasattr(fake_client, "responses")
