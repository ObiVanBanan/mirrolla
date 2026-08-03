from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

from agent.runtime.code_parser import extract_python_code
from agent.runtime.docker_sandbox import DockerSandbox, SandboxExecutionResult
from agent.runtime.local_llm import LocalLLMClient


MAX_REPAIR_CODE_CHARS = 12000
MAX_DIAGNOSTICS_CHARS = 8000
CHARTS_ROOT = Path("data/charts")
SYSTEM_PROMPT = """You are Mirrolla local analytical code generator.

Return exactly one complete Python script.
The script must:
- read input files only from /mnt/data;
- inspect available files and headers before computing metrics;
- write the final JSON result to /mnt/output/result.json;
- print the same final JSON to stdout;
- save PNG charts only to /mnt/output;
- use ensure_ascii=False and default=str when serializing JSON;
- avoid NaN and Infinity in JSON output;
- never use network access;
- never use shell commands, subprocess, pip, eval, or exec.
"""


def compact_execution_prompt(prompt: str, max_chars: int) -> str:
    if max_chars < 4000:
        raise ValueError("max_chars must be at least 4000")
    if len(prompt) <= max_chars:
        return prompt

    headings = [
        "## Question",
        "## Attached execution manifest",
        "## Attached datasets for this analysis",
        "## Hypotheses to validate",
        "## Critical rules",
        "## Output format",
    ]
    sections = _split_sections(prompt)
    kept: list[str] = []
    optional: list[str] = []
    for section in sections:
        if any(section.startswith(heading) for heading in headings):
            kept.append(section)
        elif section.startswith("## Reference helpers"):
            continue
        else:
            optional.append(section)

    compacted = "\n\n".join([*kept, *optional]).strip()
    if len(compacted) <= max_chars:
        return compacted

    while optional and len(compacted) > max_chars:
        optional.pop()
        compacted = "\n\n".join([*kept, *optional]).strip()

    if len(compacted) > max_chars:
        raise ValueError("Prompt is too large even after compaction")
    return compacted


