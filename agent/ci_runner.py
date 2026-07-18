"""
agent/ci_runner.py — OpenAI Code Interpreter runner (Responses API).

Использует responses.create с tool code_interpreter и container auto.
Файлы загружаются через files.create(purpose='user_data') и передаются
в container.file_ids — Code Interpreter монтирует их в /mnt/data/.

Responses API — актуальный путь в OpenAI 2.x. Assistants API deprecated
и не работает с файлами корректно.
"""

import os
import time
import json
import shutil
import tempfile
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("token", "")
MODEL_NAME = os.getenv("EXECUTOR_MODEL", "gpt-4o-mini")

# Таймаут ожидания выполнения (секунды)
RUN_TIMEOUT = 300  # 5 минут
POLL_INTERVAL = 3

# Директория для скачанных файлов (графиков)
CHARTS_DIR = os.path.join("data", "charts")


# === Маппинг русских имён в ASCII ===
# Code Interpreter sandbox монтирует файлы под именами file-<id>,
# но в instructions нам нужно ссылаться на оригинальные имена.
# Передаём маппинг в prompt.
ASCII_NAMES = {
    "озон 17.03-16.04.xlsx": "ozon_1.xlsx",
    "озон 17.04-16.05.xlsx": "ozon_2.xlsx",
    "озон 17.05-16.06.xlsx": "ozon_3.xlsx",
    "Отзывы ВБ 17.03-17.06.2026.xlsx": "wb_reviews.xlsx",
    "products.json": "products.json",
    "balances.json": "balances.json",
}


