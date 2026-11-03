"""Design candidates: ordering, selection, downloads, and previews."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile
import streamlit as st
from corpus_atelier.artifacts.hashing import digest_file
from corpus_atelier.artifacts.records import read_json
from corpus_atelier.atelier.image_prompt.prompt_compiler import MAX_GENERATION_PROMPT_CHARS
from corpus_atelier.app.state import CandidateSelection, RunResult, RunSummary

from corpus_atelier.ui.session import _resume, _t


def read_json_artifact(result: RunResult, name: str) -> Any:
    path = result.artifacts.get(name)
    return read_json(Path(path)) if path else {}


def _ready_candidates(result: RunResult) -> list[dict[str, Any]]:
    candidates = read_json_artifact(result, "candidate_index")
    return [
        candidate
        for candidate in candidates
        if candidate.get("status") == "ready"
    ]


def _all_candidates(result: RunResult) -> list[dict[str, Any]]:
    candidates = read_json_artifact(result, "candidate_index")
    return candidates if isinstance(candidates, list) else []


def _selected_candidate_id(result: RunResult) -> str | None:
    selection = read_json_artifact(result, "selection")
    return selection.get("selected_candidate_id") if isinstance(selection, dict) else None


def _ordered_candidates(
    candidates: list[dict[str, Any]], selected_id: str | None,
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.get("candidate_id") != selected_id,
            candidate.get("candidate_id", ""),
        ),
    )


def _safe_filename_part(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", " ".join(value.split()))
    cleaned = cleaned.strip(" ._")
    return (cleaned or fallback)[:56]


def _candidate_filename(
    title: str,
    candidate: dict[str, Any],
    *,
    selected: bool,
) -> str:
    task = _safe_filename_part(title, fallback=_t("file_design_task"))
    candidate_id = candidate.get("candidate_id", "c00")
    suffix = (
        _t("file_final")
        if selected
        else _t("file_candidate", number=candidate_id.removeprefix("c"))
    )
    return f"{_t('export_prefix')}_{task}_{suffix}.png"


def _verified_image_bytes(candidate: dict[str, Any]) -> bytes | None:
    image_path = candidate.get("image_path")
    if not image_path:
        return None
    path = Path(image_path)
    if not path.is_file():
        return None
    expected = candidate.get("image_sha256")
    if expected and digest_file(path) != expected:
        return None
    return path.read_bytes()


def _image_archive(
    title: str,
    candidates: list[dict[str, Any]],
    selected_id: str | None,
) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for candidate in candidates:
            data = _verified_image_bytes(candidate)
            if data is None:
                continue
            archive.writestr(
                _candidate_filename(
                    title,
                    candidate,
                    selected=candidate.get("candidate_id") == selected_id,
                ),
                data,
            )
    return output.getvalue()


def _render_visual_qa(candidate: dict[str, Any]) -> None:
    """Show the prompt writer's review checklist for one candidate."""
    checks = ((candidate.get("image_prompt") or {}).get("visual_qa")) or []
    if not checks:
        return
    with st.expander(_t("visual_qa"), icon=":material/checklist:"):
        for item in checks:
            st.markdown(f"- {item}")


def _restore_generation_prompt(key: str, prompt: str) -> None:
    """Reset the editable prompt widget before it is re-instantiated."""
    st.session_state[key] = prompt


