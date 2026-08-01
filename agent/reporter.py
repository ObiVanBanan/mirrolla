"""
Reporter LLM: turns findings into a user-facing answer.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from agent.schemas import AnalysisMode, Finding, SkillType

load_dotenv()

MODEL_NAME = os.getenv("REPORTER_MODEL", "gpt-4o")
API_KEY = os.getenv("token", "")

REPORTER_PROMPT = """Ты — аналитик Mirrolla.

Ответь на исходный вопрос пользователя, используя только предоставленный JSON анализа.

Правила:
- отвечай прямо на вопрос;
- не придумывай данные, которых нет;
- для general не добавляй бизнес-рекомендации без запроса;
- для specialized можно опираться на findings и действия из результата;
- если данных не хватает, коротко объясни ограничение;
- пиши по-русски.
"""


def synthesize(
    question: str,
    skill: SkillType | None,
    analysis_mode: AnalysisMode,
    findings: list[Finding],
    limitations: list[str],
    answer_status: str = "answered",
    ci_answer: str = "",
) -> str:
    if not API_KEY:
        return _fallback_synthesize(
            question,
            skill,
            analysis_mode,
            findings,
            limitations,
            answer_status,
            ci_answer,
        )

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=MODEL_NAME,
            api_key=API_KEY,
            temperature=0.2,
        )
        payload = {
            "question": question,
            "analysis_mode": analysis_mode.value,
            "skill": skill.value if skill is not None else None,
            "answer_status": answer_status,
            "findings": [finding.model_dump() for finding in findings],
            "limitations": limitations,
            "ci_answer": ci_answer,
        }
        response = llm.invoke(
            [
                {"role": "system", "content": REPORTER_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ]
        )
        return response.content
    except Exception:
        return _fallback_synthesize(
            question,
            skill,
            analysis_mode,
            findings,
            limitations,
            answer_status,
            ci_answer,
        )


def _fallback_synthesize(
    question: str,
    skill: SkillType | None,
    analysis_mode: AnalysisMode,
    findings: list[Finding],
    limitations: list[str],
    answer_status: str,
    ci_answer: str,
) -> str:
    if ci_answer and analysis_mode == AnalysisMode.GENERAL:
        return ci_answer
    if not findings:
        if ci_answer:
            return ci_answer
        return f"Не удалось сформировать ответ. Статус: {answer_status}."

    lines = [f"### Ответ на вопрос: {question}", ""]
    if analysis_mode == AnalysisMode.GENERAL:
        lines.append(f"Найдено результатов: {len(findings)}.")
    else:
        mode_line = "Специализированный анализ"
        if skill is not None:
            mode_line += f" ({skill.value})"
        lines.append(mode_line)
        lines.append("")

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda item: priority_order.get(item.priority, 4))
    for index, finding in enumerate(sorted_findings[:5], 1):
        lines.append(f"{index}. {finding.entity_id} — {finding.name}")
        for reason in finding.reasons[:2]:
            lines.append(f"- {reason}")
        if finding.recommended_action and analysis_mode == AnalysisMode.SPECIALIZED:
            lines.append(f"- Действие: {finding.recommended_action}")

    if limitations:
        lines.append("")
        lines.append("Ограничения:")
        for limitation in limitations[:3]:
            lines.append(f"- {limitation}")

    return "\n".join(lines)
