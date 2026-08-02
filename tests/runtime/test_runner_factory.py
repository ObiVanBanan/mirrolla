from __future__ import annotations

from unittest.mock import patch

import pytest

from agent.runtime.runner_factory import create_analysis_runner


def test_runner_factory_returns_local_qwen_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXECUTION_BACKEND", raising=False)

    with patch("agent.runtime.runner_factory.LocalQwenRunner", return_value="local-runner"):
        assert create_analysis_runner() == "local-runner"


def test_runner_factory_returns_local_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_BACKEND", "local_qwen")

    with patch("agent.runtime.runner_factory.LocalQwenRunner", return_value="local-runner"):
        assert create_analysis_runner() == "local-runner"


def test_runner_factory_returns_openai_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_BACKEND", "openai_ci")

    with patch("agent.runtime.runner_factory.CIRunner", return_value="ci-runner"):
        assert create_analysis_runner() == "ci-runner"


def test_runner_factory_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXECUTION_BACKEND", "unknown")

    with pytest.raises(ValueError) as exc_info:
        create_analysis_runner()

    assert "Unknown execution backend" in str(exc_info.value)