def _render_generation_preview(
    result: RunResult, *, editable: bool = False, active: bool = False,
) -> dict[str, str]:
    ready = _ready_candidates(result)
    if not ready:
        return {}
    overrides: dict[str, str] = {}
    columns = st.columns(len(ready), gap="large", vertical_alignment="top")
    for column, candidate in zip(columns, ready, strict=True):
        proposal = candidate.get("proposal") or {}
        seed = candidate.get("direction_seed", {})
        with column.container(border=True, height="stretch"):
            st.subheader(seed.get("label", candidate["candidate_id"]))
            if proposal:
                st.markdown(
                    proposal.get("chosen_direction", _t("proposal_fallback"))
                )
                if proposal.get("design_description"):
                    with st.expander(_t("full_visual_description"), expanded=True):
                        st.markdown(proposal["design_description"])
                if proposal.get("design_rationale"):
                    st.caption(proposal["design_rationale"])
            request = candidate.get("generation_request", {})
            st.caption(
                _t("meta_separator").join([
                    _t("image_model_meta", value=request.get("model", _t("not_recorded"))),
                    _t("quality_meta", value=request.get("quality", _t("not_recorded"))),
                    _t("size_meta", value=request.get("size", _t("not_recorded"))),
                ])
            )
            _render_visual_qa(candidate)
            prompt = candidate.get("generation_prompt", "")
            if prompt:
                st.caption(_t(
                    "prompt_length", count=len(prompt), limit=MAX_GENERATION_PROMPT_CHARS,
                ))
            if prompt and editable:
                key = f"generation_prompt_{result.run_id}_{candidate['candidate_id']}"
                st.session_state.setdefault(key, prompt)
                with st.expander(_t("edit_prompt"), expanded=True):
                    st.caption(_t("editable_prompt_hint"))
                    edited = st.text_area(
                        _t("generation_prompt"), key=key, height=260, disabled=active,
                    )
                    st.button(
                        _t("restore_prompt"),
                        key=f"restore_prompt_{result.run_id}_{candidate['candidate_id']}",
                        disabled=active,
                        on_click=_restore_generation_prompt,
                        args=(key, prompt),
                    )
                if edited and edited.strip() and edited != prompt:
                    overrides[candidate["candidate_id"]] = edited
            elif prompt:
                with st.expander(_t("full_prompt_to_send")):
                    st.code(prompt, language=None, wrap_lines=True)
    return overrides


def _render_generation_receipt(result: RunResult) -> None:
    """Report the render that just ran: settings, artifact paths, one next check.

    This is the skill's closing report rather than an audit: the exact inputs that
    were sent, where they live, and the single check most likely to matter.
    """
    generated = [
        candidate for candidate in _all_candidates(result)
        if candidate.get("status") == "generated"
    ]
    if not generated:
        return
    selected_id = _selected_candidate_id(result)
    candidate = next(
        (item for item in generated if item.get("candidate_id") == selected_id), generated[0],
    )
    request = read_json_artifact(result, "generation_request_preview")
    if not isinstance(request, dict) or not request:
        request = candidate.get("generation_request") or {}
    checks = (candidate.get("image_prompt") or {}).get("visual_qa") or []
    prompt_path = (result.artifacts or {}).get("generation_prompt") or (
        f"candidates/{candidate.get('candidate_id', 'c01')}/generation/prompt.md"
    )
    with st.expander(_t("generation_receipt"), icon=":material/receipt_long:"):
        st.caption(_t("meta_separator").join([
            _t("image_model_meta", value=request.get("model", _t("not_recorded"))),
            _t("quality_meta", value=request.get("quality", _t("not_recorded"))),
            _t("size_meta", value=request.get("size", _t("not_recorded"))),
        ]))
        st.markdown(f"**{_t('receipt_prompt')}**")
        st.code(prompt_path or _t("not_recorded"), language=None, wrap_lines=True)
        if candidate.get("generation_prompt"):
            st.caption(_t(
                "prompt_length",
                count=len(candidate["generation_prompt"]),
                limit=MAX_GENERATION_PROMPT_CHARS,
            ))
        st.markdown(f"**{_t('receipt_image')}**")
        st.code(str(candidate.get("image_path") or _t("not_recorded")), language=None, wrap_lines=True)
        if checks:
            st.caption(_t("receipt_refinement", hint=checks[0]))


