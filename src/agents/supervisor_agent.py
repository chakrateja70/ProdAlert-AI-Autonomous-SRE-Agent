from typing import Literal

from pydantic import BaseModel, ValidationError

from src.llm_service import get_llm
from src.state import OverallState

llm = get_llm("gpt-4o-mini")

NextAgent = Literal["triage", "investigator", "remediator", "finish"]
NEXT_AGENTS: tuple[NextAgent, ...] = ("triage", "investigator", "remediator", "finish")

SYSTEM_PROMPT = """You are the SRE Supervisor. You route tasks and assess risk.
If triage_analysis is empty -> next_agent: triage.
If triage_analysis is present and logs/metrics are empty -> next_agent: investigator.
If investigation is done and remediation is empty -> next_agent: remediator.
Otherwise -> next_agent: finish.

Also assess risk_level (LOW, MEDIUM, HIGH, CRITICAL) and confidence (0.0-1.0)
from the available state.

Respond in exactly this format, one field per line, no extra commentary:
next_agent: <triage|investigator|remediator|finish>
confidence: <0.0-1.0>
risk_level: <LOW|MEDIUM|HIGH|CRITICAL>
reason: <one short sentence>
"""

MAX_VISITS_PER_AGENT = 3


class SupervisorDecision(BaseModel):
    next_agent: NextAgent
    confidence: float
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    reason: str


def _build_status(state: OverallState) -> str:
    return f"""
    triage_analysis: {state.get("triage_analysis") or "(none)"}
    intent_type: {state.get("intent_type") or "(none)"}
    risk_level: {state.get("risk_level") or "(none)"}
    confidence: {state.get("confidence")}
    logs: {"present" if state.get("logs") else "(none)"}
    metrics: {"present" if state.get("metrics") else "(none)"}
    remediation: {"present" if state.get("remediation") else "(none)"}
    """


def _parse(content: str) -> SupervisorDecision:
    fields: dict[str, str] = {}
    for line in content.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip().lower()] = value.strip()
    return SupervisorDecision(
        next_agent=fields["next_agent"].lower(),  # type: ignore[arg-type]
        confidence=float(fields["confidence"]),
        risk_level=fields["risk_level"].upper(),  # type: ignore[arg-type]
        reason=fields.get("reason", ""),
    )


DESTRUCTIVE_INTENTS = ("data_deletion", "destructive")


def _apply_visit_cap(state: OverallState, next_agent: NextAgent) -> tuple[NextAgent, dict[str, int]]:
    visits = dict(state.get("agent_visits") or {})
    if next_agent != "finish":
        visits[next_agent] = visits.get(next_agent, 0) + 1
        if visits[next_agent] > MAX_VISITS_PER_AGENT:
            print(f"⚠️ supervisor_agent: {next_agent} exceeded {MAX_VISITS_PER_AGENT} visits, escalating to finish")
            next_agent = "finish"
    return next_agent, visits


def supervisor_agent(state: OverallState) -> dict[str, object]:
    print(f"👮 supervisor_agent: called | state={state}")

    intent_type = state.get("intent_type")
    triage_confidence = state.get("confidence", 0.0)
    investigation_pending = not state.get("logs") and not state.get("metrics")

    # Routes to investigator (not finish) so the run has a real node to park before under
    # interrupt_before; a human must approve to release it. Only fires pre-investigation so an
    # approved run does not re-trip the gate and pause again on the supervisor's next turn.
    if intent_type in DESTRUCTIVE_INTENTS and investigation_pending:
        next_agent, visits = _apply_visit_cap(state, "investigator")
        result = {
            "supervisor_decision": "escalate",
            "confidence": triage_confidence,
            "risk_level": "CRITICAL",
            "needs_approval": True,
            "next_agent": next_agent,
            "agent_visits": visits,
            "report": (
                f"🚨 BLOCKED: Destructive intent detected ({intent_type}). "
                f"Alert: '{state['alert']}'. Analysis: {state.get('triage_analysis', '')}. "
                f"Reason: {state.get('risk_reason', '')}"
            ),
        }
        print(f"🚨 supervisor_agent: destructive intent gate escalated (intent_type={intent_type}), returning {result}")
        return result

    if state.get("risk_level") == "HIGH" and intent_type == "operational_issue" and investigation_pending:
        next_agent, visits = _apply_visit_cap(state, "investigator")
        result = {
            "supervisor_decision": "investigate" if next_agent == "investigator" else next_agent,
            "confidence": 0.9,
            "risk_level": "HIGH",
            "needs_approval": False,
            "next_agent": next_agent,
            "agent_visits": visits,
        }
        print(f"👮 supervisor_agent: operational HIGH-risk fast path, returning {result}")
        return result

    response = llm.invoke(f"{SYSTEM_PROMPT}\n\nCurrent state:\n{_build_status(state)}")
    content = str(response.content)
    print(f"🤖 supervisor_agent: llm output: {content!r}")

    try:
        decision = _parse(content)
        next_agent = decision.next_agent
        confidence = decision.confidence
        risk_level = decision.risk_level
    except (KeyError, ValueError, ValidationError) as exc:
        print(f"⚠️ supervisor_agent: llm output unparseable ({exc}), escalating to finish")
        next_agent = "finish"
        confidence = 0.0
        risk_level = "HIGH"

    next_agent, visits = _apply_visit_cap(state, next_agent)

    print(f"👮 Supervisor routing to: {next_agent}")
    return {
        "supervisor_decision": next_agent,
        "confidence": confidence,
        "risk_level": risk_level,
        "needs_approval": risk_level in ("HIGH", "CRITICAL"),
        "next_agent": next_agent,
        "agent_visits": visits,
    }
