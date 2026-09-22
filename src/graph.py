from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.investigator_agent import investigator_agent
from src.agents.remediate_agent import remediate_agent
from src.agents.supervisor_agent import supervisor_agent
from src.agents.triage_agent import triage_agent
from src.state import OverallState


def route_from_supervisor(state: OverallState):
    next_agent = state.get("next_agent", "finish")
    return END if next_agent == "finish" else next_agent


workflow = StateGraph(OverallState)

workflow.add_node("supervisor", supervisor_agent)
workflow.add_node("triage", triage_agent)
workflow.add_node("investigator", investigator_agent)
workflow.add_node("remediator", remediate_agent)

workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    route_from_supervisor,
    {
        "triage": "triage",
        "investigator": "investigator",
        "remediator": "remediator",
        END: END,
    },
)

workflow.add_edge("triage", "supervisor")
workflow.add_edge("investigator", "supervisor")
workflow.add_edge("remediator", "supervisor")

GATED_NODES = ["triage", "investigator", "remediator"]

app_graph = workflow.compile(checkpointer=MemorySaver())
graph = app_graph
