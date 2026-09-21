"""Streamlit adapter for the review-gated, single-generation workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.materials import list_materials
from corpus_atelier.state import DesignJob, FinalDecision, HumanDecision, RunResult


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
DEFAULT_KNOWLEDGE = [
    "mucha-commercial-color-print-character",
    "mucha-commercial-product-rhetoric",
    "mucha-commercial-vertical-figure-organization",
]
DEFAULT_REFERENCES = ["mucha-poster-124474277"]
CASES = {
    "工作坊海报": (
        "rhetoric-poster",
        ROOT / "experiments/cases/poster-01/brief.json",
        {"knowledge_ids": ["mucha-commercial-lettering-image-integration"], "reference_ids": []},
    ),
    "文章封面": (
        "art-article-cover",
        ROOT / "experiments/cases/article-cover-01/brief.json",
        {"knowledge_ids": ["mucha-commercial-lettering-image-integration"], "reference_ids": []},
    ),
    "慕夏风格女士手表广告": (
        "rhetoric-poster",
        ROOT / "experiments/cases/mucha-watch/grounded-brief.json",
        {"knowledge_ids": DEFAULT_KNOWLEDGE, "reference_ids": DEFAULT_REFERENCES},
    ),
    "慕夏启发女士手表广告": (
        "rhetoric-poster",
        ROOT / "experiments/cases/mucha-watch/inspired-brief.json",
        {"knowledge_ids": DEFAULT_KNOWLEDGE, "reference_ids": DEFAULT_REFERENCES},
    ),
}
TERMINAL_STATUSES = {"completed", "rejected", "discarded", "failed"}


def load_case(label: str) -> dict[str, Any]:
    """Load one bundled example brief."""
    return json.loads(CASES[label][1].read_text(encoding="utf-8"))


@st.cache_data(max_entries=4)
def load_material_choices(snapshot: str) -> list[dict[str, str]]:
    """Load verified material labels once per snapshot path."""
    return list_materials(snapshot)


def parse_brief(value: str) -> dict[str, Any]:
    """Parse a brief while keeping UI validation separate from model calls."""
    brief = json.loads(value)
    if not isinstance(brief, dict):
        raise ValueError("Brief 必须是一个 JSON 对象。")
    return brief


def read_json_artifact(result: RunResult, name: str) -> dict[str, Any]:
    path = result.artifacts.get(name)
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def review_points(review: dict[str, Any]) -> list[str]:
    """Return concise, user-facing review findings."""
    points = list(review.get("observations", []))
    points.extend(review.get("priority_actions", []))
    return points


def _reset() -> None:
    for key in ("atelier_app", "result", "ui_error", "ui_failed"):
        st.session_state.pop(key, None)


def _change_case() -> None:
    _, _, defaults = CASES[st.session_state.case_label]
    st.session_state.brief_editor = json.dumps(
        load_case(st.session_state.case_label), ensure_ascii=False, indent=2,
    )
    st.session_state.selected_knowledge_ids = list(defaults["knowledge_ids"])
    st.session_state.selected_reference_ids = list(defaults["reference_ids"])


def _resume(decision: HumanDecision | FinalDecision, message: str) -> None:
    app: CorpusAtelierApplication = st.session_state.atelier_app
    result: RunResult = st.session_state.result
    st.session_state.ui_error = ""
    try:
        with st.spinner(message):
            st.session_state.result = app.resume(result.run_id, decision)
    except Exception as exc:  # Streamlit turns provider failures into a recoverable page.
        st.session_state.ui_error = str(exc)
        st.session_state.ui_failed = True
    st.rerun()


def _show_review(result: RunResult) -> None:
    review = read_json_artifact(result, "review")
    if not review:
        return
    verdict = {"accept": "建议接受", "revise": "建议重新实验", "reject": "建议放弃"}.get(
        review.get("verdict"), "审查完成",
    )
    st.caption(f"自动审查：{verdict}")
    points = review_points(review)
    if points:
        with st.expander("查看审查要点"):
            for point in points:
                st.write(f"- {point}")


def _show_image(result: RunResult) -> None:
    image = result.artifacts.get("image")
    if image:
        st.image(image, caption="生成结果", width="stretch")


def _start_page() -> None:
    st.subheader("开始一个实验")
    if "case_label" not in st.session_state:
        st.session_state.case_label = next(iter(CASES))
    if "brief_editor" not in st.session_state:
        _change_case()

    st.selectbox(
        "选择示例", list(CASES), key="case_label", on_change=_change_case,
    )
    case_brief = load_case(st.session_state.case_label)
    choices = load_material_choices(str(SNAPSHOT))
    knowledge = [item["id"] for item in choices if item["kind"] == "knowledge"]
    references = [item["id"] for item in choices if item["kind"] == "reference"]
    titles = {item["id"]: item["title"] for item in choices}

    with st.expander("选择语料材料", expanded=bool(case_brief.get("reference_mode"))):
        st.multiselect(
            "知识材料",
            knowledge,
            key="selected_knowledge_ids",
            format_func=lambda material_id: titles[material_id],
        )
        if case_brief.get("reference_mode"):
            st.multiselect(
                "参考图像",
                references,
                key="selected_reference_ids",
                max_selections=3,
                format_func=lambda material_id: titles[material_id],
            )

    with st.expander("编辑内容", expanded=False):
        st.text_area("Brief（JSON）", height=280, key="brief_editor")

    if not st.button("生成设计方案", type="primary", width="stretch"):
        return
    try:
        brief = parse_brief(st.session_state.brief_editor)
        reference_ids = list(st.session_state.get("selected_reference_ids", []))
        if brief.get("reference_mode"):
            if not reference_ids:
                raise ValueError("使用参考模式时，至少选择一张参考图像。")
            brief["reference_count"] = len(reference_ids)
            brief["reference_scope"] = "selected_snapshot_images"
        else:
            reference_ids = []
        materials = {
            "format_version": 1,
            "knowledge_ids": list(st.session_state.get("selected_knowledge_ids", [])),
            "reference_ids": reference_ids,
        }
        profile = CASES[st.session_state.case_label][0]
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在准备设计方案…"):
            result = app.start(DesignJob(
                profile=profile,
                brief=brief,
                snapshot=SNAPSHOT,
                materials=materials,
            ))
        st.session_state.atelier_app = app
        st.session_state.result = result
        st.session_state.ui_error = ""
        st.session_state.ui_failed = False
        st.rerun()
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"实验输入有误：{exc}")
    except Exception as exc:
        st.error(f"无法生成设计方案：{exc}")


def _approval_page(result: RunResult) -> None:
    proposal = read_json_artifact(result, "proposal")
    st.subheader("设计方案")
    reference_plan = read_json_artifact(result, "reference_plan")
    if reference_plan:
        package = read_json_artifact(result, "materials_package")
        count = len(package.get("references", []))
        st.caption(
            f"参考关系：{reference_plan.get('mode', 'unknown')} · 已选 {count} 张参考图"
        )
        with st.expander("查看参考使用提案"):
            st.json(reference_plan)
        images = sorted(
            (name, path) for name, path in result.artifacts.items()
            if name.startswith("reference_image_")
        )
        if images:
            with st.expander("查看所选参考图"):
                columns = st.columns(3)
                for index, (_, path) in enumerate(images):
                    columns[index % 3].image(path, width="stretch")
    st.write(proposal.get("chosen_direction", "设计方案已准备完成。"))
    rationale = proposal.get("design_rationale")
    if rationale:
        st.caption(rationale)
    approve, reject = st.columns(2)
    if approve.button("批准并生成", type="primary", width="stretch"):
        _resume(HumanDecision(True, reviewer="streamlit-user"), "正在生成并审查图片…")
    if reject.button("放弃", width="stretch"):
        _resume(HumanDecision(False, reviewer="streamlit-user"), "正在结束本次实验…")


def _final_decision_page(result: RunResult) -> None:
    st.subheader("查看实验结果")
    _show_image(result)
    _show_review(result)
    accept, discard = st.columns(2)
    if accept.button("接受结果", type="primary", width="stretch"):
        _resume(FinalDecision("accept", reviewer="streamlit-user"), "正在保存决定…")
    if discard.button("放弃结果", width="stretch"):
        _resume(FinalDecision("discard", reviewer="streamlit-user"), "正在结束本次实验…")


def _terminal_page(result: RunResult) -> None:
    labels = {
        "completed": "实验结果已接受",
        "rejected": "已放弃图像生成",
        "discarded": "实验结果已放弃",
        "failed": "本次实验失败",
    }
    st.subheader(labels.get(result.status, "本次实验已结束"))
    _show_image(result)
    if st.button("开始新实验", type="primary", width="stretch"):
        _reset()
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Corpus Atelier", page_icon="◫", layout="centered")
    st.title("Corpus Atelier")
    st.caption("从选定语料到单次图像生成的可复现实验工作台")

    if st.session_state.get("ui_error"):
        st.error(f"操作失败：{st.session_state.ui_error}")
    if st.session_state.get("ui_failed"):
        if st.button("重新开始", type="primary", width="stretch"):
            _reset()
            st.rerun()
        return

    result: RunResult | None = st.session_state.get("result")
    if result is None:
        _start_page()
    elif result.status == "awaiting_approval":
        _approval_page(result)
    elif result.status == "awaiting_final_decision":
        _final_decision_page(result)
    elif result.status in TERMINAL_STATUSES:
        _terminal_page(result)
    else:
        st.info("工作流正在处理，请稍候刷新。")


if __name__ == "__main__":
    main()
