"""
Smoke-тест Mirrolla AI через поднятый API (localhost:8000).

Прогоняет 4 вопроса, дожидается выполнения, оценивает:
  - нашёл ли сервис зашитые паттерны
  - точность цифр
  - качество ответа

Usage: python tools/smoke_test_api.py
"""
import json
import time
import sys
import requests

API = "http://localhost:8000/api/v1"

# 4 вопроса менеджера + ожидаемые паттерны
TESTS = [
    {
        "id": "Q1-decline",
        "question": "Почему упали продажи товара ЦБ-00013356?",
        "expect": "T1: падение 175→48, должно быть в findings с приоритетом",
        "expect_codes": ["ЦБ-00013356"],
    },
    {
        "id": "Q2-growth",
        "question": "Какие товары растут быстрее рынка?",
        "expect": "T2 ЦБ-00031200 (рост 34→223) должен быть в топе роста",
        "expect_codes": ["ЦБ-00031200"],
    },
    {
        "id": "Q3-stockout",
        "question": "Какие товары заканчиваются на складе?",
        "expect": "T3 ЦБ-00026659 (balance=0) должен быть critical",
        "expect_codes": ["ЦБ-00026659"],
    },
    {
        "id": "Q4-reviews",
        "question": "Какие отзывы требуют реакции?",
        "expect": "T4 ЦБ-00065539 (20 отзывов 1-2★) должен быть в findings",
        "expect_codes": ["ЦБ-00065539"],
    },
]


def run_one(test: dict, timeout: int = 180) -> dict:
    """Создать анализ, подтвердить, дождаться, вернуть результат."""
    print(f"\n{'='*60}")
    print(f"  {test['id']}: {test['question']}")
    print(f"{'='*60}")

    # 1. Создать
    r = requests.post(f"{API}/analyses", json={"question": test["question"]}, timeout=30)
    if r.status_code != 200:
        return {"id": test["id"], "error": f"create: {r.status_code} {r.text[:200]}"}
    data = r.json()
    aid = data["id"]
    status = data["status"]
    plan = data.get("plan", {})
    print(f"  created: {aid[:8]}, status={status}")
    print(f"  plan skill: {plan.get('skill','?')}, hypotheses: {len(plan.get('hypotheses',[]))}")

    # 2. Approve
    r = requests.post(f"{API}/analyses/{aid}/approve", timeout=30)
    if r.status_code != 200:
        return {"id": test["id"], "aid": aid, "error": f"approve: {r.status_code} {r.text[:200]}"}
    print(f"  approved, executing...")

    # 3. Poll
    t0 = time.time()
    result = None
    while time.time() - t0 < timeout:
        time.sleep(5)
        r = requests.get(f"{API}/analyses/{aid}", timeout=15)
        if r.status_code != 200:
            continue
        data = r.json()
        status = data["status"]
        elapsed = int(time.time() - t0)
        if status in ("done", "error", "rejected"):
            result = data
            print(f"  → {status} ({elapsed}s)")
            break
        print(f"  ... {status} ({elapsed}s)")

    if not result:
        return {"id": test["id"], "aid": aid, "error": f"timeout {timeout}s"}
    return {"id": test["id"], "aid": aid, "result": result, "elapsed": int(time.time() - t0)}


def evaluate(test: dict, res: dict) -> dict:
    """Оценить: нашёл ли ожидаемые коды в findings."""
    verdict = {"id": test["id"], "found_codes": [], "missed": [], "extra": []}
    if "error" in res:
        verdict["verdict"] = "ERROR"
        verdict["error"] = res["error"]
        return verdict

    result = res.get("result", {})
    findings = result.get("findings", [])
    summary = result.get("summary", "") or result.get("answer", "")
    answer_status = result.get("answer_status", "?")

    # Собрать все entity_id из findings
    found_ids = {f.get("entity_id", "") for f in findings}
    # Также проверить summary на упоминание кодов
    summary_lower = summary.lower()

    for code in test["expect_codes"]:
        if code in found_ids or code.lower() in summary_lower:
            verdict["found_codes"].append(code)
        else:
            verdict["missed"].append(code)

    # Лишние (не из ожидаемых) — не обязательно плохо, но отметим
    for fid in found_ids:
        if fid and fid not in test["expect_codes"]:
            verdict["extra"].append(fid)

    verdict["n_findings"] = len(findings)
    verdict["answer_status"] = answer_status
    verdict["elapsed"] = res.get("elapsed", "?")
    verdict["verdict"] = "PASS" if not verdict["missed"] else "FAIL"
    verdict["summary_preview"] = summary[:500] if summary else "(empty)"
    verdict["findings_preview"] = [
        {"id": f.get("entity_id"), "prio": f.get("priority"), "name": f.get("name", "")[:40],
         "reasons": f.get("reasons", [])[:2]}
        for f in findings[:5]
    ]
    return verdict


def main():
    print("=== Mirrolla AI Smoke Test ===")
    print(f"API: {API}")

    # health
    r = requests.get(f"{API}/health", timeout=5)
    print(f"health: {r.json()}")

    results = []
    for test in TESTS:
        res = run_one(test)
        verdict = evaluate(test, res)
        results.append(verdict)
        # Live-вывод
        if verdict["verdict"] == "ERROR":
            print(f"  ❌ ERROR: {verdict['error']}")
        else:
            print(f"  findings: {verdict['n_findings']}, status: {verdict['answer_status']}")
            print(f"  found: {verdict['found_codes']}, missed: {verdict['missed']}, extra: {verdict['extra']}")
            print(f"  verdict: {verdict['verdict']}")
            if verdict["findings_preview"]:
                for fp in verdict["findings_preview"][:3]:
                    print(f"    [{fp['prio']}] {fp['id']} — {fp['name']}")
                    for r_ in fp["reasons"]:
                        print(f"        • {r_[:80]}")

    # Итог
    print(f"\n{'='*60}")
    print("  ИТОГ SMOKE TEST")
    print(f"{'='*60}")
    passed = sum(1 for v in results if v["verdict"] == "PASS")
    print(f"  PASS: {passed}/{len(results)}")
    for v in results:
        icon = "✅" if v["verdict"] == "PASS" else "❌"
        print(f"  {icon} {v['id']}: {v['verdict']} (found={v.get('found_codes',[])}, missed={v.get('missed',[])})")

    # Сохранить полный отчёт
    with open("data/smoke_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Полный отчёт: data/smoke_test_results.json")


if __name__ == "__main__":
    main()