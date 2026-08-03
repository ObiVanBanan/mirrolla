from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_IMAGE = "mirrolla-analysis-sandbox:py312"
DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_MEMORY_LIMIT = "4g"
DEFAULT_CPU_LIMIT = "2"
DEFAULT_PIDS_LIMIT = 128
DEFAULT_RUNTIME_ROOT = Path(".runtime/local-executor")
MAX_OUTPUT_CHARS = 1024 * 1024
MAX_RESULT_JSON_BYTES = 5 * 1024 * 1024
MAX_PNG_COUNT = 10
MAX_PNG_BYTES = 20 * 1024 * 1024
SAFE_BASENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SANDBOX_UID = 10001
SANDBOX_GID = 10001


@dataclass(frozen=True)
class SandboxConfig:
    image: str
    timeout_seconds: int
    memory_limit: str
    cpu_limit: str
    pids_limit: int
    runtime_root: Path
    keep_runs: bool


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
    runtime_dir: str
    output_dir: str
    timed_out: bool
    result_json_error: str | None
    input_files: list[str]


def _truncate_output(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    return value[:MAX_OUTPUT_CHARS] + "\n[output truncated]"


def _parse_positive_int(raw_value: str, env_name: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{env_name} must be greater than zero")
    return value


def load_sandbox_config() -> SandboxConfig:
    image = os.getenv("LOCAL_SANDBOX_IMAGE", DEFAULT_IMAGE).strip()
    if not image:
        raise ValueError("LOCAL_SANDBOX_IMAGE must not be empty")

    timeout_seconds = _parse_positive_int(
        os.getenv("LOCAL_SANDBOX_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)),
        "LOCAL_SANDBOX_TIMEOUT_SECONDS",
    )
    pids_limit = _parse_positive_int(
        os.getenv("LOCAL_SANDBOX_PIDS_LIMIT", str(DEFAULT_PIDS_LIMIT)),
        "LOCAL_SANDBOX_PIDS_LIMIT",
    )
    memory_limit = os.getenv("LOCAL_SANDBOX_MEMORY", DEFAULT_MEMORY_LIMIT).strip()
    cpu_limit = os.getenv("LOCAL_SANDBOX_CPUS", DEFAULT_CPU_LIMIT).strip()
    runtime_root_raw = os.getenv("LOCAL_SANDBOX_ROOT", str(DEFAULT_RUNTIME_ROOT)).strip()
    if not runtime_root_raw:
        raise ValueError("LOCAL_SANDBOX_ROOT must not be empty")
    runtime_root = Path(runtime_root_raw)
    keep_runs = os.getenv("LOCAL_SANDBOX_KEEP_RUNS", "0").strip() == "1"

    return SandboxConfig(
        image=image,
        timeout_seconds=timeout_seconds,
        memory_limit=memory_limit,
        cpu_limit=cpu_limit,
        pids_limit=pids_limit,
        runtime_root=runtime_root,
        keep_runs=keep_runs,
    )


class DockerSandbox:
    def __init__(self, *, config: SandboxConfig | None = None) -> None:
        self.config = config or load_sandbox_config()

    def execute(
        self,
        code: str,
        file_paths: list[str],
        *,
        run_id: str = "local-qwen",
        attempt: int = 1,
        sandbox_filenames: list[str] | None = None,
    ) -> SandboxExecutionResult:
        runtime_dir = self.config.runtime_root / run_id
        input_dir = runtime_dir / "input"
        output_dir = runtime_dir / "output"
        attempts_dir = runtime_dir / "attempts"
        metadata_path = runtime_dir / "metadata.json"

        runtime_dir.mkdir(parents=True, exist_ok=True)
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        attempts_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_output_directory(output_dir)

        stdout_path = attempts_dir / f"attempt_{attempt}.stdout.txt"
        stderr_path = attempts_dir / f"attempt_{attempt}.stderr.txt"
        script_path = attempts_dir / f"attempt_{attempt}.py"
        script_path.write_text(code, encoding="utf-8")

        copied_files: list[str] = []
        command: list[str] = []
        self._write_metadata(
            metadata_path,
            run_id=run_id,
            attempt=attempt,
            input_files=[],
            command=[],
            exit_code=None,
            status="prepared",
            timed_out=False,
            result_json_error=None,
        )

        try:
            copied_files = self._copy_input_files(
                file_paths=file_paths,
                input_dir=input_dir,
                sandbox_filenames=sandbox_filenames,
            )
            command = self._build_command(
                input_dir=input_dir,
                output_dir=output_dir,
                script_path=script_path,
            )
            self._write_metadata(
                metadata_path,
                run_id=run_id,
                attempt=attempt,
                input_files=copied_files,
                command=command,
                exit_code=None,
                status="running",
                timed_out=False,
                result_json_error=None,
            )

            completed = subprocess.run(
                command,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
            )
            stdout_path.write_text(completed.stdout or "", encoding="utf-8")
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            stdout_value = exc.stdout or ""
            stderr_value = exc.stderr or ""
            stdout_path.write_text(stdout_value, encoding="utf-8")
            stderr_path.write_text(stderr_value, encoding="utf-8")
            self._write_metadata(
                metadata_path,
                run_id=run_id,
                attempt=attempt,
                input_files=copied_files,
                command=command,
                exit_code=None,
                status="timeout",
                timed_out=True,
                result_json_error="Sandbox execution timed out",
            )
            return SandboxExecutionResult(
                status="failed",
                stdout=_truncate_output(stdout_value),
                stderr=_truncate_output(stderr_value),
                exit_code=None,
                result=None,
                charts=[],
                error="Sandbox execution timed out",
                script_path=str(script_path.resolve()),
                runtime_dir=str(runtime_dir.resolve()),
                output_dir=str(output_dir.resolve()),
                timed_out=True,
                result_json_error="Sandbox execution timed out",
                input_files=copied_files,
            )
        except Exception as exc:
            self._write_metadata(
                metadata_path,
                run_id=run_id,
                attempt=attempt,
                input_files=copied_files,
                command=command,
                exit_code=None,
                status="failed",
                timed_out=False,
                result_json_error=str(exc),
            )
            return SandboxExecutionResult(
                status="failed",
                stdout="",
                stderr="",
                exit_code=None,
                result=None,
                charts=[],
                error=str(exc),
                script_path=str(script_path.resolve()),
                runtime_dir=str(runtime_dir.resolve()),
                output_dir=str(output_dir.resolve()),
                timed_out=False,
                result_json_error=str(exc),
                input_files=copied_files,
            )

        stdout = _truncate_output(completed.stdout or "")
        stderr = _truncate_output(completed.stderr or "")
        result_payload, result_error = self._load_result_payload(output_dir / "result.json")
        charts, charts_error = self._collect_charts(output_dir)

        status = "completed"
        error = None
        if completed.returncode != 0:
            status = "failed"
            error = f"Sandbox exited with code {completed.returncode}"
        elif result_error:
            status = "failed"
            error = result_error
        elif charts_error:
            status = "failed"
            error = charts_error

        self._write_metadata(
            metadata_path,
            run_id=run_id,
            attempt=attempt,
            input_files=copied_files,
            command=command,
            exit_code=completed.returncode,
            status=status,
            timed_out=False,
            result_json_error=result_error,
        )

        return SandboxExecutionResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=completed.returncode,
            result=result_payload,
            charts=charts,
            error=error,
            script_path=str(script_path.resolve()),
            runtime_dir=str(runtime_dir.resolve()),
            output_dir=str(output_dir.resolve()),
            timed_out=False,
            result_json_error=result_error,
            input_files=copied_files,
        )

    def cleanup_run(self, runtime_dir: str | Path) -> None:
        if self.config.keep_runs:
            return
        shutil.rmtree(Path(runtime_dir), ignore_errors=True)

    def plan_input_filenames(
        self,
        file_paths: list[str],
        *,
        sandbox_filenames: list[str] | None = None,
    ) -> list[str]:
        if sandbox_filenames is not None and len(sandbox_filenames) != len(file_paths):
            raise ValueError("sandbox_filenames must match file_paths length")
        used_names: dict[str, int] = {}
        planned: list[str] = []
        for index, file_path in enumerate(file_paths):
            preferred_name = sandbox_filenames[index] if sandbox_filenames is not None else Path(file_path).name
            planned.append(self._make_safe_basename(preferred_name, used_names))
        return planned

    def _prepare_output_directory(self, output_dir: Path) -> None:
        if os.name != "nt":
            output_dir.chmod(0o777)

    def _copy_input_files(
        self,
        *,
        file_paths: list[str],
        input_dir: Path,
        sandbox_filenames: list[str] | None,
    ) -> list[str]:
        if sandbox_filenames is not None and len(sandbox_filenames) != len(file_paths):
            raise ValueError("sandbox_filenames must match file_paths length")

        used_names: dict[str, int] = {}
        copied_files: list[str] = []

        for index, file_path in enumerate(file_paths):
            source = Path(file_path)
            if not source.exists():
                raise FileNotFoundError(str(source))
            if source.is_symlink():
                raise ValueError(f"Symlink inputs are not allowed: {source}")
            if not source.is_file():
                raise ValueError(f"Input must be a regular file: {source}")

            preferred_name = sandbox_filenames[index] if sandbox_filenames is not None else source.name
            safe_name = self._make_safe_basename(preferred_name, used_names)
            destination = input_dir / safe_name
            shutil.copy2(source, destination)
            copied_files.append(safe_name)

        return copied_files

    def _make_safe_basename(self, preferred_name: str, used_names: dict[str, int]) -> str:
        candidate = Path(preferred_name).name
        if not candidate or ".." in candidate:
            raise ValueError(f"Unsafe input filename: {preferred_name}")

        stem = Path(candidate).stem
        suffix = Path(candidate).suffix
        safe_stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem).strip("._-") or "file"
        safe_suffix = re.sub(r"[^A-Za-z0-9.]", "", suffix)
        safe_name = f"{safe_stem}{safe_suffix}"
        if not SAFE_BASENAME_PATTERN.fullmatch(safe_name):
            raise ValueError(f"Unsafe input filename: {preferred_name}")

        version = used_names.get(safe_name, 0) + 1
        used_names[safe_name] = version
        if version == 1:
            return safe_name
        return f"{safe_stem}_{version}{safe_suffix}"

    def _build_command(self, *, input_dir: Path, output_dir: Path, script_path: Path) -> list[str]:
        return [
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
            str(self.config.pids_limit),
            "--memory",
            self.config.memory_limit,
            "--cpus",
            self.config.cpu_limit,
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=512m",
            "--user",
            f"{SANDBOX_UID}:{SANDBOX_GID}",
            "-v",
            f"{input_dir.resolve()}:/mnt/data:ro",
            "-v",
            f"{output_dir.resolve()}:/mnt/output:rw",
            "-v",
            f"{script_path.resolve()}:/workspace/analysis.py:ro",
            self.config.image,
            "python",
            "/workspace/analysis.py",
        ]

    def _load_result_payload(self, result_path: Path) -> tuple[dict | None, str | None]:
        if not result_path.exists():
            return None, "result.json is missing"
        if result_path.is_symlink():
            return None, "result.json must not be a symlink"
        if not result_path.is_file():
            return None, "result.json must be a regular file"
        if result_path.stat().st_size > MAX_RESULT_JSON_BYTES:
            return None, "result.json exceeds the size limit"

        try:
            parsed = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return None, f"result.json is not valid JSON: {exc.msg}"
        if not isinstance(parsed, dict):
            return None, "result.json top-level value must be an object"
        return parsed, None

    def _collect_charts(self, output_dir: Path) -> tuple[list[str], str | None]:
        charts = sorted(output_dir.glob("*.png"))
        if len(charts) > MAX_PNG_COUNT:
            return [], "Too many PNG charts were produced"

        collected: list[str] = []
        for chart_path in charts:
            if chart_path.is_symlink():
                return [], f"PNG chart must not be a symlink: {chart_path.name}"
            if not chart_path.is_file():
                return [], f"PNG chart must be a regular file: {chart_path.name}"
            if chart_path.stat().st_size > MAX_PNG_BYTES:
                return [], f"PNG chart exceeds the size limit: {chart_path.name}"
            collected.append(str(chart_path.resolve()))
        return collected, None

    def _write_metadata(
        self,
        metadata_path: Path,
        *,
        run_id: str,
        attempt: int,
        input_files: list[str],
        command: list[str],
        exit_code: int | None,
        status: str,
        timed_out: bool,
        result_json_error: str | None,
    ) -> None:
        payload = {
            "run_id": run_id,
            "attempt": attempt,
            "input_files": input_files,
            "command": command,
            "config": {
                **asdict(self.config),
                "runtime_root": str(self.config.runtime_root),
            },
            "exit_code": exit_code,
            "status": status,
            "timed_out": timed_out,
            "result_json_error": result_json_error,
        }
        metadata_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
