from langchain_openai import ChatOpenAI
from src.state import OverallState
from src.config import config


llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0, api_key=config.OPENAI_API_KEY)

def remediate_agent(state: OverallState):
    report = state.get('investigation_report', '')
    
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
    
    Also check confidence: {state.get('confidence')} - if < 0.85, don't auto-remediate.
    """
    
    response = llm.invoke(prompt)
    
    return {
        "investigation_report": report + f"\n\n--- REMEDIATION PLAN ---\n{response.content}"
    }