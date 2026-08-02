from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from agent.runtime.docker_sandbox import DockerSandbox


def test_execute_uses_restricted_docker_flags(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    sandbox.execute("print('ok')", [str(input_file)])

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert "--network" in command and "none" in command
    assert "--read-only" in command
    assert "--cap-drop" in command and "ALL" in command
    assert "--security-opt" in command and "no-new-privileges" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 120


def test_execute_mounts_input_output_and_script_paths(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    sandbox.execute("print('ok')", [str(input_file)])

    command = captured["command"]
    mount_args = [command[index + 1] for index, item in enumerate(command) if item == "-v"]
    assert any(arg.endswith(":/mnt/data:ro") for arg in mount_args)
    assert any(arg.endswith(":/mnt/output:rw") for arg in mount_args)
    assert any(arg.endswith(":/mnt/script/analysis.py:ro") for arg in mount_args)


def test_execute_handles_timeout(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"], output="a" * 10, stderr="b" * 10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    result = sandbox.execute("print('ok')", [str(input_file)])

    assert result.status == "timeout"
    assert result.error == "Sandbox execution timed out"


def test_execute_returns_exit_code_and_result_json(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        output_mount = next(command[index + 1] for index, item in enumerate(command) if item == "-v" and command[index + 1].endswith(":/mnt/output:rw"))
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text(json.dumps({"answer": 1}), encoding="utf-8")
        (output_dir / "chart.png").write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    result = sandbox.execute("print('ok')", [str(input_file)])

    assert result.status == "completed"
    assert result.result == {"answer": 1}
    assert len(result.charts) == 1
    assert result.exit_code == 0


def test_execute_truncates_stdout_and_stderr(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="x" * 25000, stderr="y" * 25000)

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    result = sandbox.execute("print('ok')", [str(input_file)])

    assert result.status == "failed"
    assert result.stdout.endswith("...[truncated]...")
    assert result.stderr.endswith("...[truncated]...")


def test_execute_rejects_invalid_result_json(monkeypatch, tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("value\n1\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        output_mount = next(command[index + 1] for index, item in enumerate(command) if item == "-v" and command[index + 1].endswith(":/mnt/output:rw"))
        output_dir = Path(output_mount.rsplit(":", 2)[0])
        (output_dir / "result.json").write_text("{broken", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    result = sandbox.execute("print('ok')", [str(input_file)])

    assert result.status == "failed"
    assert result.result is None
    assert "not valid JSON" in (result.error or "")


def test_execute_rejects_symlink_input(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "input.csv"
    source.write_text("value\n1\n", encoding="utf-8")

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(self: Path) -> bool:
        if self == source:
            return True
        return original_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    sandbox = DockerSandbox(runtime_root=str(tmp_path / "runtime"))

    result = sandbox.execute("print('ok')", [str(source)])

    assert result.status == "failed"
    assert "Symlink inputs are not allowed" in (result.error or "")
