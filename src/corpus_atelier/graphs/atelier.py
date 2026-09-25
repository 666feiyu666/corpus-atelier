"""The approval-gated multi-candidate Corpus Atelier graph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState


def build_graph(runtime, checkpointer):
    graph = StateGraph(AtelierState)
    graph.add_node("interpret_request", runtime.interpret_request)
    graph.add_node("prepare_corpus", runtime.prepare_corpus)
    graph.add_node("plan_directions", runtime.plan_directions)
    graph.add_node("design_candidates", runtime.design_candidates)
    graph.add_node("compile_candidates", runtime.compile_candidates)
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate_candidates", runtime.generate_candidates)
    graph.add_node("selection", runtime.selection)

    graph.add_conditional_edges(
        START,
        lambda state: (
            "interpret_request" if state.get("user_request") else
            "prepare_corpus" if (
                state.get("experiment", {}).get("condition") == "explicit_corpus"
            ) else "plan_directions"
        ),
        {
            "interpret_request": "interpret_request",
            "prepare_corpus": "prepare_corpus",
            "plan_directions": "plan_directions",
        },
    )
    graph.add_conditional_edges(
        "interpret_request",
        lambda state: (
            "prepare_corpus" if (
                state.get("experiment", {}).get("condition") == "explicit_corpus"
            ) else "plan_directions"
        ),
        {"prepare_corpus": "prepare_corpus", "plan_directions": "plan_directions"},
    )
    graph.add_edge("prepare_corpus", "plan_directions")
    graph.add_edge("plan_directions", "design_candidates")
    graph.add_edge("design_candidates", "compile_candidates")
    graph.add_edge("compile_candidates", "approval")
    graph.add_conditional_edges(
        "approval",
        lambda state: (
            "generate_candidates" if state.get("status") != "rejected" else "end"
        ),
        {"generate_candidates": "generate_candidates", "end": END},
    )
    graph.add_conditional_edges(
        "generate_candidates",
        lambda state: "end" if state.get("experiment") is not None else "selection",
        {"selection": "selection", "end": END},
    )
    graph.add_edge("selection", END)
    return graph.compile(checkpointer=checkpointer)
