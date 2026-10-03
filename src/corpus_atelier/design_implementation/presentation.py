"""Human-readable implementation summary for the approval gate."""


def render(proposal: dict, *, content_language: str | None = None) -> str:
    headings = (
        ("设计方案", "设计方向", "设计描述", "设计理由", "检查标准")
        if content_language and content_language.startswith("zh") else
        ("Design proposal", "Direction", "Design description", "Rationale", "Review criteria")
    )
    lines = [
        f"# {headings[0]}",
        "",
        f"## {headings[1]}",
        "",
        proposal["chosen_direction"],
        "",
        f"## {headings[2]}",
        "",
        proposal["design_description"],
        "",
        f"## {headings[3]}",
        "",
        proposal["design_rationale"],
        "",
        f"## {headings[4]}",
        "",
    ]
    lines.extend(f"- {item}" for item in proposal["review_criteria"])
    return "\n".join(lines) + "\n"
