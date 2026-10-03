"""Session drafts for native, field-by-field design brief editing."""

from copy import deepcopy

import streamlit as st

from .design_support.validation import load_schema
from .i18n import LANGUAGE_LABELS
from .registry import get_profile


TEXT_FIELDS = ("deliverable", "topic", "article_title", "article_summary", "purpose",
               "audience", "use_context", "setting", "art_direction")
SHORT_TEXT_FIELDS = ("deliverable", "topic", "article_title", "audience")
LIST_FIELDS = ("exact_copy", "constraints", "preferences", "user_requirements")


def draft_key(run_id: str) -> str:
    return f"brief_draft_{run_id}"


def field_key(run_id: str, field: str) -> str:
    return f"brief_edit_{run_id}_{field}"


def load_draft(run_id: str, conversation: dict, brief: dict | None = None,
               source_revision: int | None = None) -> None:
    brief = deepcopy(brief if brief is not None else conversation["design_brief"])
    if brief is None:
        schema = load_schema(get_profile(conversation["profile"]).brief_schema)
        brief = {field: [] if schema["properties"][field]["type"] == "array" else ""
                 for field in schema["required"] if field != "canvas"}
        if "canvas" in schema["required"]:
            brief["canvas"] = {"aspect_ratio": {"width": 16, "height": 9}}
    language = (brief.get("content_language") or conversation["content_language"]
                or conversation.get("discussion_language"))
    if language:
        brief["content_language"] = language
    brief.setdefault("user_requirements", [])
    draft = {"brief": brief, "questions": list(conversation["open_questions"]),
             "saved_brief": deepcopy(conversation["design_brief"]),
             "base_revision": conversation["revision"],
             "source_revision": source_revision if source_revision is not None else conversation["brief_revision"]}
    st.session_state[draft_key(run_id)] = draft
    st.session_state[field_key(run_id, "content_language")] = language
    for field in TEXT_FIELDS:
        if field in brief:
            st.session_state[field_key(run_id, field)] = brief[field]
    for field in LIST_FIELDS:
        if field in brief:
            st.session_state[field_key(run_id, field)] = "\n".join(brief[field])
    st.session_state[field_key(run_id, "open_questions")] = "\n".join(draft["questions"])
    if "canvas" in brief:
        for field in ("width", "height"):
            st.session_state[field_key(run_id, field)] = brief["canvas"]["aspect_ratio"][field]


def draft_values(run_id: str) -> tuple[dict, list[str]]:
    draft = st.session_state[draft_key(run_id)]
    brief = deepcopy(draft["brief"])
    language = st.session_state.get(field_key(run_id, "content_language"))
    if language:
        brief["content_language"] = language
    else:
        brief.pop("content_language", None)
    for field in TEXT_FIELDS:
        if field in brief:
            brief[field] = st.session_state.get(field_key(run_id, field), brief[field])
    for field in LIST_FIELDS:
        if field in brief:
            value = st.session_state.get(field_key(run_id, field), "\n".join(brief[field]))
            brief[field] = [line for line in value.splitlines() if line.strip()]
    if "canvas" in brief:
        for field in ("width", "height"):
            brief["canvas"]["aspect_ratio"][field] = st.session_state.get(
                field_key(run_id, field), brief["canvas"]["aspect_ratio"][field])
    questions = st.session_state.get(field_key(run_id, "open_questions"), "\n".join(draft["questions"]))
    return brief, [line for line in questions.splitlines() if line.strip()]


def draft_dirty(run_id: str) -> bool:
    draft = st.session_state.get(draft_key(run_id))
    if not draft:
        return False
    brief, questions = draft_values(run_id)
    return brief != draft["saved_brief"] or questions != draft["questions"]


def render_fields(run_id: str, *, disabled: bool, translate) -> None:
    brief = st.session_state[draft_key(run_id)]["brief"]
    language = st.session_state.get(field_key(run_id, "content_language"))
    languages = list(dict.fromkeys([None, "zh-CN", "en"] + ([language] if language else [])))
    st.selectbox(translate("task_content_language"), languages, index=languages.index(language),
                 format_func=lambda value: translate("choose_content_language") if value is None else LANGUAGE_LABELS.get(value, value),
                 key=field_key(run_id, "content_language"), disabled=disabled, persist_state="session")
    # Defaults also travel to the browser: a new chat turn may remount this subtree.
    short_fields = [field for field in SHORT_TEXT_FIELDS if field in brief]
    for start in range(0, len(short_fields), 2):
        columns = st.columns(2)
        for column, field in zip(columns, short_fields[start:start + 2]):
            with column:
                st.text_area(translate(field), value=brief[field], key=field_key(run_id, field), height=180,
                             disabled=disabled, persist_state="session")
    for field in TEXT_FIELDS:
        if field in brief and field not in SHORT_TEXT_FIELDS:
            st.text_area(translate(field), value=brief[field], key=field_key(run_id, field), height=280,
                         disabled=disabled, persist_state="session")
    if "canvas" in brief:
        width, height = st.columns(2)
        for column, field in ((width, "width"), (height, "height")):
            with column:
                st.number_input(translate(f"brief_ratio_{field}"), min_value=1, max_value=100,
                                value=brief["canvas"]["aspect_ratio"][field], step=1,
                                key=field_key(run_id, field), disabled=disabled,
                                persist_state="session")
    for field in LIST_FIELDS:
        if field in brief:
            st.text_area(translate("user_requirements_editor" if field == "user_requirements" else field),
                         value="\n".join(brief[field]), key=field_key(run_id, field), height=280, disabled=disabled,
                         help=translate("brief_list_help"), persist_state="session")
    st.text_area(translate("brief_open_questions"), key=field_key(run_id, "open_questions"),
                 value="\n".join(st.session_state[draft_key(run_id)]["questions"]), height=180,
                 help=translate("brief_questions_help"), disabled=disabled,
                 persist_state="session")
