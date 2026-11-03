"""Top navigation: the wordmark and the two product tabs, on every page."""

from __future__ import annotations

import streamlit as st

from corpus_atelier.ui.session import _t
from corpus_atelier.ui.theme import inject_theme


VIEWS = ("studio", "gallery")


def _render_nav() -> str:
    """Render the persistent tab bar and return the selected product view."""
    inject_theme()
    with st.container(
        horizontal=True, vertical_alignment="bottom", gap="large", key="atelier_nav",
    ):
        st.markdown(
            f'<div class="atelier-wordmark">{_t("product_name")}</div>',
            unsafe_allow_html=True,
        )
        view = st.segmented_control(
            _t("view_switch"),
            list(VIEWS),
            format_func=lambda value: _t(f"view_{value}"),
            key="product_view_tabs",
            persist_state="session",
            required=True,
            label_visibility="collapsed",
            width="content",
        ) or "studio"
    st.markdown('<div class="atelier-nav-rule"></div>', unsafe_allow_html=True)
    st.session_state.product_view = view
    return view
