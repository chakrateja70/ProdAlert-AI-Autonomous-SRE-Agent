from langchain_openai import ChatOpenAI
from src.tools.logs_search import get_logs
from src.tools.metrics_search import get_metrics
from src.state import OverallState
from src.config import config

llm = ChatOpenAI(model="gpt-4.1-nano-2025-04-14", temperature=0, api_key=config.OPENAI_API_KEY)
tools = [get_logs, get_metrics]
llm_with_tools = llm.bind_tools(tools)
TOOLS_BY_NAME = {t.name: t for t in tools}

SYSTEM_PROMPT = """You are a Senior SRE Investigator.
You have 2 tools: get_logs and get_metrics.
1. First call get_metrics for the service in alert
2. Then call get_logs with ERROR keyword
3. Correlate both and give final root cause.
"""

def investigator_agent(state: OverallState):
    alert = state['alert']

    response = llm_with_tools.invoke(f"{SYSTEM_PROMPT}\nAlert: {alert}")

    # Tool calls execute cheyali
    if response.tool_calls:
        tool_results = [
            TOOLS_BY_NAME[tool_call['name']].invoke(tool_call['args'])
            for tool_call in response.tool_calls
        ]

        # Final report
        final_prompt = f"""
        Alert: {alert}
        Tool Data: {tool_results}
        
        Based on this, write a short Investigation Report:
        - Root Cause
        - Evidence from logs and metrics
        - Severity: HIGH/MEDIUM/LOW
        """
        final_report = llm.invoke(final_prompt).content
        return {"investigation_report": final_report}
    
    return {"investigation_report": response.content}