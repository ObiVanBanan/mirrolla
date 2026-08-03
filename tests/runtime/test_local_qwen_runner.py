from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from agent.runtime.docker_sandbox import SandboxExecutionResult
from agent.runtime.local_qwen_runner import LocalQwenRunner, compact_execution_prompt


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.healthcheck_called = False
        self.config = type("Config", (), {"max_prompt_chars": 22000})()

    def healthcheck(self) -> None:
        self.healthcheck_called = True

    def generate_code(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.responses.pop(0)


class _FakeSandbox:
    def __init__(self, results: list[SandboxExecutionResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, list[str], str, int]] = []
        self.cleaned: list[str] = []

    def plan_input_filenames(self, file_paths: list[str], *, sandbox_filenames=None):
        return [Path(path).name for path in file_paths]

    def execute(self, code: str, file_paths: list[str], *, run_id: str, attempt: int):
        self.calls.append((code, file_paths, run_id, attempt))
        return self.results.pop(0)

    def cleanup_run(self, runtime_dir):
        self.cleaned.append(str(runtime_dir))


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
        runtime_dir="/tmp/run",
        output_dir="/tmp/output",
        timed_out=False,
        result_json_error=None,
        input_files=["a.csv"],
    )


def _input_file(tmp_path: Path) -> str:
    path = tmp_path / "a.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    return str(path)


def test_local_qwen_runner_succeeds_on_first_attempt(tmp_path: Path) -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "completed"
    assert result["attempts"] == 1
    assert result["code"] == "print('ok')"
    assert llm.healthcheck_called is True


def test_local_qwen_runner_recovers_after_parser_error(tmp_path: Path) -> None:
    llm = _FakeLLM([
        "```python\nif True print('broken')\n```",
        "```python\nprint('fixed')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert result["code"] == "print('fixed')"


def test_local_qwen_runner_repairs_after_sandbox_error(tmp_path: Path) -> None:
    llm = _FakeLLM([
        "```python\nprint('first')\n```",
        "```python\nprint('second')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(status="failed", error="NameError: missing"),
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert "Previous attempt failed" in llm.calls[1][1]
    assert "exit_code=1" in llm.calls[1][1]


def test_local_qwen_runner_fails_when_result_json_missing(tmp_path: Path) -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"] * 3)
    sandbox = _FakeSandbox([
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
        _sandbox_result(result=None, stdout="no result json", error="Sandbox execution failed without diagnostics"),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "failed"
    assert result["attempts"] == 3
    assert "after 3 attempts" in result["error"]


def test_local_qwen_runner_repairs_invalid_result_payload(tmp_path: Path) -> None:
    llm = _FakeLLM([
        "```python\nprint('first')\n```",
        "```python\nprint('second')\n```",
    ])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "success", "answer": "ok", "findings": []}),
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "completed"
    assert result["attempts"] == 2
    assert "Validator errors" in llm.calls[1][1]


def test_local_qwen_runner_returns_charts_and_last_code(tmp_path: Path) -> None:
    chart_path = tmp_path / "chart.png"
    chart_path.write_bytes(b"png")
    llm = _FakeLLM(["```python\nprint('chart')\n```"])
    sandbox = _FakeSandbox([
        _sandbox_result(
            result={"answer_status": "answered", "answer": "ok", "findings": []},
            charts=[str(chart_path)],
        ),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert len(result["charts"]) == 1
    assert result["charts"][0].endswith("chart.png")
    assert result["code"] == "print('chart')"
    assert "data/charts" in result["charts"][0].replace("\\", "/")


def test_local_qwen_runner_rejects_empty_file_list() -> None:
    runner = LocalQwenRunner(llm_client=_FakeLLM([]), sandbox=_FakeSandbox([]))

    result = runner.run_analysis("count rows", [])

    assert result["status"] == "failed"
    assert result["attempts"] == 0


def test_local_qwen_runner_healthcheck_failure_returns_failed(tmp_path: Path) -> None:
    class _BrokenLLM(_FakeLLM):
        def healthcheck(self) -> None:
            raise RuntimeError("offline")

    runner = LocalQwenRunner(llm_client=_BrokenLLM([]), sandbox=_FakeSandbox([]))

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "failed"
    assert result["attempts"] == 0
    assert "healthcheck failed" in result["error"]


def test_local_qwen_runner_caps_attempt_budget(tmp_path: Path) -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"] * 5)
    sandbox = _FakeSandbox([_sandbox_result(status="failed", error="boom")] * 3)
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)], max_retries=100)

    assert result["attempts"] == 3


def test_local_qwen_runner_negative_retries_use_single_attempt(tmp_path: Path) -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"])
    sandbox = _FakeSandbox([_sandbox_result(status="failed", error="boom")])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)], max_retries=-1)

    assert result["attempts"] == 1


