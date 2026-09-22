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
DESIGN_METHODS = {
    "修辞导向": "rhetoric-graphic",
    "艺术指导导向": "art-graphic",
}
DELIVERY_CONTEXTS = [
    "手机阅读海报",
    "张贴或印刷海报",
    "小红书配图",
    "文章内插图",
    "微信公众号封面",
]
REFERENCE_MODES = {
    "以共同风格特征为约束": "style_grounded",
    "仅作为创意启发": "style_inspired",
}
GENERATION_MODES = {
    "无语料库生成": "without_corpus",
    "有语料库生成": "with_corpus",
}


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


def split_lines(value: str) -> list[str]:
    """Convert a multiline UI field into compact ordered strings."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def build_general_brief(
    *, deliverable: str, purpose: str, audience: str, use_context: str,
    exact_copy: str, constraints: str, preferences: str,
    canvas_mode: str, ratio_width: int = 1, ratio_height: int = 1,
    validate_required: bool = True,
) -> dict[str, Any]:
    """Build the open graphic-design brief without UI or model side effects."""
    required = {
        "交付类型": deliverable,
        "设计目的": purpose,
        "受众": audience,
        "使用与观看场景": use_context,
    }
    missing = [label for label, value in required.items() if not value.strip()]
    if validate_required and missing:
        raise ValueError(f"请填写：{'、'.join(missing)}。")
    canvas: dict[str, Any] = {"mode": canvas_mode}
    if canvas_mode == "fixed":
        canvas["aspect_ratio"] = {
            "width": int(ratio_width), "height": int(ratio_height),
        }
    return {
        "deliverable": deliverable.strip(),
        "purpose": purpose.strip(),
        "audience": audience.strip(),
        "use_context": use_context.strip(),
        "exact_copy": split_lines(exact_copy),
        "constraints": split_lines(constraints),
        "preferences": split_lines(preferences),
        "canvas": canvas,
    }


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
    case_brief = load_case(st.session_state.case_label)
    st.session_state.brief_editor = json.dumps(
        case_brief, ensure_ascii=False, indent=2,
    )
    st.session_state.selected_knowledge_ids = list(defaults["knowledge_ids"])
    st.session_state.selected_reference_ids = list(defaults["reference_ids"])
    has_corpus = bool(defaults["knowledge_ids"] or defaults["reference_ids"])
    st.session_state.example_generation_mode = (
        "有语料库生成" if has_corpus else "无语料库生成"
    )
    mode = case_brief.get("reference_mode")
    if mode:
        st.session_state.example_reference_mode = next(
            label for label, value in REFERENCE_MODES.items() if value == mode
        )


def _material_fields(*, show_references: bool) -> None:
    choices = load_material_choices(str(SNAPSHOT))
    knowledge = [item["id"] for item in choices if item["kind"] == "knowledge"]
    references = [item["id"] for item in choices if item["kind"] == "reference"]
    titles = {item["id"]: item["title"] for item in choices}
    st.multiselect(
        "知识材料（可留空，以测试无语料基线）",
        knowledge,
        key="selected_knowledge_ids",
        format_func=lambda material_id: titles[material_id],
    )
    if show_references:
        st.multiselect(
            "参考图像",
            references,
            key="selected_reference_ids",
            max_selections=3,
            format_func=lambda material_id: titles[material_id],
        )


def _new_design_inputs() -> tuple[str, str, dict[str, Any], list[str]]:
    method = st.segmented_control(
        "设计方法", list(DESIGN_METHODS), default=list(DESIGN_METHODS)[0],
        key="design_method",
    )
    generation_label = st.segmented_control(
        "研究模式", list(GENERATION_MODES), default="无语料库生成",
        key="new_generation_mode",
    )
    generation_mode = GENERATION_MODES[generation_label]
    deliverable = st.selectbox(
        "交付类型",
        DELIVERY_CONTEXTS,
        accept_new_options=True,
        placeholder="选择常见类型，或直接输入自定义场景",
        key="general_deliverable",
    )
    purpose = st.text_area(
        "设计目的", placeholder="希望这张图完成什么沟通任务？", key="general_purpose",
    )
    audience = st.text_input("受众", key="general_audience")
    use_context = st.text_area(
        "使用与观看场景",
        placeholder="在哪里出现、用什么设备或距离观看、是否可能裁切或印刷？",
        key="general_use_context",
    )
    exact_copy = st.text_area(
        "必须出现的文字（每行一项，可留空）", key="general_exact_copy",
    )
    with st.expander("补充要求", expanded=False):
        constraints = st.text_area("硬性限制（每行一项）", key="general_constraints")
        preferences = st.text_area("设计偏好（每行一项）", key="general_preferences")

    canvas_choice = st.segmented_control(
        "画布比例", ["由设计师决定", "指定比例"], default="由设计师决定",
        key="canvas_choice",
    )
    ratio_width, ratio_height = 1, 1
    if canvas_choice == "指定比例":
        ratio_columns = st.columns(2)
        ratio_width = ratio_columns[0].number_input(
            "宽度比例", min_value=1, max_value=100, value=4, step=1,
            key="ratio_width",
        )
        ratio_height = ratio_columns[1].number_input(
            "高度比例", min_value=1, max_value=100, value=5, step=1,
            key="ratio_height",
        )
    else:
        st.caption("设计师会依据交付类型、观看场景和内容层级提出比例，并说明理由。")

    brief = build_general_brief(
        deliverable=deliverable or "",
        purpose=purpose,
        audience=audience,
        use_context=use_context,
        exact_copy=exact_copy,
        constraints=constraints,
        preferences=preferences,
        canvas_mode="fixed" if canvas_choice == "指定比例" else "auto",
        ratio_width=int(ratio_width),
        ratio_height=int(ratio_height),
        validate_required=False,
    )
    reference_ids: list[str] = []
    if generation_mode == "with_corpus":
        with st.expander("选择语料材料", expanded=True):
            _material_fields(show_references=True)
        reference_ids = list(st.session_state.get("selected_reference_ids", []))
        if reference_ids:
            reference_label = st.selectbox(
                "参考图使用策略", list(REFERENCE_MODES), key="general_reference_mode",
            )
            brief.update(
                reference_mode=REFERENCE_MODES[reference_label],
                reference_scope="selected_snapshot_images",
                reference_count=len(reference_ids),
            )
    return DESIGN_METHODS[method], generation_mode, brief, reference_ids


def _example_inputs() -> tuple[str, str, dict[str, Any], list[str]]:
    if "case_label" not in st.session_state:
        st.session_state.case_label = next(iter(CASES))
    if "brief_editor" not in st.session_state:
        _change_case()
    st.selectbox(
        "选择示例", list(CASES), key="case_label", on_change=_change_case,
    )
    generation_label = st.segmented_control(
        "研究模式", list(GENERATION_MODES), key="example_generation_mode",
    )
    generation_mode = GENERATION_MODES[generation_label]
    with st.expander("编辑内容", expanded=False):
        st.text_area("Brief（JSON）", height=280, key="brief_editor")
    brief = parse_brief(st.session_state.brief_editor)
    reference_ids: list[str] = []
    if generation_mode == "with_corpus":
        with st.expander("选择语料材料", expanded=True):
            _material_fields(show_references=True)
        reference_ids = list(st.session_state.get("selected_reference_ids", []))
    if generation_mode == "with_corpus" and reference_ids:
        reference_label = st.selectbox(
            "参考图使用策略", list(REFERENCE_MODES), key="example_reference_mode",
        )
        brief.update(
            reference_mode=REFERENCE_MODES[reference_label],
            reference_count=len(reference_ids),
            reference_scope="selected_snapshot_images",
        )
    else:
        for field in ("reference_mode", "reference_count", "reference_scope"):
            brief.pop(field, None)
    return CASES[st.session_state.case_label][0], generation_mode, brief, reference_ids


def _validate_start_inputs(
    generation_mode: str, brief: dict[str, Any], reference_ids: list[str],
) -> None:
    if "deliverable" in brief:
        required = {
            "交付类型": brief["deliverable"],
            "设计目的": brief["purpose"],
            "受众": brief["audience"],
            "使用与观看场景": brief["use_context"],
        }
        missing = [label for label, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(f"请填写：{'、'.join(missing)}。")
    if generation_mode == "with_corpus" and not (
        st.session_state.get("selected_knowledge_ids") or reference_ids
    ):
        raise ValueError("有语料库生成至少需要选择一项语料材料。")
    if brief.get("reference_mode") and not reference_ids:
        raise ValueError("使用参考图模式时，至少选择一张参考图像。")


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
    start_mode = st.segmented_control(
        "开始方式", ["新建设计", "使用示例"], default="新建设计", key="start_mode",
    )

    try:
        if start_mode == "新建设计":
            profile, generation_mode, brief, reference_ids = _new_design_inputs()
        else:
            profile, generation_mode, brief, reference_ids = _example_inputs()
        input_error: Exception | None = None
    except (json.JSONDecodeError, ValueError) as exc:
        profile, generation_mode, brief, reference_ids = "", "", {}, []
        input_error = exc

    if not st.button("生成设计方案", type="primary", width="stretch"):
        return
    try:
        if input_error is not None:
            raise input_error
        _validate_start_inputs(generation_mode, brief, reference_ids)
        materials = None
        snapshot = None
        if generation_mode == "with_corpus":
            materials = {
                "format_version": 1,
                "knowledge_ids": list(st.session_state.get("selected_knowledge_ids", [])),
                "reference_ids": reference_ids,
            }
            snapshot = SNAPSHOT
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在准备设计方案…"):
            result = app.start(DesignJob(
                profile=profile,
                brief=brief,
                generation_mode=generation_mode,
                snapshot=snapshot,
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
    manifest = read_json_artifact(result, "manifest")
    mode_label = {
        "without_corpus": "无语料库生成",
        "with_corpus": "有语料库生成",
    }.get(manifest.get("generation_mode"))
    if mode_label:
        st.caption(f"研究模式：{mode_label}")
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
    canvas_plan = (proposal.get("image_spec") or {}).get("canvas_plan")
    if canvas_plan:
        ratio = canvas_plan["aspect_ratio"]
        st.info(
            f"画布：{canvas_plan['format']} · {ratio['width']}:{ratio['height']} · "
            f"{canvas_plan['orientation']}\n\n{canvas_plan['size_rationale']}"
        )
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
    st.caption("比较无语料库与显式语料库条件的可复现图像生成实验")

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
