from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import requests


DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8010/v1")
DEFAULT_MODEL = os.getenv("VLLM_SERVED_MODEL_NAME", "gemma-4-12b-local")
DEFAULT_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("VLLM_API_KEY", "mirrolla-local")
OUTPUT_PATH = Path("data/runtime/model_probe.json")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {DEFAULT_API_KEY}",
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, *, json_body: dict | None = None) -> tuple[bool, float, str]:
    started = time.perf_counter()
    try:
        response = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            timeout=90,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        if response.ok:
            return True, latency_ms, response.text
        return False, latency_ms, f"HTTP {response.status_code}: {response.text[:500]}"
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return False, latency_ms, str(exc)


def _chat_payload(prompt: str, *, response_format: dict | None = None, tools: list[dict] | None = None) -> dict:
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if tools is not None:
        payload["tools"] = tools
    return payload


def main() -> int:
    errors: list[str] = []
    latencies: list[float] = []

    models_ok, latency, models_text = _request("GET", f"{DEFAULT_BASE_URL}/models")
    latencies.append(latency)
    if not models_ok:
        errors.append(f"/models failed: {models_text}")

    chat_ok, latency, chat_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload("Answer with the word ready."),
    )
    latencies.append(latency)
    if not chat_ok:
        errors.append(f"chat completion failed: {chat_text}")

    ru_ok, latency, ru_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload("Ответь по-русски одним словом: готово."),
    )
    latencies.append(latency)
    if not ru_ok:
        errors.append(f"russian completion failed: {ru_text}")

    code_ok, latency, code_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload("Write a tiny Python function that adds two numbers."),
    )
    latencies.append(latency)
    if not code_ok:
        errors.append(f"python code generation failed: {code_text}")

    json_ok, latency, json_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload(
            "Return a JSON object with keys status and answer.",
            response_format={"type": "json_object"},
        ),
    )
    latencies.append(latency)
    if not json_ok:
        errors.append(f"json_object failed: {json_text}")

    schema_ok, latency, schema_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload(
            "Return a JSON object with status and answer.",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "probe_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "answer": {"type": "string"},
                        },
                        "required": ["status", "answer"],
                        "additionalProperties": False,
                    },
                },
            },
        ),
    )
    latencies.append(latency)
    if not schema_ok:
        errors.append(f"json_schema failed: {schema_text}")

    long_prompt = "Count the number of times the letter A appears. " + ("A" * 9500)
    long_ok, latency, long_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload(long_prompt),
    )
    latencies.append(latency)
    if not long_ok:
        errors.append(f"long prompt failed: {long_text}")

    repeat_ok, latency, repeat_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload("Answer with the word repeated."),
    )
    latencies.append(latency)
    if not repeat_ok:
        errors.append(f"repeat request failed: {repeat_text}")

    tool_ok, latency, tool_text = _request(
        "POST",
        f"{DEFAULT_BASE_URL}/chat/completions",
        json_body=_chat_payload(
            "Call the ping tool.",
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Ping the runtime",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            ],
        ),
    )
    latencies.append(latency)
    if not tool_ok:
        errors.append(f"tool calling probe failed: {tool_text}")

    payload = {
        "server_reachable": models_ok,
        "model": DEFAULT_MODEL,
        "chat_completion": chat_ok,
        "russian_completion": ru_ok,
        "python_code_generation": code_ok,
        "json_object": json_ok,
        "json_schema": schema_ok,
        "tool_calling": tool_ok,
        "long_prompt": long_ok,
        "repeat_request": repeat_ok,
        "average_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0,
        "errors": errors,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if models_ok and chat_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
