import json
import os
import re
import unicodedata
import redis
from datetime import datetime
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

from core.logger import get_logger
from core.providers import LLMRouter

logger = get_logger("worker.graph")
router = LLMRouter()

MAX_ATTEMPTS = int(os.getenv("MAX_PARSE_ATTEMPTS", "3"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE_SCORE", "0.8"))

_redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True,
)


def _publish_progress(job_id: str, stage: str, data: dict = None):
    channel = f"job-progress:{job_id}"
    payload = json.dumps({
        "jobId": job_id,
        "stage": stage,
        "timestamp": datetime.utcnow().isoformat(),
        **(data or {}),
    })
    try:
        _redis_client.publish(channel, payload)
    except Exception as e:
        logger.warning("progress_publish_failed job_id=%s stage=%s error=%s", job_id, stage, e)


# ── HITL Rules — deterministic, tidak pakai LLM ───────────────────────────────
def _check_hitl_rules(cleaned_data: str) -> list[str]:
    """
    Return list of reasons kenapa data perlu human review.
    Empty list = tidak perlu review.
    """
    reasons = []
    try:
        data = json.loads(cleaned_data)
    except Exception:
        return ["unparseable_cleaned_data"]

    name = data.get("name", "")
    salary = data.get("salary", 0)
    date_str = data.get("date", "")

    # Nama: tiap kata harus >= 3 karakter
    words = name.split()
    short_words = [w for w in words if len(w) < 3]
    if short_words:
        reasons.append(f"name contains short word(s): {short_words} — may be initials")

    # Salary: range wajar untuk data Indonesia
    if salary < 500_000:
        reasons.append(f"salary {salary} is unusually low (< 500,000 IDR)")
    if salary > 500_000_000:
        reasons.append(f"salary {salary} is unusually high (> 500,000,000 IDR)")

    # Tanggal: harus dalam range yang masuk akal
    year = date_str[:4] if len(date_str) >= 4 else "0000"
    if year < "2000":
        reasons.append(f"date year {year} is before 2000 — possibly incorrect")
    if year > "2030":
        reasons.append(f"date year {year} is after 2030 — possibly incorrect")

    return reasons


# ── State ─────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    job_id: str
    raw_data: str
    sanitized_data: str
    sanitize_log: list[str]
    cleaned_data: str
    is_valid: bool
    confidence: float
    attempt: int
    validation_reason: str
    issues: list[str]
    hitl_reasons: list[str]
    review_decision: str
    review_edited_data: str
    review_note: str


# ── Dangerous Patterns ────────────────────────────────────────────────────────
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


# ── Nodes ──────────────────────────────────────────────────────────────────────
def sanitize_node(state: AgentState) -> AgentState:
    job_id = state.get("job_id", "unknown")
    _publish_progress(job_id, "sanitizing")

    raw = state["raw_data"]
    log: list[str] = []
    data = raw

    normalized = unicodedata.normalize("NFC", data)
    if normalized != data:
        log.append("unicode_normalized")
        data = normalized

    cleaned_zw = _ZERO_WIDTH_CHARS.sub("", data)
    if cleaned_zw != data:
        log.append("zero_width_chars_removed")
        data = cleaned_zw

    for pattern, label in _DANGEROUS_PATTERNS:
        replaced = re.sub(pattern, " ", data, flags=re.IGNORECASE)
        if replaced != data:
            log.append(f"dangerous_pattern_removed: {label}")
            data = replaced

    collapsed = re.sub(r"\s+", " ", data).strip()
    if collapsed != data:
        log.append("whitespace_normalized")
        data = collapsed

    if len(data) > 500:
        data = data[:500]
        log.append("truncated_to_500_chars")

    if log:
        logger.info("sanitize_node changes=%s original_len=%d sanitized_len=%d",
            log, len(raw), len(data))
    else:
        logger.info("sanitize_node no_changes_needed len=%d", len(data))

    _publish_progress(job_id, "sanitized", {"sanitizeLog": log})
    return {**state, "sanitized_data": data, "sanitize_log": log}


def parse_node(state: AgentState) -> AgentState:
    job_id = state.get("job_id", "unknown")
    attempt = state.get("attempt", 0) + 1
    _publish_progress(job_id, "parsing", {"attempt": attempt})
    logger.info("parse_node attempt=%d job_data_preview=%s",
        attempt, state["sanitized_data"][:50])

    input_data = state.get("review_edited_data") or state["sanitized_data"]

    prompt = f"""
You are a data cleaning agent.
Clean this sanitized data into valid JSON with these exact fields:
- name (string, format: "Firstname Lastname" — exactly two words, each capitalized, letters only)
- salary (integer, must be positive, in IDR)
- date (string, format: YYYY-MM-DD, must be a real calendar date)

Input data: {input_data}

Previous validation attempt failed:
- Reason: {state.get('validation_reason', 'N/A')}
- Confidence score: {state.get('confidence', 1.0)}
- Issues: {state.get('issues', [])}

Reviewer note: {state.get('review_note', 'N/A')}

Fix all issues. Respond ONLY with valid JSON. No explanation. No markdown. No code fences.
Example: {{"name": "John Doe", "salary": 50000, "date": "2024-01-15"}}
"""

    cleaned = router.invoke(prompt)
    logger.info("parse_node output=%s", cleaned)
    _publish_progress(job_id, "parsed", {"attempt": attempt, "output": cleaned})

    return {
        **state,
        "cleaned_data": cleaned,
        "attempt": attempt,
        "review_edited_data": "",
        "review_decision": "",
        "review_note": "",
    }


def validate_node(state: AgentState) -> AgentState:
    job_id = state.get("job_id", "unknown")
    _publish_progress(job_id, "validating", {"attempt": state["attempt"]})
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
        clean_response = re.sub(r"```(?:json)?|```", "", response).strip()
        parsed = json.loads(clean_response)
        is_valid = bool(parsed.get("is_valid", False))
        confidence = float(parsed.get("confidence", 0.0))
        reason = parsed.get("reason", "unknown")
        issues = parsed.get("issues", [])
        
        if is_valid:
            try:
                data = json.loads(state.get("cleaned_data", "{}"))
                name = data.get("name", "")
                if 0 < len(name) < 10 and confidence >= 0.9:
                    confidence = 0.85
                    reason = "Valid but name is short, reducing confidence for human review"
                    if "name is unusually short" not in issues:
                        issues.append("name is unusually short")
            except Exception:
                pass
    except Exception as e:
        logger.warning("validate_node json_parse_error=%s response=%s", e, response)
        is_valid = False
        confidence = 0.0
        reason = f"Validator returned unparseable response: {response}"
        issues = ["unparseable_validator_response"]

    logger.info("validate_node is_valid=%s confidence=%.2f reason=%s issues=%s",
        is_valid, confidence, reason, issues)

    _publish_progress(job_id, "validated", {
        "attempt": state["attempt"],
        "isValid": is_valid,
        "confidence": confidence,
        "reason": reason,
        "issues": issues,
    })

    return {
        **state,
        "is_valid": is_valid,
        "confidence": confidence,
        "validation_reason": reason,
        "issues": issues,
    }


def pre_review_check_node(state: AgentState) -> AgentState:
    """
    Rule-based check setelah validate.
    Deterministic — tidak pakai LLM.
    Cek apakah data perlu human review berdasarkan business rules.
    """
    job_id = state.get("job_id", "unknown")
    hitl_reasons = _check_hitl_rules(state["cleaned_data"])

    if hitl_reasons:
        logger.info(
            "pre_review_check job_id=%s hitl_triggered reasons=%s",
            job_id, hitl_reasons,
        )
    else:
        logger.info("pre_review_check job_id=%s hitl_not_triggered", job_id)

    return {**state, "hitl_reasons": hitl_reasons}


def human_review_node(state: AgentState) -> AgentState:
    job_id = state.get("job_id", "unknown")

    logger.info(
        "human_review_node job_id=%s hitl_reasons=%s — waiting for review",
        job_id, state["hitl_reasons"],
    )

    _publish_progress(job_id, "pending_review", {
        "cleanedData": state["cleaned_data"],
        "confidence": state["confidence"],
        "issues": state["issues"],
        "hitlReasons": state["hitl_reasons"],
    })

    review_input = interrupt({
        "jobId": job_id,
        "cleanedData": state["cleaned_data"],
        "confidence": state["confidence"],
        "hitlReasons": state["hitl_reasons"],
        "issues": state["issues"],
        "message": "Data requires human review due to business rule violations.",
    })

    logger.info(
        "human_review_node job_id=%s review_decision=%s",
        job_id, review_input.get("decision"),
    )

    _publish_progress(job_id, "review_received", {
        "decision": review_input.get("decision"),
        "note": review_input.get("note", ""),
    })

    return {
        **state,
        "review_decision": review_input.get("decision", "reject"),
        "review_edited_data": review_input.get("editedData", ""),
        "review_note": review_input.get("note", ""),
    }


# ── Routing ───────────────────────────────────────────────────────────────────
def should_retry_or_review(state: AgentState) -> str:
    """Routing setelah pre_review_check."""
    job_id = state.get("job_id", "unknown")
    is_valid = state["is_valid"]
    confidence = state["confidence"]
    attempt = state["attempt"]
    hitl_reasons = state.get("hitl_reasons", [])

    # Valid DAN tidak ada HITL triggers → auto complete
    if is_valid and confidence >= MIN_CONFIDENCE and not hitl_reasons:
        logger.info("graph_decision result=auto_complete confidence=%.2f", confidence)
        _publish_progress(job_id, "completed", {
            "confidence": confidence,
            "attempts": attempt,
            "reviewRequired": False,
        })
        return END

    # Valid tapi ada HITL triggers atau confidence rendah -> minta review manusia
    if is_valid and (hitl_reasons or confidence < MIN_CONFIDENCE):
        logger.info(
            "graph_decision result=pending_review hitl_reasons=%s confidence=%.2f", 
            hitl_reasons, confidence,
        )
        return "human_review"

    # Max attempts → fail
    if attempt >= MAX_ATTEMPTS:
        logger.error("graph_decision result=max_attempts attempts=%d", attempt)
        _publish_progress(job_id, "failed", {
            "reason": state["validation_reason"],
            "attempts": attempt,
        })
        return END

    # Invalid → retry
    logger.info("graph_decision result=retry attempt=%d reason=%s",
        attempt, state["validation_reason"])
    _publish_progress(job_id, "retrying", {
        "attempt": attempt,
        "reason": state["validation_reason"],
    })
    return "parse"


def after_review(state: AgentState) -> str:
    decision = state.get("review_decision", "reject")
    job_id = state.get("job_id", "unknown")

    if decision == "approve":
        logger.info("graph_decision result=approved_by_human")
        _publish_progress(job_id, "completed", {
            "confidence": state["confidence"],
            "attempts": state["attempt"],
            "reviewRequired": True,
            "reviewDecision": "approve",
        })
        return END

    if decision == "edit":
        logger.info("graph_decision result=edit_by_human reparse")
        return "parse"

    logger.info("graph_decision result=rejected_by_human reparse")
    return "parse"


# ── Graph ─────────────────────────────────────────────────────────────────────
def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("sanitize", sanitize_node)
    graph.add_node("parse", parse_node)
    graph.add_node("validate", validate_node)
    graph.add_node("pre_review_check", pre_review_check_node)
    graph.add_node("human_review", human_review_node)

    graph.set_entry_point("sanitize")
    graph.add_edge("sanitize", "parse")
    graph.add_edge("parse", "validate")
    graph.add_edge("validate", "pre_review_check")
    graph.add_conditional_edges("pre_review_check", should_retry_or_review)
    graph.add_conditional_edges("human_review", after_review)

    return graph.compile(
        checkpointer=checkpointer,
        # HAPUS interrupt_before — biarkan interrupt() di dalam node yang handle
    )