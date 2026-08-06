import json
import os
from typing import TypedDict
from langgraph.graph import StateGraph, END

from core.logger import get_logger
from core.providers import LLMRouter

logger = get_logger("worker.graph")
router = LLMRouter()

MAX_ATTEMPTS = int(os.getenv("MAX_PARSE_ATTEMPTS", "3"))


class AgentState(TypedDict):
    raw_data: str
    cleaned_data: str
    is_valid: bool
    attempt: int
    validation_reason: str


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
You are a data validation agent.
Validate this JSON:
- name: must be "Firstname Lastname" (two words, each capitalized)
- salary: must be a positive integer
- date: must be valid YYYY-MM-DD calendar date

Data: {state['cleaned_data']}

Respond ONLY with JSON. No markdown.
Format: {{"is_valid": true/false, "reason": "OK or explanation"}}
"""
    response = router.invoke(prompt)
    logger.debug("validate_node raw_response=%s", response)

    try:
        parsed = json.loads(response)
        is_valid = bool(parsed.get("is_valid", False))
        reason = parsed.get("reason", "unknown")
    except Exception as e:
        logger.warning("validate_node json_parse_error=%s response=%s", e, response)
        is_valid = False
        reason = f"Unparseable validator response: {response}"

    logger.info("validate_node is_valid=%s reason=%s", is_valid, reason)
    return {**state, "is_valid": is_valid, "validation_reason": reason}


def should_retry(state: AgentState) -> str:
    if state["is_valid"]:
        logger.info("graph_decision result=valid attempts=%d", state["attempt"])
        return END
    if state["attempt"] >= MAX_ATTEMPTS:
        logger.error("graph_decision result=max_attempts attempts=%d", state["attempt"])
        return END
    logger.info("graph_decision result=retry attempt=%d reason=%s", state["attempt"], state["validation_reason"])
    return "parse"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_node)
    graph.add_node("validate", validate_node)
    graph.set_entry_point("parse")
    graph.add_edge("parse", "validate")
    graph.add_conditional_edges("validate", should_retry)
    return graph.compile()