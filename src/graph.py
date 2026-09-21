from langgraph.graph import StateGraph, END
from src.state import OverallState
from src.agents.triage_agent import triage_agent
from src.agents.investigator_agent import investigator_agent
from src.agents.remediate_agent import remediate_agent # NEW

def router(state: OverallState):
    if state['confidence'] < 0.8:
        return "escalate"
    if state['triage_decision'] == "investigate":
        return "investigate"
    return END

def escalate_node(state: OverallState):
    return {"investigation_report": f"ESCALATED: Needs human. Alert: {state['alert']}"}

workflow = StateGraph(OverallState)

workflow.add_node("triage", triage_agent)
workflow.add_node("investigate", investigator_agent)
workflow.add_node("remediate", remediate_agent) # NEW
workflow.add_node("escalate", escalate_node)

workflow.set_entry_point("triage")

workflow.add_conditional_edges("triage", router, {
    "investigate": "investigate",
    "escalate": "escalate",
    END: END
})

workflow.add_edge("investigate", "remediate") # CHAIN: investigate -> remediate
workflow.add_edge("remediate", END)
workflow.add_edge("escalate", END)

app_graph = workflow.compile()