def _split_sections(prompt: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for line in prompt.splitlines():
        if line.startswith("## ") and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


class LocalQwenRunner:
    def __init__(
        self,
        *,
        llm_client: LocalLLMClient | None = None,
        sandbox: DockerSandbox | None = None,
    ) -> None:
        self.llm_client = llm_client or LocalLLMClient()
        self.sandbox = sandbox or DockerSandbox()

    def run_analysis(
        self,
        prompt: str,
        file_paths: list[str],
        max_retries: int = 2,
    ) -> dict:
        if not file_paths:
            return self._failed_result("No input files were provided", None, 0)
        for file_path in file_paths:
            if not Path(file_path).exists():
                return self._failed_result(f"Input file does not exist: {file_path}", None, 0)

        attempts_limit = 1 + min(max(max_retries, 0), 2)
        run_id = uuid.uuid4().hex[:8]
        previous_code: str | None = None
        last_code: str | None = None
        last_error = ""

        try:
            self.llm_client.healthcheck()
        except Exception as exc:
            return self._failed_result(f"Local LLM healthcheck failed: {exc}", None, 0)

        sandbox_names = self.sandbox.plan_input_filenames(file_paths)
        prompt = compact_execution_prompt(prompt, self.llm_client.config.max_prompt_chars)

        for attempt in range(1, attempts_limit + 1):
            llm_started = time.perf_counter()
            try:
                user_prompt = self._build_user_prompt(
                    prompt=prompt,
                    sandbox_names=sandbox_names,
                    previous_code=previous_code,
                    previous_error=last_error,
                )
                raw_response = self.llm_client.generate_code(SYSTEM_PROMPT, user_prompt)
                llm_ms = int((time.perf_counter() - llm_started) * 1000)
                code = extract_python_code(raw_response)
                last_code = code
            except Exception as exc:
                last_error = str(exc)
                print(f"[LocalQwenRunner] run={run_id} attempt={attempt} llm_ms={int((time.perf_counter() - llm_started) * 1000)} error={last_error}")
                previous_code = last_code
                continue

            sandbox_started = time.perf_counter()
            sandbox_result = self.sandbox.execute(code, file_paths, run_id=run_id, attempt=attempt)
            sandbox_ms = int((time.perf_counter() - sandbox_started) * 1000)
            print(f"[LocalQwenRunner] run={run_id} attempt={attempt} llm_ms={llm_ms} sandbox_ms={sandbox_ms}")

            try:
                if sandbox_result.status == "completed" and isinstance(sandbox_result.result, dict):
                    validation_error = self._validate_result_payload(sandbox_result.result)
                    if validation_error:
                        last_error = validation_error
                        previous_code = code
                        continue
                    chart_paths = self._persist_charts(run_id, sandbox_result.charts)
                    result_text = json.dumps(sandbox_result.result, ensure_ascii=False)
                    print(
                        f"[LocalQwenRunner] result_json=true findings={len(sandbox_result.result.get('findings', []))} charts={len(chart_paths)}"
                    )
                    return {
                        "status": "completed",
                        "text": result_text,
                        "charts": chart_paths,
                        "error": "",
                        "code": code,
                        "attempts": attempt,
                    }

                last_error = self._build_sandbox_error(sandbox_result)
                previous_code = code
            finally:
                self.sandbox.cleanup_run(sandbox_result.runtime_dir)

        return self._failed_result(
            f"Local Qwen execution failed after {attempts_limit} attempts: {last_error or 'unknown error'}",
            last_code,
            attempts_limit,
        )

    def _build_user_prompt(
        self,
        *,
        prompt: str,
        sandbox_names: list[str],
        previous_code: str | None,
        previous_error: str,
    ) -> str:
        file_block = "\n".join(f"- /mnt/data/{name}" for name in sandbox_names)
        repair_block = ""
        if previous_error:
            repair_block = (
                "\nPrevious attempt failed.\n"
                f"Diagnostics:\n{previous_error[-MAX_DIAGNOSTICS_CHARS:]}\n"
            )
            if previous_code:
                trimmed_code = previous_code[-MAX_REPAIR_CODE_CHARS:]
                repair_block += f"\nPrevious code:\n```python\n{trimmed_code}\n```\n"
            repair_block += "Return a full replacement Python script. Do not return a diff.\n"

        return (
            f"{prompt}\n\n"
            "## Critical rules\n"
            "- Use only the exact sandbox file paths listed below.\n"
            "- Write /mnt/output/result.json and print the same JSON to stdout.\n"
            "- answer_status must be exactly one of: answered, partial, not_enough_data.\n"
            "- answer must be a non-empty string.\n"
            "- findings must be a JSON list.\n"
            "- Do not change input file paths.\n\n"
            "## Output format\n"
            "- Return one complete Python script.\n\n"
            f"## Sandbox files\n{file_block}\n"
            f"{repair_block}"
        )

    def _build_sandbox_error(self, sandbox_result: SandboxExecutionResult) -> str:
        parts: list[str] = []
        if sandbox_result.exit_code is not None:
            parts.append(f"exit_code={sandbox_result.exit_code}")
        parts.append(f"timed_out={sandbox_result.timed_out}")
        if sandbox_result.result_json_error:
            parts.append(f"result_json_error={sandbox_result.result_json_error}")
        if sandbox_result.stderr:
            parts.append(f"stderr={sandbox_result.stderr[-MAX_DIAGNOSTICS_CHARS:]}")
        if sandbox_result.stdout:
            parts.append(f"stdout={sandbox_result.stdout[-MAX_DIAGNOSTICS_CHARS:]}")
        if sandbox_result.error:
            parts.append(f"error={sandbox_result.error}")
        return "\n".join(parts) or "Sandbox execution failed without diagnostics"

    def _persist_charts(self, run_id: str, chart_paths: list[str]) -> list[str]:
        if not chart_paths:
            return []
        destination_dir = CHARTS_ROOT / run_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for chart_path in chart_paths:
            source = Path(chart_path)
            destination = destination_dir / source.name
            shutil.copy2(source, destination)
            copied.append(str(destination.resolve()))
        return copied

    def _validate_result_payload(self, payload: dict) -> str | None:
        allowed_statuses = {"answered", "partial", "not_enough_data"}
        answer_status = payload.get("answer_status")
        if answer_status not in allowed_statuses:
            return "result.json has invalid answer_status"
        if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
            return "result.json must contain a non-empty string answer"
        findings = payload.get("findings")
        if not isinstance(findings, list):
            return "result.json must contain findings as a list"
        return None

    def _failed_result(self, error: str, code: str | None, attempts: int) -> dict:
        return {
            "status": "failed",
            "text": "",
            "charts": [],
            "error": error,
            "code": code,
            "attempts": attempts,
        }
