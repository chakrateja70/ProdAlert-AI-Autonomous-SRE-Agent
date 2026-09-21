from typing import TypedDict, List, Optional

class OverallState(TypedDict):
    alert: str
    confidence: float
    triage_decision: str
    investigation_report: str
    final_action: str
    retries: int