def _render_image_gallery(
    summary: RunSummary,
    result: RunResult,
    *,
    selectable: bool,
    active: bool = False,
) -> None:
    candidates = _all_candidates(result)
    selected_id = _selected_candidate_id(result)
    successful = _ordered_candidates(
        [candidate for candidate in candidates if candidate.get("status") == "generated"],
        selected_id,
    )
    failed = [candidate for candidate in candidates if candidate.get("status") == "failed"]

    if selectable:
        st.caption(_t("choose_or_discard"))
    elif successful:
        st.subheader(_t("generation_results"))

    if not successful:
        st.info(_t("no_images"))
    else:
        columns = st.columns(len(successful), gap="large", vertical_alignment="top")
        for column, candidate in zip(columns, successful, strict=True):
            candidate_id = candidate.get("candidate_id", "方案")
            is_selected = candidate_id == selected_id
            seed = candidate.get("direction_seed", {})
            proposal = candidate.get("proposal") or {}
            with column.container(border=True, height="stretch"):
                image_data = _verified_image_bytes(candidate)
                if image_data is None:
                    st.error(_t("image_invalid"))
                else:
                    st.image(image_data, width="stretch")
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.subheader(seed.get("label", candidate_id))
                    if is_selected:
                        st.badge(
                            _t("final_choice"),
                            icon=":material/check_circle:",
                            color="green",
                        )
                    elif not selectable:
                        st.badge(_t("alternative"), color="gray")
                if proposal.get("chosen_direction"):
                    st.caption(proposal["chosen_direction"])
                if image_data is not None:
                    if proposal.get("design_rationale"):
                        st.caption(proposal["design_rationale"])
                    _render_visual_qa(candidate)
                    st.download_button(
                        _t("download_png"),
                        data=image_data,
                        file_name=_candidate_filename(
                            summary.manifest.get("title", result.run_id),
                            candidate,
                            selected=is_selected,
                        ),
                        mime="image/png",
                        icon=":material/download:",
                        on_click="ignore",
                        width="stretch",
                        key=f"download_{result.run_id}_{candidate_id}",
                    )

                if selectable and st.button(
                    _t("choose_proposal"),
                    type="primary",
                    icon=":material/check:",
                    key=f"select_{result.run_id}_{candidate_id}",
                    width="stretch",
                    disabled=active,
                ):
                    _resume(
                        summary,
                        CandidateSelection(candidate_id, reviewer="streamlit-user"),
                    )

        if len(successful) > 1:
            archive_name = (
                f"{_t('export_prefix')}_"
                f"{_safe_filename_part(summary.manifest.get('title', result.run_id), fallback=_t('file_design_task'))}_"
                f"{_t('file_all_images')}.zip"
            )
            st.download_button(
                _t("download_all"),
                data=_image_archive(
                    summary.manifest.get("title", result.run_id),
                    successful,
                    selected_id,
                ),
                file_name=archive_name,
                mime="application/zip",
                icon=":material/folder_zip:",
                on_click="ignore",
                key=f"download_all_{result.run_id}",
            )

    if failed:
        labels = [
            candidate.get("direction_seed", {}).get(
                "label", candidate.get("candidate_id", _t("unknown_proposal"))
            )
            for candidate in failed
        ]
        st.warning(_t("failed_candidates", labels="、".join(labels)))

    if selectable and st.button(
        _t("discard_all"),
        icon=":material/delete_sweep:",
        key=f"discard_{result.run_id}",
        disabled=active,
    ):
        _resume(
            summary,
            CandidateSelection(None, reviewer="streamlit-user"),
        )


def _render_design_details(result: RunResult) -> None:
    candidates = _all_candidates(result)
    selected_id = _selected_candidate_id(result)
    candidates = _ordered_candidates(
        [
            candidate
            for candidate in candidates
            if candidate.get("proposal") or candidate.get("generation_prompt")
        ],
        selected_id,
    )
    if not candidates:
        return

    with st.expander(_t("design_details"), icon=":material/design_services:"):
        labels = []
        for candidate in candidates:
            label = candidate.get("direction_seed", {}).get(
                "label", candidate.get("candidate_id", _t("design_proposal"))
            )
            if candidate.get("candidate_id") == selected_id:
                label = f"{label} · {_t('final_choice')}"
            labels.append(label)

        for tab, candidate in zip(st.tabs(labels), candidates, strict=True):
            with tab:
                proposal = candidate.get("proposal") or {}
                status = candidate.get("status")
                if status == "failed":
                    error = candidate.get("error", {})
                    st.warning(_t(
                        "generation_failed_detail",
                        message=error.get("message", _t("no_failure_reason")),
                    ))

                if proposal:
                    st.subheader(_t("design_direction"))
                    st.markdown(
                        proposal.get("chosen_direction", _t("no_direction"))
                    )
                    if proposal.get("design_description"):
                        st.subheader(_t("full_visual_description"))
                        st.markdown(proposal["design_description"])
                    if proposal.get("design_rationale"):
                        st.subheader(_t("design_rationale"))
                        st.markdown(proposal["design_rationale"])
                else:
                    st.caption(_t("direct_route_meta"))

                request = candidate.get("generation_request", {})
                if request:
                    st.caption(
                        _t("meta_separator").join([
                            _t("image_model_meta", value=request.get("model", _t("not_recorded"))),
                            _t("quality_meta", value=request.get("quality", _t("not_recorded"))),
                            _t("size_meta", value=request.get("size", _t("not_recorded"))),
                        ])
                    )
                _render_visual_qa(candidate)
                prompt = candidate.get("generation_prompt")
                if prompt:
                    st.subheader(_t("generation_prompt"))
                    st.code(prompt, language=None, wrap_lines=True)
