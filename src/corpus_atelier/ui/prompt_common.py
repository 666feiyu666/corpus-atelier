"""Small rendering helpers shared by the prompt-session views."""

from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from corpus_atelier.app.state import RunSummary
from corpus_atelier.prompt_session.records import image_record
from corpus_atelier.ui.session import _t

LOGGER = logging.getLogger(__name__)


def _creation_failure(exc: Exception, log_message: str) -> None:
    """Report an upload or prompt validation reason, and log anything unexpected."""
    if isinstance(exc, ValueError):
        st.error(str(exc), icon=":material/error:")
        return
    LOGGER.exception(log_message)
    st.error(_t("create_failed"), icon=":material/error:")


def _image_labels(session: dict) -> dict[str, str]:
    names = {}
    for upload in session["uploads"]:
        names[upload["id"]] = upload.get("name") or upload["id"]
    for result in session["image_results"]:
        names[result["id"]] = f"{result.get('label') or _t('result_label')} ({result['id'][-4:]})"
    return names


def _revision_number(session: dict, revision_id: str) -> int:
    for index, revision in enumerate(session["prompt_revisions"], 1):
        if revision["id"] == revision_id:
            return index
    return 0


def _prompt_error(exc: Exception) -> None:
    st.error(_t("action_failed"))
    with st.expander(_t("error_details")):
        st.text(str(exc))


def _image_path(summary: RunSummary, session: dict, image_id: str) -> Path | None:
    try:
        record = image_record(session, image_id)
    except ValueError:
        return None
    path = (summary.run_dir / record["path"]).resolve()
    return path if summary.run_dir in path.parents and path.is_file() else None
