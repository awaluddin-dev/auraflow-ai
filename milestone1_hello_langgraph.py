import os
from dotenv import load_dotenv
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

# ── State ────────────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    raw_data: str
    cleaned_data: str
    is_valid: bool
    attempt: int
    validation_reason: str

# ── LLM ──────────────────────────────────────────────────────────────────────
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

# ── Nodes ─────────────────────────────────────────────────────────────────────
def parse_node(state: AgentState) -> AgentState:
    attempt = state.get("attempt", 0) + 1
    print(f"\n[Parser] Attempt #{attempt}")

    prompt = f"""
You are a data cleaning agent.
Clean this raw data into valid JSON with these fields:
- name (string, format: "firstname lastname")
- salary (integer, in IDR)
- date (string, format: YYYY-MM-DD)

Raw data: {state['raw_data']}

If previous validation failed, the reason was: {state.get('validation_reason', 'N/A')}

Respond ONLY with valid JSON. No explanation. No markdown.
Example: {{"name": "John Doe", "salary": 50000, "date": "2024-01-15"}}
"""
    result = llm.invoke(prompt)
    cleaned = result.content.strip()
    print(f"[Parser] Output: {cleaned}")

    return {
        **state,
        "cleaned_data": cleaned,
        "attempt": attempt,
    }


def validate_node(state: AgentState) -> AgentState:
    print(f"\n[Validator] Checking output...")

    prompt = f"""
You are a data validation agent.
Check if this JSON is valid and has the correct format:
- name: must be "firstname lastname" (two words, capitalized)
- salary: must be a positive integer
- date: must be YYYY-MM-DD format and a real calendar date

Data to validate: {state['cleaned_data']}

Respond ONLY with JSON in this format:
{{"is_valid": true/false, "reason": "explanation if invalid, or 'OK' if valid"}}
No markdown, no explanation outside the JSON.
"""
    result = llm.invoke(prompt)
    response = result.content.strip()
    print(f"[Validator] Result: {response}")

    import json
    try:
        parsed = json.loads(response)
        is_valid = parsed.get("is_valid", False)
        reason = parsed.get("reason", "Unknown")
    except Exception:
        is_valid = False
        reason = f"Validator returned unparseable response: {response}"

    return {
        **state,
        "is_valid": is_valid,
        "validation_reason": reason,
    }


# ── Routing ───────────────────────────────────────────────────────────────────
def should_retry(state: AgentState) -> str:
    if state["is_valid"]:
        print(f"\n✅ Valid after {state['attempt']} attempt(s)")
        return END
    
    if state["attempt"] >= 3:
        print(f"\n❌ Max attempts reached. Last output: {state['cleaned_data']}")
        return END

    print(f"\n🔁 Retrying... Reason: {state['validation_reason']}")
    return "parse"


# ── Graph ─────────────────────────────────────────────────────────────────────
def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("parse", parse_node)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("parse")
    graph.add_edge("parse", "validate")
    graph.add_conditional_edges("validate", should_retry)

    return graph.compile()


# ── Test Cases ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = build_graph()

    test_cases = [
        {
            "label": "Case 1 — Tanggal tidak valid",
            "raw_data": "john,doe,50000,2024-13-45"
        },
        {
            "label": "Case 2 — Format campur aduk",
            "raw_data": "Name: BUDI SANTOSO | gaji: Rp 8.500.000 | tgl masuk: 15 Januari 2024"
        },
        {
            "label": "Case 3 — Data relatif bersih",
            "raw_data": "ahmad fauzi, 12000000, 2024-03-01"
        },
    ]

    for case in test_cases:
        print(f"\n{'='*60}")
        print(f"🧪 {case['label']}")
        print(f"Input: {case['raw_data']}")
        print("─" * 60)

        result = app.invoke({
            "raw_data": case["raw_data"],
            "cleaned_data": "",
            "is_valid": False,
            "attempt": 0,
            "validation_reason": "",
        })

        print(f"\n📦 Final State:")
        print(f"  cleaned_data : {result['cleaned_data']}")
        print(f"  is_valid     : {result['is_valid']}")
        print(f"  attempts     : {result['attempt']}")
        print(f"  reason       : {result['validation_reason']}")