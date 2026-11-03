"""Closed visual taxonomy for the corpus layer.

A *closed* taxonomy means corpus records may only carry labels declared here.
Adding, renaming, or removing a label is an explicit, versioned change to this
module — it is not something an ingest path may do implicitly.

The movement and objective facets label archived records for retrieval. They are
corpus annotations only: the generation stages no longer ship a movement catalog,
so these labels never select or justify a design direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

TAXONOMY_VERSION = "ca-visual-v1"


@dataclass(frozen=True)
class Tag:
    """One closed label: a slug id, its facet, and bilingual display labels."""

    id: str
    facet: str
    en: str
    zh: str


# Facet order is the canonical grouping/display order.
FACETS: tuple[str, ...] = (
    "use_case",
    "medium",
    "art_movement",
    "design_movement",
    "objective",
    "composition",
    "mood",
)

_FACET_LABELS: dict[str, tuple[str, str]] = {
    "use_case": ("Use case", "用途"),
    "medium": ("Medium", "媒介"),
    "art_movement": ("Art movement", "艺术运动"),
    "design_movement": ("Design movement", "设计运动"),
    "objective": ("Objective", "目标导向"),
    "composition": ("Composition", "构图"),
    "mood": ("Mood & color", "情绪与色彩"),
}

TAGS: dict[str, Tag] = {}


def _declare(facet: str, entries: list[tuple[str, str, str]]) -> None:
    if facet not in FACETS:
        raise ValueError(f"Unknown facet {facet!r}.")
    for tag_id, en, zh in entries:
        if tag_id in TAGS:
            raise ValueError(f"Duplicate tag id {tag_id!r}.")
        TAGS[tag_id] = Tag(id=tag_id, facet=facet, en=en, zh=zh)


_declare("use_case", [
    ("poster", "Poster", "海报"),
    ("article-cover", "Article cover", "文章封面"),
    ("social-card", "Social-media card", "社媒卡片"),
    ("invitation", "Invitation", "邀请函"),
    ("label", "Label", "标签"),
    ("album-cover", "Album cover", "专辑封面"),
    ("book-cover", "Book cover", "书籍封面"),
    ("banner", "Banner", "横幅"),
    ("flyer", "Flyer", "传单"),
    ("wallpaper", "Wallpaper", "壁纸"),
])

_declare("medium", [
    ("illustration", "Illustration", "插画"),
    ("photography", "Photography", "摄影"),
    ("3d-render", "3D render", "三维渲染"),
    ("flat-vector", "Flat vector", "扁平矢量"),
    ("painterly", "Painterly", "绘画质感"),
    ("collage", "Collage", "拼贴"),
    ("typographic", "Typographic", "字体主导"),
    ("sketch", "Sketch", "手绘草图"),
])

_declare("art_movement", [
    ("neoclassicism", "Neoclassicism", "新古典主义"),
    ("romanticism", "Romanticism", "浪漫主义"),
    ("realism", "Realism", "现实主义"),
    ("impressionism", "Impressionism", "印象派"),
    ("post-impressionism", "Post-Impressionism", "后印象派"),
    ("expressionism", "Expressionism", "表现主义"),
    ("surrealism", "Surrealism", "超现实主义"),
])

_declare("design_movement", [
    ("art-nouveau", "Art Nouveau", "新艺术运动"),
    ("constructivism", "Constructivism", "构成主义"),
    ("de-stijl", "De Stijl", "风格派"),
    ("bauhaus-new-typography", "Bauhaus New Typography", "包豪斯新字体排印"),
    ("swiss-style", "Swiss Style", "瑞士风格"),
    ("art-deco", "Art Deco", "装饰艺术"),
    ("psychedelic", "Psychedelic", "迷幻风格"),
    ("postmodern-memphis", "Postmodern Memphis", "后现代孟菲斯"),
])

_declare("objective", [
    ("art-led", "Art-led", "艺术主导"),
    ("rhetoric-led", "Rhetoric-led", "修辞主导"),
])

_declare("composition", [
    ("centered", "Centered", "居中构图"),
    ("symmetric", "Symmetric", "对称"),
    ("asymmetric", "Asymmetric", "不对称"),
    ("diagonal", "Diagonal", "对角线"),
    ("grid", "Grid", "网格"),
    ("whitespace-minimal", "Whitespace / minimal", "大量留白"),
    ("full-bleed", "Full-bleed", "满幅出血"),
])

_declare("mood", [
    ("warm", "Warm", "暖调"),
    ("cool", "Cool", "冷调"),
    ("monochrome", "Monochrome", "单色"),
    ("high-contrast", "High contrast", "高对比"),
    ("muted", "Muted", "低饱和柔和"),
    ("vibrant", "Vibrant", "高饱和鲜艳"),
    ("dark", "Dark", "暗调"),
    ("airy", "Airy", "明亮通透"),
])


def facet_label(facet: str) -> tuple[str, str]:
    """Return the (English, Chinese) display label for a facet."""
    try:
        return _FACET_LABELS[facet]
    except KeyError as exc:
        raise ValueError(f"Unknown facet {facet!r}.") from exc


def tags_of(facet: str) -> tuple[Tag, ...]:
    """Return the tags of one facet in declaration order."""
    if facet not in FACETS:
        raise ValueError(f"Unknown facet {facet!r}.")
    return tuple(tag for tag in TAGS.values() if tag.facet == facet)


def tag_ids(facet: str | None = None) -> list[str]:
    """Return tag ids, optionally restricted to one facet."""
    if facet is not None and facet not in FACETS:
        raise ValueError(f"Unknown facet {facet!r}.")
    return [tag.id for tag in TAGS.values() if facet is None or tag.facet == facet]


def resolve(tag_id: str) -> Tag:
    """Look up one tag by id; raise on unknown labels (closed taxonomy)."""
    try:
        return TAGS[tag_id]
    except KeyError as exc:
        raise ValueError(f"Unknown taxonomy tag {tag_id!r}.") from exc


def normalize_tags(tags: Iterable[str]) -> list[str]:
    """Canonicalize a label collection: de-duplicate, keep order, reject unknown.

    This is the closed-taxonomy gate every ingest path must pass through.
    """
    seen: set[str] = set()
    result: list[str] = []
    for tag_id in tags:
        resolve(tag_id)
        if tag_id not in seen:
            seen.add(tag_id)
            result.append(tag_id)
    return result
