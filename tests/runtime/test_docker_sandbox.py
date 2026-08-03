from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from agent.runtime.docker_sandbox import (
    DockerSandbox,
    MAX_OUTPUT_CHARS,
    MAX_PNG_BYTES,
    MAX_RESULT_JSON_BYTES,
    SandboxConfig,
    load_sandbox_config,
)


def _config(tmp_path: Path, *, keep_runs: bool = False) -> SandboxConfig:
    return SandboxConfig(
        image="mirrolla-analysis-sandbox:py312",
        timeout_seconds=180,
        memory_limit="4g",
        cpu_limit="2",
        pids_limit=128,
        runtime_root=tmp_path / "runtime",
        keep_runs=keep_runs,
    )


def test_load_sandbox_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_SANDBOX_IMAGE", "sandbox:test")
    monkeypatch.setenv("LOCAL_SANDBOX_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LOCAL_SANDBOX_MEMORY", "1g")
    monkeypatch.setenv("LOCAL_SANDBOX_CPUS", "0.5")
    monkeypatch.setenv("LOCAL_SANDBOX_PIDS_LIMIT", "64")
    monkeypatch.setenv("LOCAL_SANDBOX_ROOT", ".runtime/custom")
    monkeypatch.setenv("LOCAL_SANDBOX_KEEP_RUNS", "1")

    config = load_sandbox_config()

    assert config.image == "sandbox:test"
    assert config.timeout_seconds == 30
    assert config.memory_limit == "1g"
    assert config.cpu_limit == "0.5"
    assert config.pids_limit == 64
    assert config.runtime_root == Path(".runtime/custom")
    assert config.keep_runs is True


