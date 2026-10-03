"""Session drafts for native, field-by-field design brief editing."""

from copy import deepcopy

import streamlit as st


TEXT_FIELDS = ("deliverable", "topic", "article_title", "article_summary", "purpose",
               "audience", "use_context", "setting", "art_direction")
LIST_FIELDS = ("exact_copy", "constraints", "preferences", "user_requirements")


def draft_key(run_id: str) -> str:
    return f"brief_draft_{run_id}"


def field_key(run_id: str, field: str) -> str:
    return f"brief_edit_{run_id}_{field}"


def load_draft(run_id: str, conversation: dict, brief: dict | None = None,
               source_revision: int | None = None) -> None:
    brief = deepcopy(brief if brief is not None else conversation["design_brief"])
    if brief is None:
        return
    # A reviewed language proposal keeps its language; source copy is never translated here.
    brief.setdefault("content_language", conversation["content_language"])
    brief.setdefault("user_requirements", [])
    draft = {"brief": brief, "questions": list(conversation["open_questions"]),
             "saved_brief": deepcopy(conversation["design_brief"]),
             "base_revision": conversation["revision"],
             "source_revision": source_revision if source_revision is not None else conversation["brief_revision"]}
    draft["source_suggestion_ids"] = []
    st.session_state[draft_key(run_id)] = draft
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


def add_suggestion(run_id: str, conversation: dict, suggestion: dict, *,
                   mode: str = "append", replacement_index: int | None = None) -> None:
    """Add source-linked text to the current draft without saving or dropping other edits."""
    if draft_key(run_id) not in st.session_state:
        load_draft(run_id, conversation)
    draft = st.session_state[draft_key(run_id)]
    if draft["base_revision"] != conversation["revision"]:
        raise ValueError("Review the current brief before adding a suggestion to a stale draft.")
    brief, _ = draft_values(run_id)
    field, sentence = suggestion["field"], suggestion["text"]
    if field not in brief:
        raise ValueError("The suggestion targets a field absent from this draft.")
    if field in LIST_FIELDS:
        entries = list(brief[field])
        if mode == "append":
            if sentence not in entries:
                entries.append(sentence)
        elif mode == "replace" and isinstance(replacement_index, int) and 0 <= replacement_index < len(entries):
            entries[replacement_index] = sentence
        else:
            raise ValueError("Choose the existing entry to replace.")
        st.session_state[field_key(run_id, field)] = "\n".join(entries)
    elif field in TEXT_FIELDS and mode == "replace":
        st.session_state[field_key(run_id, field)] = sentence
    else:
        raise ValueError("Choose replacement for a text field.")
    if suggestion["id"] not in draft["source_suggestion_ids"]:
        draft["source_suggestion_ids"].append(suggestion["id"])


def render_fields(run_id: str, *, disabled: bool, translate) -> None:
    brief = st.session_state[draft_key(run_id)]["brief"]
    columns = st.columns(2)
    # Defaults also travel to the browser: a new chat turn may remount this subtree.
    for index, field in enumerate(field for field in TEXT_FIELDS if field in brief):
        with columns[index % 2]:
            st.text_area(translate(field), value=brief[field], key=field_key(run_id, field), height=90,
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
                         value="\n".join(brief[field]), key=field_key(run_id, field), height=100, disabled=disabled,
                         help=translate("brief_list_help"), persist_state="session")
    st.text_area(translate("brief_open_questions"), key=field_key(run_id, "open_questions"),
                 value="\n".join(st.session_state[draft_key(run_id)]["questions"]), height=80,
                 help=translate("brief_questions_help"), disabled=disabled,
                 persist_state="session")
