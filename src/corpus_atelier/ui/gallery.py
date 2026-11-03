"""The showcase gallery and archived corpus records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import streamlit as st
from corpus_atelier.artifacts.records import read_json
from corpus_atelier.corpus import FACETS, resolve, tags_of

from corpus_atelier.config.paths import resolve_paths
from corpus_atelier.ui.session import _corpus_store, _language, _t


SHOWCASE_PAGE_SIZE = 4


@dataclass(frozen=True)
class ShowcaseItem:
    image_path: Path
    title: str
    featured: bool
    featured_order: int | None


def _showcase_items() -> list[ShowcaseItem]:
    showcase_root = resolve_paths().showcase_root
    manifest_path = showcase_root / "manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError):
        return []
    if (
        not isinstance(manifest, dict)
        or manifest.get("format_version") != 1
        or not isinstance(manifest.get("items"), list)
    ):
        return []

    items: list[ShowcaseItem] = []
    for entry in manifest["items"]:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("image")
        titles = entry.get("title")
        if not isinstance(relative, str) or not isinstance(titles, dict):
            continue
        image_path = (showcase_root / relative).resolve()
        if showcase_root not in image_path.parents or not image_path.is_file():
            continue
        title = titles.get(_language()) or titles.get("en")
        if not isinstance(title, str) or not title.strip():
            continue
        featured_order = entry.get("featured_order")
        if isinstance(featured_order, bool) or not isinstance(
            featured_order, int
        ):
            featured_order = None
        items.append(ShowcaseItem(
            image_path=image_path,
            title=title.strip(),
            featured=entry.get("featured") is True,
            featured_order=featured_order,
        ))
    return items


def _render_corpus_record(record: dict[str, Any]) -> None:
    image = record.get("image")
    left, right = st.columns([1, 3], vertical_alignment="top")
    with left:
        if image and image.get("path"):
            path = resolve_paths().corpus_media_root / image["path"]
            if path.is_file():
                st.image(str(path), width="stretch", output_format="PNG")
            else:
                st.caption(_t("corpus_no_media"))
        else:
            st.caption(_t("corpus_no_media"))
    with right:
        st.markdown(f"**{record['prompt']}**")
        negative = record.get("negative_prompt")
        if negative:
            st.caption(f"**{_t('corpus_negative')}:** {negative}")
        tags = record.get("tags", [])
        if tags:
            labels = []
            for tag_id in tags:
                try:
                    labels.append(resolve(tag_id).zh)
                except ValueError:
                    labels.append(tag_id)
            st.markdown(" · ".join(labels))
        source = record.get("source", {})
        st.caption(f"{_t('corpus_source')}: {source.get('kind', '')}")


def _render_gallery() -> None:
    st.title(_t("gallery_title"))
    st.caption(_t("gallery_tagline"))
    featured = _showcase_items()
    if featured:
        st.subheader(_t("gallery_featured"))
        columns = st.columns(
            min(len(featured), SHOWCASE_PAGE_SIZE),
            gap="medium",
            vertical_alignment="top",
        )
        for column, item in zip(columns, featured[:SHOWCASE_PAGE_SIZE], strict=True):
            with column:
                st.image(
                    item.image_path,
                    caption=item.title,
                    width="stretch",
                    output_format="PNG",
                )
    st.subheader(_t("corpus_title"))
    st.caption(_t("corpus_tagline"))
    query = st.text_input(_t("corpus_search_placeholder"), key="corpus_query")
    tag_options = [tag.id for facet in FACETS for tag in tags_of(facet)]
    selected_tags = st.multiselect(
        _t("corpus_tags_label"),
        tag_options,
        key="corpus_tags",
        format_func=lambda tag_id: resolve(tag_id).zh,
    )
    store = _corpus_store()
    try:
        results = store.search(query or None, tags=selected_tags, limit=20)
    finally:
        store.close()
    if not results:
        st.caption(_t("corpus_empty"))
        return
    for record in results:
        _render_corpus_record(record)
