from __future__ import annotations

from agent.runtime.docker_sandbox import SandboxExecutionResult
from agent.runtime.local_qwen_runner import LocalQwenRunner


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.healthcheck_called = False

    def healthcheck(self) -> None:
        self.healthcheck_called = True

    def generate_code(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.responses.pop(0)


class _FakeSandbox:
    def __init__(self, results: list[SandboxExecutionResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, list[str], str]] = []

    def execute(self, code: str, file_paths: list[str], *, run_id: str):
        self.calls.append((code, file_paths, run_id))
        return self.results.pop(0)


def _sandbox_result(
    *,
    status: str = "completed",
    result: dict | None = None,
    charts: list[str] | None = None,
    error: str | None = None,
    stdout: str = "",
    stderr: str = "",
) -> SandboxExecutionResult:
    return SandboxExecutionResult(
        status=status,
        stdout=stdout,
        stderr=stderr,
        exit_code=0 if status == "completed" else 1,
        result=result,
        charts=charts or [],
        error=error,
        script_path="/tmp/analysis.py",
    )


def test_local_qwen_runner_succeeds_on_first_attempt() -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["status"] == "completed"
    assert result["attempts"] == 1
    assert result["code"] == "print('ok')"
    assert llm.healthcheck_called is True


def test_local_qwen_runner_recovers_after_parser_error() -> None:
    llm = _FakeLLM([
        "```python\nif True print('broken')\n```",
        "```python\nprint('fixed')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert result["code"] == "print('fixed')"


def test_local_qwen_runner_repairs_after_sandbox_error() -> None:
    llm = _FakeLLM([
        "```python\nprint('first')\n```",
        "```python\nprint('second')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(status="failed", error="NameError: missing"),
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert "Previous attempt failed" in llm.calls[1][1]


def test_local_qwen_runner_fails_when_result_json_missing() -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"] * 3)
    sandbox = _FakeSandbox([
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["status"] == "failed"
    assert result["attempts"] == 3


def test_local_qwen_runner_repairs_invalid_result_payload() -> None:
    llm = _FakeLLM([
        "```python\nprint('first')\n```",
        "```python\nprint('second')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "success", "answer": "ok", "findings": []}),
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert "Previous attempt failed" in llm.calls[1][1]


def test_local_qwen_runner_returns_charts_and_last_code() -> None:
    llm = _FakeLLM(["```python\nprint('chart')\n```"])
    sandbox = _FakeSandbox([
        _sandbox_result(
            result={"answer_status": "answered", "answer": "ok", "findings": []},
            charts=["chart.png"],
        ),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", ["a.csv"])

    assert result["charts"] == ["chart.png"]
    assert result["code"] == "print('chart')"
