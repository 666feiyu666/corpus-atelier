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