class CIRunner:
    """OpenAI Code Interpreter runner (Responses API)."""

    def __init__(self):
        if not API_KEY:
            raise ValueError("API ключ не найден. Установите token в .env")

        self.client = OpenAI(api_key=API_KEY)
        self.file_ids: list[str] = []  # загруженные file_id
        self.file_names: dict[str, str] = {}  # file_id → ascii_name (для prompt)

    def _ensure_dirs(self):
        os.makedirs(CHARTS_DIR, exist_ok=True)

    def upload_files(self, file_paths: list[str]) -> list[str]:
        """
        Загрузить файлы данных в OpenAI через files.create(purpose='user_data').

        Args:
            file_paths: пути к .xlsx/.json файлам.

        Returns:
            list of file IDs.
        """
        print(f"  [CI] Загрузка {len(file_paths)} файлов...")
        file_ids = []

        temp_dir = tempfile.mkdtemp()

        for path in file_paths:
            if not os.path.exists(path):
                print(f"  [CI] ⚠ Файл не найден: {path}")
                continue
            filename = os.path.basename(path)
            ascii_name = ASCII_NAMES.get(filename, filename)

            # Копируем в temp с ASCII именем (на всякий случай — некоторые API
            # плохо переваривают кириллицу в именах)
            temp_path = os.path.join(temp_dir, ascii_name)
            shutil.copy2(path, temp_path)

            with open(temp_path, "rb") as f:
                file_obj = self.client.files.create(
                    file=f,
                    purpose="user_data",
                )
            file_ids.append(file_obj.id)
            self.file_names[file_obj.id] = ascii_name
            print(f"  [CI] ✅ {filename} → {ascii_name} → {file_obj.id}")

        shutil.rmtree(temp_dir, ignore_errors=True)

        self.file_ids = file_ids
        return file_ids

    def _build_file_mapping(self) -> str:
        """Построить текстовое описание: какой файл под каким именем в sandbox."""
        if not self.file_names:
            return ""
        lines = ["Файлы в sandbox (/mnt/data/):"]
        for fid, name in self.file_names.items():
            lines.append(f"- {name} → /mnt/data/{fid}")
        return "\n".join(lines)

    def run_analysis(
        self,
        prompt: str,
        file_paths: list[str],
        max_retries: int = 2,
    ) -> dict:
        """
        Полный цикл: upload → responses.create(code_interpreter) → extract → cleanup.
        С встроенным self-correction через previous_response_id (без перезагрузки файлов).

        Args:
            prompt: полный prompt для Code Interpreter.
            file_paths: пути к файлам данных.
            max_retries: максимум попыток если JSON невалидный.

        Returns:
            dict: {status, text, charts, error}
        """
        self._ensure_dirs()

        # Шаг 1: Upload
        self.upload_files(file_paths)
        if not self.file_ids:
            return {
                "status": "failed",
                "error": "Не удалось загрузить файлы",
                "text": "",
                "charts": [],
            }

        # Шаг 2: Дополнить prompt маппингом файлов
        file_mapping = self._build_file_mapping()
        full_prompt = f"{prompt}\n\n## Расположение файлов в sandbox\n{file_mapping}"

        # Шаг 3: Responses API + code_interpreter, с self-correction
        print(f"  [CI] Запуск Code Interpreter через Responses API (timeout={RUN_TIMEOUT}s)...")
        print(f"  [CI] Prompt: {len(full_prompt)} символов, файлов: {len(self.file_ids)}")

        response_id = None
        text_parts = []
        chart_paths = []
        status = "failed"
        error_msg = ""

        for attempt in range(1, max_retries + 1):
            print(f"  [CI] Попытка {attempt}/{max_retries}...")

            try:
                if attempt == 1:
                    # Первая попытка — с файлами
                    response = self.client.responses.create(
                        model=MODEL_NAME,
                        tools=[{
                            "type": "code_interpreter",
                            "container": {"type": "auto", "file_ids": self.file_ids},
                        }],
                        input=[{"role": "user", "content": full_prompt}],
                        max_output_tokens=16000,
                    )
                else:
                    # Self-correction — продолжаем тот же диалог
                    correction_msg = (
                        "Предыдущий ответ не содержит валидный JSON с findings. "
                        "Выполни анализ полностью и в конце обязательно выведи: "
                        "print(json.dumps(result, ensure_ascii=False, indent=2, default=str)) "
                        "где result — dict с ключами answer_status, answer, findings (массив!), "
                        "limitations. Каждый finding: entity_type, entity_id, name, priority, "
                        "reasons, metrics, recommended_action. "
                        "Проверь КАЖДУЮ гипотезу и верни до 20 findings."
                    )
                    response = self.client.responses.create(
                        model=MODEL_NAME,
                        previous_response_id=response_id,
                        input=[{"role": "user", "content": correction_msg}],
                        max_output_tokens=16000,
                    )
            except Exception as e:
                print(f"  [CI] ❌ Responses API error: {e}")
                self._cleanup_files()
                return {
                    "status": "failed",
                    "error": f"Responses API: {e}",
                    "text": "",
                    "charts": [],
                }

            response_id = response.id
            print(f"  [CI] Response status: {response.status}")

            # Извлечь результаты
            text_parts = []
            chart_paths = []

            for item in response.output:
                if item.type == "code_interpreter_call":
                    # Логируем код для отладки
                    code = getattr(item, "code", "")
                    if code:
                        print(f"  [CI] 📝 Code ({len(code)} chars):")
                        for line in code.split("\n")[:8]:
                            print(f"       {line}")
                        if len(code.split("\n")) > 8:
                            print(f"       ... ({len(code.split(chr(10)))} lines total)")
                    outs = getattr(item, "outputs", []) or []
                    for out in outs:
                        if out.type == "file":
                            chart_path = self._download_file(out.file.file_id, out.file.filename)
                            if chart_path:
                                chart_paths.append(chart_path)
                        elif out.type == "logs":
                            logs = out.logs[:300] if out.logs else ""
                            if logs:
                                print(f"  [CI] 📤 Logs: {logs}")
                elif item.type == "message":
                    for b in item.content:
                        if b.type == "output_text":
                            text_parts.append(b.text)

            full_text = "\n\n".join(text_parts)
            print(f"  [CI] Текст: {len(full_text)} символов, графиков: {len(chart_paths)}")

            # Проверка: есть ли JSON с findings или hypothesis_results?
            has_json = "findings" in full_text or "hypothesis_results" in full_text
            if has_json:
                print(f"  [CI] ✅ JSON найден в ответе")
                status = "completed"
                break
            else:
                print(f"  [CI] ⚠ JSON не найден в ответе")
                if attempt < max_retries:
                    print(f"  [CI] → self-correction через previous_response_id...")
                else:
                    status = "completed"  # возвращаем что есть
                    error_msg = "JSON с findings/hypothesis_results не найден после всех попыток"

        # Шаг 4: Cleanup загруженных файлов
        self._cleanup_files()

        return {
            "status": status,
            "text": "\n\n".join(text_parts),
            "charts": chart_paths,
            "error": error_msg,
        }

    def _download_file(self, file_id: str, filename: str) -> Optional[str]:
        """Скачать файл (график) из OpenAI."""
        try:
            content = self.client.files.content(file_id)
            # Нормализуем имя файла
            safe_name = filename or f"chart_{file_id[:8]}.png"
            if not safe_name.endswith(".png"):
                safe_name += ".png"
            path = os.path.join(CHARTS_DIR, safe_name)
            content.write_to_file(path)
            print(f"  [CI] 📊 График: {path}")
            return path
        except Exception as e:
            print(f"  [CI] ⚠ Не удалось скачать файл {file_id}: {e}")
            return None

    def _cleanup_files(self):
        """Удалить загруженные файлы из OpenAI."""
        for fid in self.file_ids:
            try:
                self.client.files.delete(fid)
            except Exception:
                pass
        self.file_ids = []
        self.file_names = {}