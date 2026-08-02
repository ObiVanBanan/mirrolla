from __future__ import annotations

import os

from agent.ci_runner import CIRunner
from agent.runtime.analysis_runner import AnalysisRunner
from agent.runtime.local_qwen_runner import LocalQwenRunner


def create_analysis_runner() -> AnalysisRunner:
    backend = os.getenv("EXECUTION_BACKEND", "local_qwen").strip().lower()
    if backend == "local_qwen":
        return LocalQwenRunner()
    if backend == "openai_ci":
        return CIRunner()
    raise ValueError(f"Unknown execution backend: {backend}")
