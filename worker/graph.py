import json
import os
import re
import unicodedata
from typing import TypedDict
from langgraph.graph import StateGraph, END

from core.logger import get_logger
from core.providers import LLMRouter

logger = get_logger("worker.graph")
router = LLMRouter()

MAX_ATTEMPTS = int(os.getenv("MAX_PARSE_ATTEMPTS", "3"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8"))


class AgentState(TypedDict):
    raw_data: str
    sanitized_data: str
    sanitize_log: list[str]
    cleaned_data: str
    is_valid: bool
    confidence: float
    attempt: int
    validation_reason: str
    issues: list[str]

_DANGEROUS_PATTERNS = [
    (r"<[^>]+>",                    "HTML/XML tags"),
    (r"\{[^}]*\}",                  "curly brace expressions"),
    (r"(--|;|\/\*|\*\/|xp_|exec\s+|drop\s+table|insert\s+into|select\s+from)",
                                    "SQL injection pattern"),
    (r"(javascript:|data:|vbscript:)", "script injection"),
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "control characters"),
]

_ZERO_WIDTH_CHARS = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad]"
)

def sanitize_node(state: AgentState) -> AgentState:
    raw = state["raw_data"]
    log: list[str] = []
    data = raw

    # 1. Normalize unicode — NFC form, handle lookalike characters
    normalized = unicodedata.normalize("NFC", data)
    if normalized != data:
        log.append("unicode_normalized")
        data = normalized

    # 2. Strip zero-width characters
    cleaned_zw = _ZERO_WIDTH_CHARS.sub("", data)
    if cleaned_zw != data:
        log.append("zero_width_chars_removed")
        data = cleaned_zw

    # 3. Strip dangerous patterns
    for pattern, label in _DANGEROUS_PATTERNS:
        replaced = re.sub(pattern, " ", data, flags=re.IGNORECASE)
        if replaced != data:
            log.append(f"dangerous_pattern_removed: {label}")
            data = replaced

    # 4. Normalize whitespace
    collapsed = re.sub(r"\s+", " ", data).strip()
    if collapsed != data:
        log.append("whitespace_normalized")
        data = collapsed

    # 5. Truncate jika terlalu panjang (LLM context protection)
    if len(data) > 500:
        data = data[:500]
        log.append("truncated_to_500_chars")

    if log:
        logger.info(
            "sanitize_node changes=%s original_len=%d sanitized_len=%d",
            log, len(raw), len(data),
        )
    else:
        logger.info("sanitize_node no_changes_needed len=%d", len(data))

    return {
        **state,
        "sanitized_data": data,
        "sanitize_log": log,
    }

def parse_node(state: AgentState) -> AgentState:
    attempt = state.get("attempt", 0) + 1
    logger.info("parse_node attempt=%d job_data_preview=%s", attempt, state["raw_data"][:50])

    prompt = f"""
You are a data cleaning agent.
Clean this raw data into valid JSON with these fields:
- name (string, format: "Firstname Lastname")
- salary (integer, in IDR)
- date (string, format: YYYY-MM-DD)

Raw data: {state['raw_data']}
Previous validation failure reason: {state.get('validation_reason', 'N/A')}

Respond ONLY with valid JSON. No explanation. No markdown. No code fences.
Example: {{"name": "John Doe", "salary": 50000, "date": "2024-01-15"}}
"""
    cleaned = router.invoke(prompt)
    logger.info("parse_node output=%s", cleaned)
    return {**state, "cleaned_data": cleaned, "attempt": attempt}


def validate_node(state: AgentState) -> AgentState:
    logger.info("validate_node attempt=%d", state["attempt"])

    prompt = f"""
You are a strict data validation agent. Validate this JSON and return a confidence score.

Rules:
- name: exactly two words, each capitalized, letters only (no digits, no special chars)
- salary: positive integer (greater than 0)
- date: valid YYYY-MM-DD calendar date (must be a real date, not 0000-00-00 or 1970-01-01)

Data to validate: {state['cleaned_data']}

Respond ONLY with JSON in this exact format:
{{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "reason": "OK or main reason if invalid",
  "issues": ["list", "of", "specific", "issues"]
}}

Confidence scoring guide:
- 1.0: all fields perfect, no ambiguity
- 0.9: valid but minor formatting concern
- 0.8: valid but one field is borderline
- below 0.8: invalid or high uncertainty
- 0.0: completely invalid

No markdown. No explanation outside JSON.
"""

    response = router.invoke(prompt)
    logger.debug("validate_node raw_response=%s", response)

    try:
        # Strip markdown code fences jika ada
        clean_response = re.sub(r"```(?:json)?|```", "", response).strip()
        parsed = json.loads(clean_response)

        is_valid = bool(parsed.get("is_valid", False))
        confidence = float(parsed.get("confidence", 0.0))
        reason = parsed.get("reason", "unknown")
        issues = parsed.get("issues", [])

    except Exception as e:
        logger.warning("validate_node json_parse_error=%s response=%s", e, response)
        is_valid = False
        confidence = 0.0
        reason = f"Validator returned unparseable response: {response}"
        issues = ["unparseable_validator_response"]

    logger.info(
        "validate_node is_valid=%s confidence=%.2f reason=%s issues=%s",
        is_valid, confidence, reason, issues,
    )

    return {
        **state,
        "is_valid": is_valid,
        "confidence": confidence,
        "validation_reason": reason,
        "issues": issues,
    }


def should_retry(state: AgentState) -> str:
    is_valid = state["is_valid"]
    confidence = state["confidence"]
    attempt = state["attempt"]

    # Valid DAN confidence cukup tinggi
    if is_valid and confidence >= MIN_CONFIDENCE:
        logger.info(
            "graph_decision result=valid attempts=%d confidence=%.2f",
            attempt, confidence,
        )
        return END

    # Max attempts tercapai
    if attempt >= MAX_ATTEMPTS:
        logger.error(
            "graph_decision result=max_attempts attempts=%d confidence=%.2f last_output=%s",
            attempt, confidence, state["cleaned_data"],
        )
        return END

    # Retry — kasih info kenapa
    if is_valid and confidence < MIN_CONFIDENCE:
        logger.info(
            "graph_decision result=retry_low_confidence attempt=%d confidence=%.2f",
            attempt, confidence,
        )
    else:
        logger.info(
            "graph_decision result=retry_invalid attempt=%d reason=%s",
            attempt, state["validation_reason"],
        )

    return "parse"

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("sanitize", sanitize_node)
    graph.add_node("parse", parse_node)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("sanitize")
    graph.add_edge("sanitize", "parse")    # sanitize selalu ke parse
    graph.add_edge("parse", "validate")
    graph.add_conditional_edges("validate", should_retry)

    return graph.compile()