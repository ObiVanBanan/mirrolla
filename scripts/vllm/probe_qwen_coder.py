from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import error, request

from agent.runtime.code_parser import GeneratedCodeError, extract_python_code


DEFAULT_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8010/v1")
DEFAULT_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen-coder-local")
DEFAULT_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "mirrolla-local")
OUTPUT_PATH = Path("data/runtime/model_probe.json")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DEFAULT_API_KEY}",
        "Content-Type": "application/json",
    }


def _request_json(method: str, url: str, *, payload: dict | None = None) -> tuple[bool, float, dict | str]:
    started = time.perf_counter()
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=_headers(), method=method)
    try:
        with request.urlopen(req, timeout=90) as response:
            latency_ms = (time.perf_counter() - started) * 1000
            text = response.read().decode("utf-8")
            return True, latency_ms, json.loads(text)
    except error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", errors="replace")
        return False, latency_ms, f"HTTP {exc.code}: {detail[:500]}"
    except json.JSONDecodeError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, f"Invalid JSON response: {exc}"
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, str(exc)


def _extract_message_content(payload: dict) -> str:
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("chat/completions response does not contain choices[0].message.content") from exc


def main() -> int:
    errors: list[str] = []
    probe = {
        "base_url": DEFAULT_BASE_URL,
        "expected_model": DEFAULT_MODEL,
        "models_ok": False,
        "model_present": False,
        "chat_ok": False,
        "python_block_ok": False,
        "latency_ms": {},
        "errors": errors,
    }

    models_ok, latency_ms, models_payload = _request_json("GET", f"{DEFAULT_BASE_URL}/models")
    probe["latency_ms"]["models"] = round(latency_ms, 2)
    probe["models_ok"] = models_ok
    if not models_ok:
        errors.append(f"/models failed: {models_payload}")
    else:
        model_ids = [
            item.get("id")
            for item in models_payload.get("data", [])
            if isinstance(item, dict)
        ]
        probe["available_models"] = model_ids
        probe["model_present"] = DEFAULT_MODEL in model_ids
        if not probe["model_present"]:
            errors.append(f"model '{DEFAULT_MODEL}' not found in /models")

    chat_ok, latency_ms, chat_payload = _request_json(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        payload={
            "model": DEFAULT_MODEL,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Return only one Python code block with a function add(a, b) "
                        "that returns a + b."
                    ),
                }
            ],
        },
    )
    probe["latency_ms"]["chat_completions"] = round(latency_ms, 2)
    probe["chat_ok"] = chat_ok
    if not chat_ok:
        errors.append(f"/chat/completions failed: {chat_payload}")
    else:
        try:
            content = _extract_message_content(chat_payload)
            probe["raw_content_preview"] = content[:200]
            extracted_code = extract_python_code(content)
            probe["python_block_ok"] = True
            probe["extracted_code_preview"] = extracted_code[:200]
        except (ValueError, GeneratedCodeError) as exc:
            errors.append(f"code extraction failed: {exc}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(probe, ensure_ascii=False, indent=2))

    mandatory_checks = (
        probe["models_ok"],
        probe["model_present"],
        probe["chat_ok"],
        probe["python_block_ok"],
    )
    return 0 if all(mandatory_checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
