from typing import Literal

from pydantic import BaseModel, ValidationError

from src.llm_service import get_llm
from src.state import OverallState

llm = get_llm("gpt-4.1-nano-2025-04-14")

MAX_ATTEMPTS = 3

IntentType = Literal[
    "data_deletion", "destructive", "operational_issue", "performance_degradation", "read_only"
]


class TriageAnalysis(BaseModel):
    analysis: str
    intent_type: IntentType
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    confidence: float
    risk_reason: str


def build_prompt(alert: str) -> str:
    return f"""
    You are a Senior SRE Triage Analyst.
    Analyze this alert: "{alert}"

    Respond in exactly this format, one field per line, no extra commentary:
    analysis: <1 line technical analysis: affected service, symptom, numbers if any>
    intent_type: <one of: data_deletion, destructive, operational_issue, performance_degradation, read_only>
    risk_level: <LOW|MEDIUM|HIGH|CRITICAL>
    confidence: <0.0-1.0, how confident you are in this risk_level>
    risk_reason: <why you picked this risk_level and intent_type, one short sentence>

    Examples:
    Alert: "delete user data named teja"
    analysis: Request to delete a specific user's data
    intent_type: data_deletion
    risk_level: CRITICAL
    confidence: 0.95
    risk_reason: Explicit request to permanently remove user data, irreversible and needs human sign-off

    Alert: "payment-service is experiencing DB Connection Timeout on db-prod-1, CPU 95% high"
    analysis: Payment service DB connection timeouts with DB CPU at 95%
    intent_type: operational_issue
    risk_level: HIGH
    confidence: 0.85
    risk_reason: Service degradation from resource exhaustion, needs investigation but nothing destructive requested
    """


def _parse(content: str) -> TriageAnalysis:
    fields: dict[str, str] = {}
    for line in content.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip()
    return TriageAnalysis(
        analysis=fields["analysis"],
        intent_type=fields["intent_type"].lower(),  # type: ignore[arg-type]
        risk_level=fields["risk_level"].upper(),  # type: ignore[arg-type]
        confidence=float(fields["confidence"]),
        risk_reason=fields.get("risk_reason", ""),
    )


def triage_agent(state: OverallState) -> dict[str, object]:
    print("🚦 triage_agent: called")
    alert = state["alert"]
    prompt = build_prompt(alert)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"🤖 triage_agent: llm call attempt {attempt}")
        response = llm.invoke(prompt)
        content = str(response.content)
        print(f"🤖 triage_agent: llm output attempt {attempt}: {content!r}")
        try:
            parsed = _parse(content)
            result = {
                "triage_analysis": parsed.analysis,
                "intent_type": parsed.intent_type,
                "risk_level": parsed.risk_level,
                "confidence": parsed.confidence,
                "risk_reason": parsed.risk_reason,
            }
            print(f"🔍 Triage Analysis: {result}")
            return result
        except (KeyError, ValueError, ValidationError) as exc:
            print(f"⚠️ triage_agent: parse failed on attempt {attempt}: {exc}")
            continue

    result = {
        "triage_analysis": f"Unable to analyze alert: {alert}",
        "intent_type": "destructive",
        "risk_level": "HIGH",
        "confidence": 0.0,
        "risk_reason": "Triage could not parse a structured analysis; treating as high-risk until a human reviews it.",
    }
    print(f"🔍 Triage Analysis: {result}")
    return result
