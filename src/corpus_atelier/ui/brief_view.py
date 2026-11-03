"""Read-only rendering of a saved design brief."""

from __future__ import annotations

import streamlit as st
from corpus_atelier.app.state import RunResult

from corpus_atelier.ui.session import _t
from corpus_atelier.ui.candidates import read_json_artifact


def _render_brief_contents(brief: dict, *, include_requirements: bool = True) -> None:
    fields = ("deliverable", "topic", "article_title", "article_summary", "purpose",
              "audience", "use_context", "setting", "art_direction")
    for key in fields:
        if key in brief:
            st.markdown(f"**{_t(key)}:** {brief[key] or _t('brief_unspecified')}")
    ratio = brief.get("canvas", {}).get("aspect_ratio")
    if ratio:
        st.markdown(f"**{_t('brief_canvas')}:** {ratio['width']}:{ratio['height']}")
    groups = ["exact_copy", "constraints", "preferences"]
    if include_requirements:
        groups.append("user_requirements")
    for key in groups:
        if key not in brief:
            continue
        label = "confirmed_user_requirements" if key == "user_requirements" else key
        st.markdown(f"**{_t(label)}:**")
        if brief[key]:
            for item in brief[key]:
                st.markdown(f"- {item}")
        else:
            st.caption(_t("brief_no_copy" if key == "exact_copy" else "brief_unspecified"))


def _render_brief(result: RunResult) -> None:
    brief = read_json_artifact(result, "brief")
    if brief:
        with st.expander(_t("understood_request"), icon=":material/description:"):
            _render_brief_contents(brief)
