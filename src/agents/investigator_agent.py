from src.llm_service import get_llm
from src.state import OverallState
from src.tools.logs_search import get_logs
from src.tools.metrics_search import get_metrics

llm = get_llm("gpt-4.1-nano-2025-04-14")
tools = [get_logs, get_metrics]
llm_with_tools = llm.bind_tools(tools)
TOOLS_BY_NAME = {t.name: t for t in tools}

SYSTEM_PROMPT = """You are a Senior SRE Investigator.
You have 2 tools: get_logs and get_metrics.
Call only the tools that are actually useful for this alert - zero, one, or
both. Do not call a tool just because it exists. Once you have enough
evidence, correlate it and give the final root cause.
"""


def investigator_agent(state: OverallState):
    print(f"🔎 investigator_agent: called | state={state}")
    alert = state["alert"]

    print("🤖 investigator_agent: llm call (with tools)")
    response = llm_with_tools.invoke(f"{SYSTEM_PROMPT}\nAlert: {alert}")
    print(
        f"🤖 investigator_agent: llm output: {response.content!r} | tool_calls={response.tool_calls}"
    )

    # Tool calls execute cheyali
    if response.tool_calls:
        logs = ""
        metrics = ""
        tool_results = []
        for tool_call in response.tool_calls:
            print(
                f"🛠️ investigator_agent: tool call {tool_call['name']}({tool_call['args']})"
            )
            tool_result = TOOLS_BY_NAME[tool_call["name"]].invoke(tool_call["args"])
            print(
                f"🛠️ investigator_agent: tool output {tool_call['name']}: {tool_result!r}"
            )
            tool_results.append(tool_result)
            if tool_call["name"] == "get_logs":
                logs = str(tool_result)
            elif tool_call["name"] == "get_metrics":
                metrics = str(tool_result)

        # Final report
        final_prompt = f"""
        Alert: {alert}
        Tool Data: {tool_results}

        Based on this, write a short Investigation Report:
        - Root Cause
        - Evidence from logs and metrics
        - Severity: HIGH/MEDIUM/LOW
        """
        print("🤖 investigator_agent: llm call (final report)")
        final_report = llm.invoke(final_prompt).content
        print(f"🤖 investigator_agent: llm output (final report): {final_report!r}")
        result = {"report": final_report, "logs": logs, "metrics": metrics}
        print(f"🔎 investigator_agent: returning {result}")
        return result

    result = {"report": response.content}
    print(f"🔎 investigator_agent: returning {result}")
    return result
