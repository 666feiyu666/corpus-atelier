"""Human-readable proposal summary for the approval gate."""


def render(proposal: dict) -> str:
    lines = [
        "# Design proposal",
        "",
        f"Status: **{proposal['status']}**",
        "",
        "## Direction",
        "",
        proposal["chosen_direction"],
        "",
        "## Rationale",
        "",
        proposal["design_rationale"],
        "",
        "## Review criteria",
        "",
    ]
    lines.extend(f"- {item}" for item in proposal["review_criteria"])
    return "\n".join(lines) + "\n"