def test_execute_uses_restricted_docker_flags(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    sandbox.execute("print('ok')", [str(input_file)], run_id="run-1", attempt=2)

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert "--network" in command and "none" in command
    assert "--read-only" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "--security-opt" in command and "no-new-privileges" in command
    assert "--pids-limit" in command and "128" in command
    assert "--memory" in command and "4g" in command
    assert "--cpus" in command and "2" in command
    assert "--tmpfs" in command and "/tmp:rw,nosuid,nodev,size=512m" in command
    assert "--user" in command and "10001:10001" in command
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is False


def test_execute_mounts_input_output_and_attempt_script(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-2", attempt=3)

    command = captured["command"]
    mount_args = [command[index + 1] for index, item in enumerate(command) if item == "-v"]
    assert any(arg.endswith(":/mnt/data:ro") for arg in mount_args)
    assert any(arg.endswith(":/mnt/output:rw") for arg in mount_args)
    assert any(arg.endswith(":/workspace/analysis.py:ro") for arg in mount_args)
    assert result.script_path.endswith("attempt_3.py")


def test_execute_prepares_output_directory_for_writes(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    chmod_calls: list[int] = []
    original_chmod = Path.chmod

    def fake_chmod(self: Path, mode: int) -> None:
        chmod_calls.append(mode)
        return original_chmod(self, mode)

    def fake_run(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "chmod", fake_chmod)
    monkeypatch.setattr(os, "name", "posix")
    sandbox = DockerSandbox(config=_config(tmp_path))

    sandbox.execute("print('ok')", [str(input_file)], run_id="run-3", attempt=1)

    assert 0o777 in chmod_calls


def test_execute_handles_timeout(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"], output="a" * 10, stderr="b" * 10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-timeout", attempt=1)

    assert result.status == "failed"
    assert result.timed_out is True
    assert result.error == "Sandbox execution timed out"


def test_execute_uses_safe_duplicate_basenames(monkeypatch, tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "sales report.csv"
    second = second_dir / "sales report.csv"
    first.write_text("value\n1\n", encoding="utf-8")
    second.write_text("value\n2\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        input_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/data:ro")
        )
        input_dir = Path(input_mount.rsplit(":", 2)[0])
        assert sorted(path.name for path in input_dir.iterdir()) == ["sales_report.csv", "sales_report_2.csv"]
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(first), str(second)], run_id="run-dupes", attempt=1)

    metadata = json.loads((Path(result.runtime_dir) / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["input_files"] == ["sales_report.csv", "sales_report_2.csv"]


def test_execute_rejects_missing_result_json(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-no-result", attempt=1)

    assert result.status == "failed"
    assert result.error == "result.json is missing"


def test_execute_rejects_input_directory(monkeypatch, tmp_path: Path) -> None:
    input_dir = tmp_path / "input-dir"
    input_dir.mkdir()
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_dir)], run_id="run-dir", attempt=1)

    assert result.status == "failed"
    assert "Input must be a regular file" in (result.error or "")


def test_execute_rejects_result_json_symlink(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    original_is_symlink = Path.is_symlink

    def fake_run(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    def fake_is_symlink(self: Path) -> bool:
        if self.name == "result.json":
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-link", attempt=1)

    assert result.status == "failed"
    assert "must not be a symlink" in (result.error or "")


def test_execute_rejects_large_and_non_object_result_json(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    sandbox = DockerSandbox(config=_config(tmp_path))

    def fake_large(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_bytes(b"x" * (MAX_RESULT_JSON_BYTES + 1))
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_large)
    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-large", attempt=1)
    assert result.status == "failed"
    assert "size limit" in (result.error or "")

    def fake_list(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_list)
    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-list", attempt=1)
    assert result.status == "failed"
    assert "top-level value must be an object" in (result.error or "")


def test_execute_rejects_too_many_and_symlink_pngs(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    sandbox = DockerSandbox(config=_config(tmp_path))
    original_is_symlink = Path.is_symlink

    def fake_many_pngs(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        for index in range(11):
            (output_dir / f"chart_{index}.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_many_pngs)
    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-png-many", attempt=1)
    assert result.status == "failed"
    assert "Too many PNG charts" in (result.error or "")

    def fake_symlink_png(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        (output_dir / "chart.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    def fake_is_symlink(self: Path) -> bool:
        if self.name == "chart.png":
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(subprocess, "run", fake_symlink_png)
    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-png-link", attempt=1)
    assert result.status == "failed"
    assert "must not be a symlink" in (result.error or "")


def test_execute_rejects_large_png(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        (output_dir / "chart.png").write_bytes(b"x" * (MAX_PNG_BYTES + 1))
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-png-large", attempt=1)

    assert result.status == "failed"
    assert "size limit" in (result.error or "")


def test_execute_preserves_verified_sandbox_filenames(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "sales.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        input_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/data:ro")
        )
        input_dir = Path(input_mount.rsplit(":", 2)[0])
        captured["files"] = sorted(path.name for path in input_dir.iterdir())
        output_mount = next(
            command[index + 1]
            for index, item in enumerate(command)
            if item == "-v" and command[index + 1].endswith(":/mnt/output:rw")
        )
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    sandbox.execute(
        "print('ok')",
        [str(input_file)],
        run_id="run-safe-name",
        attempt=1,
        sandbox_filenames=["dataset_001.csv"],
    )

    assert captured["files"] == ["dataset_001.csv"]


def test_execute_truncates_stdout_and_stderr_and_writes_attempt_files(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="x" * (MAX_OUTPUT_CHARS + 100), stderr="y" * (MAX_OUTPUT_CHARS + 100))

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(config=_config(tmp_path))

    result = sandbox.execute("print('ok')", [str(input_file)], run_id="run-output", attempt=4)

    assert result.status == "failed"
    assert result.stdout.endswith("[output truncated]")
    assert result.stderr.endswith("[output truncated]")
    runtime_dir = Path(result.runtime_dir)
    assert (runtime_dir / "attempts" / "attempt_4.stdout.txt").exists()
    assert (runtime_dir / "attempts" / "attempt_4.stderr.txt").exists()
    metadata = json.loads((runtime_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["attempt"] == 4


def test_cleanup_run_respects_keep_runs(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime" / "run-keep"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "marker.txt").write_text("x", encoding="utf-8")

    keep_sandbox = DockerSandbox(config=_config(tmp_path, keep_runs=True))
    keep_sandbox.cleanup_run(runtime_dir)
    assert runtime_dir.exists()

    delete_sandbox = DockerSandbox(config=_config(tmp_path, keep_runs=False))
    delete_sandbox.cleanup_run(runtime_dir)
    assert not runtime_dir.exists()
