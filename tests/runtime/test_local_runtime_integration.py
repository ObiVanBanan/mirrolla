from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent.runtime.local_qwen_runner import LocalQwenRunner


pytestmark = pytest.mark.local_runtime


def test_local_runtime_end_to_end(tmp_path: Path) -> None:
    if os.getenv("RUN_LOCAL_RUNTIME_TESTS") != "1":
        pytest.skip("RUN_LOCAL_RUNTIME_TESTS is not enabled")

    subprocess.run(
        ["docker", "image", "inspect", "mirrolla-analysis-sandbox:py312"],
        check=True,
        capture_output=True,
        text=True,
    )

    dataset_path = tmp_path / "numbers.csv"
    with dataset_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerow(["A", 1])
        writer.writerow(["B", 2])
        writer.writerow(["C", 3])

    runner = LocalQwenRunner()
    result = runner.run_analysis(
        (
            "В CSV есть колонки name и value. "
            "Посчитай количество строк данных и сумму колонки value. "
            "Используй имена колонок из заголовка CSV, не индексы. "
            "В строковом answer явно укажи оба числа: row_count=3 и value_sum=6. "
            "Верни result.json c answer_status='answered', коротким строковым answer и findings как JSON-списком."
        ),
        [str(dataset_path)],
        max_retries=2,
    )

    assert result["status"] == "completed"
    assert result["text"]
    payload = json.loads(result["text"])
    assert payload["answer_status"] == "answered"
    assert "3" in payload["answer"]
    assert "6" in payload["answer"]
