"""Route resolution shared by the intake stage and the graph."""

from __future__ import annotations

from ..state import AtelierState


def resolve_execution_route(state: AtelierState) -> str:
    """Resolve the direct/staged route from an explicit choice or the reviewed brief."""
    mode = state.get("generation_mode") or "auto"
    if mode in {"direct", "staged"}:
        return mode
    route = (state.get("brief") or {}).get("execution_route")
    return route if route in {"direct", "staged"} else "staged"
