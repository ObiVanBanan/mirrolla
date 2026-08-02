from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IMAGE = "mirrolla-analysis-sandbox:py312"
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True)
class SandboxExecutionResult:
    status: str
    stdout: str
    stderr: str
    exit_code: int | None
    result: dict | None
    charts: list[str]
    error: str | None
    script_path: str


def _truncate_output(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\n...[truncated]..."


class DockerSandbox:
    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        timeout_seconds: int = 120,
        memory_limit: str = "2g",
        cpu_limit: str = "1.0",
        pids_limit: int = 128,
        runtime_root: str = ".runtime",
    ) -> None:
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.pids_limit = pids_limit
        self.runtime_root = runtime_root

    def execute(self, code: str, file_paths: list[str], *, run_id: str = "local-qwen") -> SandboxExecutionResult:
        Path(self.runtime_root).mkdir(parents=True, exist_ok=True)
        runtime_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=self.runtime_root))
        input_dir = runtime_dir / "input"
        output_dir = runtime_dir / "output"
        script_dir = runtime_dir / "script"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        script_dir.mkdir(parents=True, exist_ok=True)

        try:
            for file_path in file_paths:
                source = Path(file_path)
                if source.is_symlink():
                    raise ValueError(f"Symlink inputs are not allowed: {source}")
                if not source.exists():
                    raise FileNotFoundError(str(source))
                shutil.copy2(source, input_dir / source.name)

            script_path = script_dir / "analysis.py"
            script_path.write_text(code, encoding="utf-8")

            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                str(self.pids_limit),
                "--memory",
                self.memory_limit,
                "--cpus",
                self.cpu_limit,
                "-v",
                f"{input_dir.resolve()}:/mnt/data:ro",
                "-v",
                f"{output_dir.resolve()}:/mnt/output:rw",
                "-v",
                f"{script_path.resolve()}:/mnt/script/analysis.py:ro",
                self.image,
                "python",
                "/mnt/script/analysis.py",
            ]

            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxExecutionResult(
                status="timeout",
                stdout=_truncate_output(exc.stdout or ""),
                stderr=_truncate_output(exc.stderr or ""),
                exit_code=None,
                result=None,
                charts=[],
                error="Sandbox execution timed out",
                script_path=str((script_dir / "analysis.py").resolve()),
            )
        except Exception as exc:
            return SandboxExecutionResult(
                status="failed",
                stdout="",
                stderr="",
                exit_code=None,
                result=None,
                charts=[],
                error=str(exc),
                script_path=str((script_dir / "analysis.py").resolve()),
            )

        stdout = _truncate_output(completed.stdout)
        stderr = _truncate_output(completed.stderr)
        result_path = output_dir / "result.json"
        result_payload = None
        if result_path.exists():
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return SandboxExecutionResult(
                    status="failed",
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=completed.returncode,
                    result=None,
                    charts=[],
                    error=f"result.json is not valid JSON: {exc.msg}",
                    script_path=str(script_path.resolve()),
                )

        charts = sorted(str(path.resolve()) for path in output_dir.glob("*.png"))
        status = "completed" if completed.returncode == 0 else "failed"
        error = None if completed.returncode == 0 else f"Sandbox exited with code {completed.returncode}"

        return SandboxExecutionResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.returncode,
            result=result_payload,
            charts=charts,
            error=error,
            script_path=str(script_path.resolve()),
        )
