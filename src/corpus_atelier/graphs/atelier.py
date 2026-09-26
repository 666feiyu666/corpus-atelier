"""The approval-gated multi-candidate product graph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState


def build_graph(runtime, checkpointer):
    graph = StateGraph(AtelierState)
    graph.add_node("interpret_request", runtime.interpret_request)
    graph.add_node("design_directions", runtime.design_directions)
    graph.add_node("implement_designs", runtime.implement_designs)
    graph.add_node("compile_candidates", runtime.compile_candidates)
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate_candidates", runtime.generate_candidates)
    graph.add_node("selection", runtime.selection)

    graph.add_conditional_edges(
        START,
        lambda state: "interpret_request" if state.get("user_request") else "design_directions",
        {
            "interpret_request": "interpret_request",
            "design_directions": "design_directions",
        },
    )
    graph.add_edge("interpret_request", "design_directions")
    graph.add_edge("design_directions", "implement_designs")
    graph.add_edge("implement_designs", "compile_candidates")
    graph.add_edge("compile_candidates", "approval")
    graph.add_conditional_edges(
        "approval",
        lambda state: (
            "generate_candidates" if state.get("status") != "rejected" else "end"
        ),
        {"generate_candidates": "generate_candidates", "end": END},
    )
    graph.add_edge("generate_candidates", "selection")
    graph.add_edge("selection", END)
    return graph.compile(checkpointer=checkpointer)
