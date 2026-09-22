from src.llm_service import get_llm
from src.state import OverallState

llm = get_llm("gpt-4.1-nano-2025-04-14")


def remediate_agent(state: OverallState):
    print(f"🩹 remediate_agent: called | state={state}")
    report = state.get("report", "")

    prompt = f"""
    You are a Senior SRE Remediation Agent.
    Investigation Report: {report}
    
    Based on this, suggest remediation steps.
    
    Rules:
    1. If DB CPU high / connection pool full -> suggest: scale DB, restart service, clear connections
    2. Never do auto-restart in prod. Always ask for human approval.
    3. Output format:
       - Suggested Action:
       - Command: (e.g., kubectl rollout restart deployment/payment-service)
       - Risk: HIGH/MEDIUM/LOW
       - Needs Approval: Yes/No
    
    Also check confidence: {state.get("confidence")} - if < 0.85, don't auto-remediate.
    """

    print("🤖 remediate_agent: llm call")
    response = llm.invoke(prompt)
    print(f"🤖 remediate_agent: llm output: {response.content!r}")

    result = {"remediation": str(response.content)}
    print(f"🩹 remediate_agent: returning {result}")
    return result
