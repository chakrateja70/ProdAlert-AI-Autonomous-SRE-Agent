from typing import Dict, TypedDict

class OverallState(TypedDict):
    job_id: str
    alert: str
    triage_analysis: str
    intent_type: str
    supervisor_decision: str
    confidence: float
    risk_level: str
    risk_reason: str
    needs_approval: bool
    logs: str
    metrics: str
    remediation: str
    next_agent: str
    retries: int
    report: str
    agent_visits: Dict[str, int]
