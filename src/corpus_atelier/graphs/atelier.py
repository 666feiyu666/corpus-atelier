"""The review-gated Corpus Atelier LangGraph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState
from .routing import profile_route


def build_graph(runtime, checkpointer):
    from . import artistic, rhetoric

    graph = StateGraph(AtelierState)
    graph.add_node("retrieve", runtime.retrieve)
    graph.add_node("rhetoric", lambda state: rhetoric.run(state, runtime))
    graph.add_node("artistic", lambda state: artistic.run(state, runtime))
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate", runtime.generate)
    graph.add_node("review", runtime.review)
    graph.add_node("revision_gate", runtime.revision_gate)
    graph.add_node("plan_revision", runtime.plan_revision)
    graph.add_node("revision_approval", runtime.revision_approval)
    graph.add_node("edit_image", runtime.edit_image)
    graph.add_node("review_revision", runtime.review_revision)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", profile_route, {
        "rhetoric": "rhetoric", "artistic": "artistic",
    })
    graph.add_edge("rhetoric", "approval")
    graph.add_edge("artistic", "approval")
    graph.add_conditional_edges(
        "approval", lambda state: "generate" if state.get("status") != "rejected" else "end",
        {"generate": "generate", "end": END},
    )
    graph.add_edge("generate", "review")
    graph.add_edge("review", "revision_gate")
    graph.add_conditional_edges(
        "revision_gate", lambda state: state["revision_action"],
        {"accept": END, "discard": END, "revise": "plan_revision"},
    )
    graph.add_edge("plan_revision", "revision_approval")
    graph.add_conditional_edges(
        "revision_approval",
        lambda state: "edit" if state["revision_approval"]["approved"] else "gate",
        {"edit": "edit_image", "gate": "revision_gate"},
    )
    graph.add_edge("edit_image", "review_revision")
    graph.add_edge("review_revision", "revision_gate")
    return graph.compile(checkpointer=checkpointer)
