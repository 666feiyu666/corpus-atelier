"""The review-gated, single-generation Corpus Atelier graph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState


def build_graph(runtime, checkpointer):
    graph = StateGraph(AtelierState)
    graph.add_node("prepare_inputs", runtime.prepare_inputs)
    graph.add_node("plan_references", runtime.plan_references)
    graph.add_node("design", runtime.design)
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate", runtime.generate)
    graph.add_node("review", runtime.review)
    graph.add_node("final_decision", runtime.final_decision)

    graph.add_edge(START, "prepare_inputs")
    graph.add_conditional_edges(
        "prepare_inputs",
        lambda state: "references" if state.get("brief", {}).get("reference_mode") else "design",
        {"references": "plan_references", "design": "design"},
    )
    graph.add_edge("plan_references", "design")
    graph.add_edge("design", "approval")
    graph.add_conditional_edges(
        "approval",
        lambda state: "generate" if state.get("status") != "rejected" else "end",
        {"generate": "generate", "end": END},
    )
    graph.add_edge("generate", "review")
    graph.add_edge("review", "final_decision")
    graph.add_edge("final_decision", END)
    return graph.compile(checkpointer=checkpointer)
