"""The corpus gallery: browse archived prompts and reference images as a grid."""

from __future__ import annotations

from math import ceil
from typing import Any

import streamlit as st

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.corpus import resolve, tags_of
from corpus_atelier.corpus.gallery import ensure_gallery_seed
from corpus_atelier.ui.session import _corpus_store, _t


PAGE_SIZE = 12
GRID_COLUMNS = 3
MAX_RESULTS = 500


def _tag_label(tag_id: str) -> str:
    try:
        return resolve(tag_id).zh
    except ValueError:
        return tag_id


def _collection_label(tag_id: str | None) -> str:
    if tag_id is None:
        return _t("gallery_all_collections")
    return _tag_label(tag_id)


def _prompt_excerpt(prompt: str, *, limit: int = 160) -> str:
    text = " ".join(str(prompt).split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _render_record_card(column, record: dict[str, Any]) -> None:
    with column:
        with st.container(border=True, key=f"gallery_card_{record['id']}"):
            image = record.get("image")
            path = resolve_paths().corpus_media_root / image["path"] if image else None
            if path is not None and path.is_file():
                st.image(str(path), width="stretch", output_format="PNG")
            else:
                st.caption(_t("corpus_no_media"))
            source = record.get("source") or {}
            note = (source.get("note") or "").strip()
            st.markdown(f"**{note or record['id']}**")
            st.caption(_prompt_excerpt(record["prompt"]))
            tags = record.get("tags") or []
            if tags:
                st.caption("  ".join(_tag_label(tag_id) for tag_id in tags))
            with st.expander(_t("gallery_prompt_show")):
                st.code(record["prompt"], language=None, wrap_lines=True)
                negative = record.get("negative_prompt")
                if negative:
                    st.caption(_t("corpus_negative"))
                    st.code(negative, language=None, wrap_lines=True)
                label = f"{_t('corpus_source')}: {source.get('kind', '')}"
                url = source.get("url")
                st.caption(f"{label}  {url}" if url else label)


def _render_page_controls(page: int, pages: int) -> None:
    previous, status, following = st.columns([1, 2, 1], vertical_alignment="center")
    with previous:
        if st.button(_t("gallery_prev"), key="gallery_prev", disabled=page <= 0):
            st.session_state.gallery_page = page - 1
            st.rerun()
    with status:
        st.caption(_t("gallery_page_status", page=page + 1, pages=pages))
    with following:
        if st.button(
            _t("gallery_next"), key="gallery_next", disabled=page >= pages - 1,
        ):
            st.session_state.gallery_page = page + 1
            st.rerun()


def _render_filters() -> tuple[str | None, str]:
    collection_column, search_column = st.columns([1, 2], vertical_alignment="bottom")
    with collection_column:
        collection = st.selectbox(
            _t("gallery_collection_label"),
            [None, *[tag.id for tag in tags_of("collection")]],
            format_func=_collection_label,
            key="gallery_collection",
        )
    with search_column:
        query = st.text_input(
            _t("search_label"),
            key="corpus_query",
            placeholder=_t("corpus_search_placeholder"),
        )
    return collection, query or ""


def _render_gallery() -> None:
    st.title(_t("gallery_title"))
    st.caption(_t("gallery_tagline"))
    collection, query = _render_filters()
    signature = (collection or "", query.strip())
    if st.session_state.get("gallery_signature") != signature:
        st.session_state.gallery_signature = signature
        st.session_state.gallery_page = 0

    store = _corpus_store()
    try:
        ensure_gallery_seed(store, media_root=resolve_paths().corpus_media_root)
        results = store.search(
            query or None,
            tags=[collection] if collection else None,
            limit=MAX_RESULTS,
        )
    finally:
        store.close()
    if not results:
        st.info(_t("corpus_empty"), icon=":material/search_off:")
        return

    st.caption(_t("gallery_result_count", count=len(results)))
    pages = max(1, ceil(len(results) / PAGE_SIZE))
    page = min(int(st.session_state.get("gallery_page") or 0), pages - 1)
    st.session_state.gallery_page = page
    start = page * PAGE_SIZE
    batch = results[start:start + PAGE_SIZE]
    with st.container(key="gallery_grid"):
        for offset in range(0, len(batch), GRID_COLUMNS):
            columns = st.columns(GRID_COLUMNS, gap="medium")
            for column, record in zip(
                columns, batch[offset:offset + GRID_COLUMNS], strict=False,
            ):
                _render_record_card(column, record)
    if pages > 1:
        _render_page_controls(page, pages)
