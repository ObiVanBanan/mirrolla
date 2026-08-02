from __future__ import annotations

import json
import os
import time
import uuid

from agent.runtime.code_parser import GeneratedCodeError, extract_python_code
from agent.runtime.docker_sandbox import DockerSandbox, SandboxExecutionResult
from agent.runtime.local_llm import LocalLLMClient


SYSTEM_PROMPT = """You are Mirrolla local analytical code generator.

Return only Python code.
Do not return markdown explanations unless the response is a Python code block.
The script must:
- read input files only from /mnt/data;
- inspect the available files and their headers before computing metrics;
- prefer pandas or csv.DictReader and reference columns by header names, not positional indexes;
- write the final JSON result to /mnt/output/result.json;
- optionally save PNG charts to /mnt/output;
- never use network access;
- never use subprocess, shell commands, pip, eval, or exec.
- result.json must be a JSON object with:
  - answer_status: one of answered, partial, not_enough_data
  - answer: a short human-readable string
  - findings: a list, use [] when there are no itemized findings
"""


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
        run_id = uuid.uuid4().hex[:8]
        file_names = [os.path.basename(path) for path in file_paths]
        attempts = 0
        last_error = ""
        last_code: str | None = None
        previous_code: str | None = None

        self.llm_client.healthcheck()

        for attempt in range(1, max_retries + 2):
            attempts = attempt
            llm_started = time.perf_counter()
            try:
                user_prompt = self._build_user_prompt(
                    prompt=prompt,
                    file_names=file_names,
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
            sandbox_result = self.sandbox.execute(code, file_paths, run_id=run_id)
            sandbox_ms = int((time.perf_counter() - sandbox_started) * 1000)
            print(f"[LocalQwenRunner] run={run_id} attempt={attempt} llm_ms={llm_ms} sandbox_ms={sandbox_ms}")

            if sandbox_result.status == "completed" and isinstance(sandbox_result.result, dict):
                validation_error = self._validate_result_payload(sandbox_result.result)
                if validation_error:
                    last_error = validation_error
                    previous_code = code
                    continue
                result_text = json.dumps(sandbox_result.result, ensure_ascii=False)
                print(
                    f"[LocalQwenRunner] result_json=true findings={len(sandbox_result.result.get('findings', []))} charts={len(sandbox_result.charts)}"
                )
                return {
                    "status": "completed",
                    "text": result_text,
                    "charts": sandbox_result.charts,
                    "error": "",
                    "code": code,
                    "attempts": attempt,
                }

            last_error = self._build_sandbox_error(sandbox_result)
            previous_code = code

        return {
            "status": "failed",
            "text": "",
            "charts": [],
            "error": last_error or "Local Qwen execution failed",
            "code": last_code,
            "attempts": attempts,
        }

    def _build_user_prompt(
        self,
        *,
        prompt: str,
        file_names: list[str],
        previous_code: str | None,
        previous_error: str,
    ) -> str:
        file_block = "\n".join(f"- {name}" for name in file_names) or "- no attached files"
        repair_block = ""
        if previous_error:
            repair_block = (
                "\nPrevious attempt failed.\n"
                f"Error:\n{previous_error}\n"
            )
            if previous_code:
                repair_block += f"\nPrevious code:\n```python\n{previous_code}\n```\n"
            repair_block += "Fix the problem and return a full replacement script.\n"

        return (
            f"Task:\n{prompt}\n\n"
            f"Attached sandbox files:\n{file_block}\n\n"
            "Output contract:\n"
            "- Write /mnt/output/result.json.\n"
            "- answer_status must be exactly one of: answered, partial, not_enough_data.\n"
            "- answer must be a short string, never a number or object.\n"
            "- findings must be a JSON list. Use [] when there are no detailed findings.\n"
            "- Read tabular files by column names from the header row, not by column position.\n\n"
            "Return one complete Python script that writes JSON to /mnt/output/result.json.\n"
            f"{repair_block}"
        )

    def _build_sandbox_error(self, sandbox_result: SandboxExecutionResult) -> str:
        if sandbox_result.error:
            return sandbox_result.error
        if sandbox_result.stderr:
            return sandbox_result.stderr
        if sandbox_result.stdout:
            return sandbox_result.stdout
        return "Sandbox execution failed without diagnostics"

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
