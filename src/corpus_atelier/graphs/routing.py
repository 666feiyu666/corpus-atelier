"""Top-level profile routing."""


def profile_route(state: dict) -> str:
    routes = {
        "rhetoric-poster": "rhetoric",
        "art-article-cover": "artistic",
    }
    try:
        return routes[state["profile"]]
    except KeyError as exc:
        raise ValueError(f"No graph route for profile {state.get('profile')!r}.") from exc


def after_retrieval_route(state: dict) -> str:
    return "references" if state.get("brief", {}).get("reference_mode") else profile_route(state)


def reference_mode_route(state: dict) -> str:
    mode = state.get("brief", {}).get("reference_mode")
    if mode not in {"style_grounded", "style_inspired"}:
        raise ValueError(f"No graph route for reference mode {mode!r}.")
    return mode
