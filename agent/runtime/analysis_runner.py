from __future__ import annotations

from typing import Protocol


class AnalysisRunner(Protocol):
    def run_analysis(
        self,
        prompt: str,
        file_paths: list[str],
        max_retries: int = 2,
    ) -> dict:
        ...