def test_local_qwen_runner_fails_when_prompt_cannot_be_compacted(tmp_path: Path) -> None:
    llm = _FakeLLM([])
    sandbox = _FakeSandbox([])
    llm.config.max_prompt_chars = 4000
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)
    prompt = "\n\n".join(
        [
            "## Question\n" + ("Q" * 5000),
            "## Attached execution manifest\nM",
            "## Attached datasets for this analysis\nD",
            "## Hypotheses to validate\nH",
            "## Critical rules\nR",
            "## Output format\nO",
        ]
    )

    result = runner.run_analysis(prompt, [_input_file(tmp_path)])

    assert result["status"] == "failed"
    assert result["attempts"] == 0
    assert "too large" in result["error"].lower()


def test_local_qwen_runner_uses_exact_sandbox_paths_in_prompt(tmp_path: Path) -> None:
    llm = _FakeLLM(["```python\nprint('ok')\n```"])
    sandbox = _FakeSandbox([
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert "- /mnt/data/a.csv" in llm.calls[0][1]


def test_local_qwen_runner_truncates_diagnostics_to_last_stdout_lines(tmp_path: Path) -> None:
    llm = _FakeLLM([
        "```python\nprint('first')\n```",
        "```python\nprint('second')\n```",
    ])
    stdout_text = "\n".join(f"line-{index}" for index in range(60))
    sandbox = _FakeSandbox([
        _sandbox_result(status="failed", error="boom", stdout=stdout_text, stderr="stderr message"),
        _sandbox_result(result={"answer_status": "answered", "answer": "ok", "findings": []}),
    ])
    runner = LocalQwenRunner(llm_client=llm, sandbox=sandbox)

    result = runner.run_analysis("count rows", [_input_file(tmp_path)])

    assert result["status"] == "completed"
    repair_prompt = llm.calls[1][1]
    assert "line-59" in repair_prompt
    assert "line-0" not in repair_prompt


def test_compact_execution_prompt_reduces_optional_sections() -> None:
    prompt = "\n\n".join(
        [
            "## Question\nQ",
            "## Attached execution manifest\nM",
            "## Attached datasets for this analysis\nD",
            "## Hypotheses to validate\nH",
            "## Critical rules\nR",
            "## Output format\nO",
            "## Reference helpers\n" + ("X" * 5000),
        ]
    )

    compacted = compact_execution_prompt(prompt, 4000)

    assert "## Question" in compacted
    assert "## Output format" in compacted
    assert "## Reference helpers" not in compacted


def test_compact_execution_prompt_fails_when_required_sections_are_too_large() -> None:
    prompt = "\n\n".join(
        [
            "## Question\n" + ("Q" * 5000),
            "## Attached execution manifest\nM",
            "## Attached datasets for this analysis\nD",
            "## Hypotheses to validate\nH",
            "## Critical rules\nR",
            "## Output format\nO",
        ]
    )

    with pytest.raises(ValueError):
        compact_execution_prompt(prompt, 4000)
