import os
import re
from typing import Any, Dict, List, Optional

import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_MODEL = os.getenv("OPENAI_API_MODEL", "gpt-3.5-turbo").strip()
OPENAI_API_TIMEOUT = int(os.getenv("OPENAI_API_TIMEOUT", "15"))
OPENAI_ACTIVITY_SUGGESTIONS = os.getenv("OPENAI_ACTIVITY_SUGGESTIONS", "0").strip().lower() in {"1", "true", "yes", "on"}


def is_llm_enabled() -> bool:
    return bool(OPENAI_API_KEY)


def activity_suggestions_enabled() -> bool:
    return is_llm_enabled() and OPENAI_ACTIVITY_SUGGESTIONS


def _clean_output(text: str) -> List[str]:
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- ") or line.startswith("• "):
            line = line[2:].strip()
        line = re.sub(r"^\d+[\.).]\s*", "", line)
        if line:
            lines.append(line)
    return lines


def _truncate_text(text: str, max_chars: int = 1600) -> str:
    if len(text or "") <= max_chars:
        return text or ""
    return text[:max_chars].rstrip() + "\n...[truncated]"


def _openai_chat_completion(messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OpenAI API key is not configured.")
    url = f"{OPENAI_API_BASE}/chat/completions"
    payload = {
        "model": model or OPENAI_API_MODEL,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": 180,
        "top_p": 1.0,
        "n": 1,
    }
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers, timeout=OPENAI_API_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not data or "choices" not in data or not data["choices"]:
        raise RuntimeError("No response returned from LLM provider.")
    return data["choices"][0].get("message", {}).get("content", "").strip()


def generate_dashboard_insights(
    last_total: int,
    prev_total: int,
    last_pending: int,
    prev_pending: int,
    high_risk_pending: int,
) -> List[str]:
    if not is_llm_enabled():
        raise RuntimeError("LLM is not configured.")

    comparison = []
    if prev_total > 0:
        delta = last_total - prev_total
        ratio = delta / prev_total * 100
        comparison.append(f"Last 7 days submissions: {last_total}, prior 7 days: {prev_total} ({ratio:+.0f}% change)")
    else:
        comparison.append(f"Last 7 days submissions: {last_total}")

    if prev_pending > 0:
        pending_ratio = last_pending / prev_pending * 100
        comparison.append(f"Pending count: {last_pending}, prior 7 days pending: {prev_pending} ({pending_ratio:+.0f}% change)")
    else:
        comparison.append(f"Pending count: {last_pending}")

    prompt = (
        "You are an operations review assistant for a PM/RCA review dashboard. "
        "Summarize the current state in 1 to 3 short actionable bullet points. "
        "Focus on whether the team should prioritize backlog, high-risk reviews, or verify field activity. "
        "Do not use apologies or explanations. "
        "Output only concise bullet points, one per line.\n\n"
        "Dashboard summary data:\n"
        f"{comparison[0]}\n"
        f"{comparison[1]}\n"
        f"High-risk pending items: {high_risk_pending}\n"
    )
    result = _openai_chat_completion([
        {"role": "system", "content": "You are a concise operational review assistant."},
        {"role": "user", "content": prompt},
    ])
    lines = _clean_output(result)
    if not lines:
        lines = [result] if result else []
    return lines[:3]


def generate_activity_suggestion(
    details_text: str,
    sla_state: str,
    risk_level: str,
    activity_type: str = "activity",
) -> str:
    if not is_llm_enabled():
        raise RuntimeError("LLM is not configured.")

    truncated_details = _truncate_text(details_text or "", max_chars=1400)
    prompt = (
        "You are an operations review assistant. "
        "Read the technician-submitted activity details and recommend the next best action for desk review. "
        "Keep the response to one short sentence. "
        "Do not mention AI or the model.\n\n"
        "Activity details:\n"
        f"{truncated_details}\n\n"
        f"SLA state: {sla_state or 'Not Set'}\n"
        f"Risk level: {risk_level or 'Unknown'}\n"
        f"Activity type: {activity_type or 'Unknown'}\n"
    )
    result = _openai_chat_completion([
        {"role": "system", "content": "You are a concise operational review assistant."},
        {"role": "user", "content": prompt},
    ])
    lines = _clean_output(result)
    if lines:
        return lines[0]
    return result.strip()
