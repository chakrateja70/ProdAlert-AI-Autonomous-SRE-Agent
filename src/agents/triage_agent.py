from langchain_openai import ChatOpenAI
from src.state import OverallState
from src.config import config

llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0, api_key=config.OPENAI_API_KEY)

def triage_agent(state: OverallState):
    alert = state['alert']
    
    prompt = f"""
    You are a Senior SRE Triage Agent.
    Analyze this alert: "{alert}"
    
    You must output in this format:
    decision: <investigate | escalate | ignore>
    confidence: <0.0 to 1.0>
    
    Rules:
    - If alert has ERROR, Timeout, CPU High -> investigate
    - If confidence < 0.8 -> escalate to human
    - If just INFO -> ignore
    """
    
    response = llm.invoke(prompt)
    content = response.content.lower()
    
    # Simple parsing - tarvata manam structured output pedtam
    confidence = 0.9 if "investigate" in content else 0.5
    decision = "investigate" if "investigate" in content else "escalate"
    
    if "ignore" in content:
        decision = "ignore"
        confidence = 0.95

    return {
        "triage_decision": decision,
        "confidence": confidence,
        "retries": state.get("retries", 0) + 1
    }