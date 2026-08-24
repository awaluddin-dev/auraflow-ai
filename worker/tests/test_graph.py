import pytest
from worker.graph import _check_hitl_rules, should_retry_or_review, AgentState

def test_check_hitl_rules_short_name():
    # Valid but short name
    cleaned_data = '{"name": "Ali Ba", "salary": 5000000, "date": "2024-01-15"}'
    reasons = _check_hitl_rules(cleaned_data)
    assert len(reasons) == 1
    assert "name contains short word(s)" in reasons[0]

def test_check_hitl_rules_low_salary():
    cleaned_data = '{"name": "John Doe", "salary": 50000, "date": "2024-01-15"}'
    reasons = _check_hitl_rules(cleaned_data)
    assert len(reasons) == 1
    assert "unusually low" in reasons[0]

def test_check_hitl_rules_high_salary():
    cleaned_data = '{"name": "John Doe", "salary": 600000000, "date": "2024-01-15"}'
    reasons = _check_hitl_rules(cleaned_data)
    assert len(reasons) == 1
    assert "unusually high" in reasons[0]

def test_check_hitl_rules_bad_date():
    cleaned_data = '{"name": "John Doe", "salary": 5000000, "date": "1999-01-15"}'
    reasons = _check_hitl_rules(cleaned_data)
    assert len(reasons) == 1
    assert "before 2000" in reasons[0]

def test_check_hitl_rules_invalid_json():
    reasons = _check_hitl_rules("not a json")
    assert len(reasons) == 1
    assert reasons[0] == "unparseable_cleaned_data"

def test_should_retry_or_review_complete():
    state = {
        "job_id": "test",
        "is_valid": True,
        "confidence": 0.95,
        "attempt": 1,
        "hitl_reasons": [],
        "validation_reason": "ok"
    }
    result = should_retry_or_review(state)
    assert result == "__end__"

def test_should_retry_or_review_hitl_trigger():
    state = {
        "job_id": "test",
        "is_valid": True,
        "confidence": 0.95,
        "attempt": 1,
        "hitl_reasons": ["some reason"],
        "validation_reason": "ok"
    }
    result = should_retry_or_review(state)
    assert result == "human_review"

def test_should_retry_or_review_low_confidence(mocker):
    mocker.patch("worker.graph.MIN_CONFIDENCE", 0.9)
    state = {
        "job_id": "test",
        "is_valid": True,
        "confidence": 0.85,
        "attempt": 1,
        "hitl_reasons": [],
        "validation_reason": "ok"
    }
    result = should_retry_or_review(state)
    assert result == "human_review"

def test_should_retry_or_review_invalid_retry():
    state = {
        "job_id": "test",
        "is_valid": False,
        "confidence": 0.0,
        "attempt": 1,
        "hitl_reasons": [],
        "validation_reason": "invalid data"
    }
    result = should_retry_or_review(state)
    assert result == "parse"

def test_should_retry_or_review_max_attempts():
    state = {
        "job_id": "test",
        "is_valid": False,
        "confidence": 0.0,
        "attempt": 4, # MAX_ATTEMPTS is 3
        "hitl_reasons": [],
        "validation_reason": "invalid data"
    }
    result = should_retry_or_review(state)
    assert result == "__end__"
