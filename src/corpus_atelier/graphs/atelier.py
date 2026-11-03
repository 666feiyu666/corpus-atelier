"""The approval-gated multi-candidate product graph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState
from ..workflow_runtime import resolve_execution_route


def _route(state: AtelierState) -> str:
    return "direct_prompt" if resolve_execution_route(state) == "direct" else "design_directions"


def build_graph(runtime, checkpointer):
    graph = StateGraph(AtelierState)
    graph.add_node("interpret_request", runtime.interpret_request)
    graph.add_node("direct_prompt", runtime.compile_direct_candidates)
    graph.add_node("design_directions", runtime.design_directions)
    graph.add_node("implement_designs", runtime.implement_designs)
    graph.add_node("compile_candidates", runtime.compile_candidates)
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate_candidates", runtime.generate_candidates)
    graph.add_node("selection", runtime.selection)

    branches = {"direct_prompt": "direct_prompt", "design_directions": "design_directions"}
    graph.add_conditional_edges(
        START,
        lambda state: "interpret_request" if state.get("user_request") else _route(state),
        {"interpret_request": "interpret_request", **branches},
    )
    graph.add_conditional_edges("interpret_request", _route, branches)
    graph.add_edge("direct_prompt", "approval")
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
