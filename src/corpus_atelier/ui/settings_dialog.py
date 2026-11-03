"""The settings dialog: credential, model, and language controls."""

from __future__ import annotations

import streamlit as st
from corpus_atelier.config.languages import LANGUAGE_LABELS, SUPPORTED_LANGUAGES
from corpus_atelier.config.settings import mask_api_key, update_local_openai_api_key

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.session import (
    _current_credential,
    _language,
    _save_language,
    _t,
    _test_openai_connection,
)


def _dismiss_settings_dialog() -> None:
    st.session_state.settings_dialog_open = False


def _show_settings_dialog() -> None:
    @st.dialog(
        _t("settings"),
        icon=":material/settings:",
        on_dismiss=_dismiss_settings_dialog,
    )
    def settings_dialog() -> None:
        selected_language = st.selectbox(
            _t("interface_language"),
            list(SUPPORTED_LANGUAGES),
            index=list(SUPPORTED_LANGUAGES).index(_language()),
            format_func=LANGUAGE_LABELS.__getitem__,
            key="settings_language",
        )
        if selected_language and selected_language != _language():
            try:
                _save_language(selected_language)
                st.session_state.settings_dialog_open = False
                st.rerun()
            except OSError:
                st.error(
                    _t("settings_save_failed"),
                    icon=":material/error:",
                )

        st.subheader(_t("api_configuration"))
        credential = _current_credential()
        if credential:
            st.caption(_t(
                "api_key_configured",
                masked=mask_api_key(credential.value),
            ))
        else:
            st.caption(_t("api_key_missing"))

        with st.form("openai_api_key_form", clear_on_submit=True):
            candidate_key = st.text_input(
                _t("openai_api_key"),
                type="password",
                autocomplete="off",
                placeholder=_t(
                    "api_key_placeholder_configured"
                    if credential else "api_key_placeholder_empty"
                ),
                key="settings_openai_api_key",
            )
            remember_key = st.toggle(
                _t("remember_api_key"),
                help=_t("remember_api_key_help"),
                key="settings_remember_api_key",
            )
            with st.container(horizontal=True):
                save_key = st.form_submit_button(
                    _t("save_api_key"),
                    type="primary",
                    icon=":material/save:",
                )
                test_connection = st.form_submit_button(
                    _t("test_connection"),
                    icon=":material/cable:",
                )

        submitted_key = (candidate_key or "").strip()
        if save_key:
            if not submitted_key:
                st.error(_t("api_key_required"), icon=":material/error:")
            else:
                try:
                    if remember_key:
                        update_local_openai_api_key(resolve_paths().env_path, submitted_key)
                    st.session_state.session_openai_api_key = submitted_key
                    st.session_state.settings_notice = _t(
                        "api_key_saved_local"
                        if remember_key else "api_key_saved_session"
                    )
                    st.session_state.settings_dialog_open = False
                    st.rerun()
                except OSError:
                    st.error(
                        _t("settings_save_failed"),
                        icon=":material/error:",
                    )

        if test_connection:
            key_to_test = submitted_key or (
                credential.value if credential else ""
            )
            if not key_to_test:
                st.error(_t("api_key_required"), icon=":material/error:")
            elif _test_openai_connection(key_to_test):
                st.success(_t("connection_ok"), icon=":material/check_circle:")
            else:
                st.error(
                    _t("connection_failed"),
                    icon=":material/error:",
                )

        if st.button(
            _t("clear_api_key"),
            icon=":material/key_off:",
            key="clear_openai_api_key",
        ):
            try:
                st.session_state.session_openai_api_key = None
                update_local_openai_api_key(resolve_paths().env_path, None)
                remaining = _current_credential()
                st.session_state.settings_notice = _t(
                    "api_key_fallback_environment"
                    if remaining else "api_key_cleared"
                )
                st.session_state.settings_dialog_open = False
                st.rerun()
            except OSError:
                st.error(
                    _t("settings_save_failed"),
                    icon=":material/error:",
                )
        st.caption(_t("api_key_environment_hint"))

    settings_dialog()
