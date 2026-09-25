"""The approval-gated, single-generation Corpus Atelier graph."""

from langgraph.graph import END, START, StateGraph

from ..state import AtelierState


def build_graph(runtime, checkpointer):
    graph = StateGraph(AtelierState)
    graph.add_node("interpret_request", runtime.interpret_request)
    graph.add_node("prepare_corpus", runtime.prepare_corpus)
    graph.add_node("design", runtime.design)
    graph.add_node("compile_image_spec", runtime.compile_image_spec)
    graph.add_node("approval", runtime.approval)
    graph.add_node("generate", runtime.generate)

    graph.add_conditional_edges(
        START,
        lambda state: (
            "interpret_request" if state.get("user_request") else
            "prepare_corpus" if (
                state.get("experiment", {}).get("condition") == "explicit_corpus"
            ) else "design"
        ),
        {
            "interpret_request": "interpret_request",
            "prepare_corpus": "prepare_corpus",
            "design": "design",
        },
    )
    graph.add_conditional_edges(
        "interpret_request",
        lambda state: (
            "prepare_corpus" if (
                state.get("experiment", {}).get("condition") == "explicit_corpus"
            ) else "design"
        ),
        {"prepare_corpus": "prepare_corpus", "design": "design"},
    )
    graph.add_edge("prepare_corpus", "design")
    graph.add_edge("design", "compile_image_spec")
    graph.add_edge("compile_image_spec", "approval")
    graph.add_conditional_edges(
        "approval",
        lambda state: "generate" if state.get("status") != "rejected" else "end",
        {"generate": "generate", "end": END},
    )
    graph.add_edge("generate", END)
    return graph.compile(checkpointer=checkpointer)
