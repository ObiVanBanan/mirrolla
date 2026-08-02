"""
OpenAI Code Interpreter runner.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("token", "")
MODEL_NAME = os.getenv("EXECUTOR_MODEL", "gpt-4o-mini")
CHARTS_DIR = os.path.join("data", "charts")

ASCII_NAMES = {
    "РѕР·РѕРЅ 17.03-16.04.xlsx": "ozon_1.xlsx",
    "РѕР·РѕРЅ 17.04-16.05.xlsx": "ozon_2.xlsx",
    "РѕР·РѕРЅ 17.05-16.06.xlsx": "ozon_3.xlsx",
    "РћС‚Р·С‹РІС‹ Р’Р‘ 17.03-17.06.2026.xlsx": "wb_reviews.xlsx",
    "products.json": "products.json",
    "balances.json": "balances.json",
}


class CIRunner:
    def __init__(self):
        if not API_KEY:
            raise ValueError("API key is not configured")
        self.client = OpenAI(api_key=API_KEY)
        self.file_ids: list[str] = []
        self.file_names: dict[str, str] = {}

    def _ensure_dirs(self) -> None:
        os.makedirs(CHARTS_DIR, exist_ok=True)

    def upload_files(self, file_paths: list[str]) -> list[str]:
        temp_dir = tempfile.mkdtemp(prefix="mirrolla-ci-")
        self.file_ids = []
        self.file_names = {}
        try:
            for path in file_paths:
                if not os.path.exists(path):
                    raise FileNotFoundError(path)
                filename = os.path.basename(path)
                ascii_name = ASCII_NAMES.get(filename, filename)
                temp_path = os.path.join(temp_dir, ascii_name)
                shutil.copy2(path, temp_path)
                with open(temp_path, "rb") as handle:
                    uploaded = self.client.files.create(file=handle, purpose="user_data")
                self.file_ids.append(uploaded.id)
                self.file_names[uploaded.id] = ascii_name
            if not self.file_ids:
                raise RuntimeError("No files were uploaded to Code Interpreter")
            return list(self.file_ids)
        except Exception:
            self._cleanup_files()
            raise RuntimeError("Failed to upload attached files to Code Interpreter")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_file_mapping(self) -> str:
        if not self.file_names:
            return ""
        lines = ["Files available in sandbox:"]
        for file_id, name in self.file_names.items():
            lines.append(f"- {name} -> /mnt/data/{file_id}")
        return "\n".join(lines)

    def run_analysis(
        self,
        prompt: str,
        file_paths: list[str],
        max_retries: int = 2,
    ) -> dict:
        self._ensure_dirs()
        try:
            self.upload_files(file_paths)
            file_mapping = self._build_file_mapping()
            full_prompt = f"{prompt}\n\n## Sandbox files\n{file_mapping}"
            response = self.client.responses.create(
                model=MODEL_NAME,
                tools=[{
                    "type": "code_interpreter",
                    "container": {"type": "auto", "file_ids": self.file_ids},
                }],
                input=[{"role": "user", "content": full_prompt}],
                max_output_tokens=16000,
            )

            text_parts: list[str] = []
            chart_paths: list[str] = []
            for item in response.output:
                if item.type == "code_interpreter_call":
                    for output in getattr(item, "outputs", []) or []:
                        if output.type == "file":
                            chart_path = self._download_file(output.file.file_id, output.file.filename)
                            if chart_path:
                                chart_paths.append(chart_path)
                elif item.type == "message":
                    for block in item.content:
                        if block.type == "output_text":
                            text_parts.append(block.text)

            return {
                "status": "completed",
                "text": "\n\n".join(text_parts),
                "charts": chart_paths,
                "error": "",
                "code": None,
                "attempts": 1,
            }
        except Exception:
            return {
                "status": "failed",
                "text": "",
                "charts": [],
                "error": "Code Interpreter execution failed",
                "code": None,
                "attempts": 1,
            }
        finally:
            self._cleanup_files()

    def _download_file(self, file_id: str, filename: str) -> Optional[str]:
        try:
            content = self.client.files.content(file_id)
            safe_name = filename or f"chart_{file_id[:8]}.png"
            if not safe_name.endswith(".png"):
                safe_name += ".png"
            path = os.path.join(CHARTS_DIR, safe_name)
            content.write_to_file(path)
            return path
        except Exception:
            return None

    def _cleanup_files(self) -> None:
        for file_id in list(self.file_ids):
            try:
                self.client.files.delete(file_id)
            except Exception:
                pass
        self.file_ids = []
        self.file_names = {}
