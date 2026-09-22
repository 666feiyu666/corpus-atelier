"""Streamlit adapter for the approval-gated, single-generation workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.artifacts.store import validate_case_id
from corpus_atelier.materials import list_references
from corpus_atelier.state import DesignJob, FinalDecision, HumanDecision, RunResult


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
DEFAULT_REFERENCE = "mucha-poster-124474277"
CASES = {
    "工作坊海报": (
        "poster-01",
        "rhetoric-poster",
        ROOT / "experiments/cases/poster-01/brief.json",
        None,
    ),
    "文章封面": (
        "article-cover-01",
        "art-article-cover",
        ROOT / "experiments/cases/article-cover-01/brief.json",
        None,
    ),
    "AURELIA 女士手表广告": (
        "mucha-watch",
        "rhetoric-poster",
        ROOT / "experiments/cases/mucha-watch/brief.json",
        DEFAULT_REFERENCE,
    ),
}
CASE_REFERENCE_MODES = {
    "AURELIA 女士手表广告": "style_grounded",
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
DELIVERY_RATIOS = {
    "手机阅读海报": (4, 5),
    "张贴或印刷海报": (2, 3),
    "小红书配图": (3, 4),
    "文章内插图": (16, 9),
    "微信公众号封面": (47, 20),
}
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
    return json.loads(CASES[label][2].read_text(encoding="utf-8"))


@st.cache_data(max_entries=4)
def load_reference_choices(snapshot: str) -> list[dict[str, str]]:
    """Load verified reference labels once per snapshot path."""
    return list_references(snapshot)


def parse_brief(value: str) -> dict[str, Any]:
    """Parse a brief while keeping UI validation separate from model calls."""
    brief = json.loads(value)
    if not isinstance(brief, dict):
        raise ValueError("Brief 必须是一个 JSON 对象。")
    return brief


def split_lines(value: str) -> list[str]:
    """Convert a multiline UI field into compact ordered strings."""
    return [line.strip() for line in value.splitlines() if line.strip()]


def delivery_ratio(deliverable: str) -> tuple[int, int] | None:
    """Return the UI-owned ratio for a known delivery context."""
    return DELIVERY_RATIOS.get(deliverable)


def build_general_brief(
    *, deliverable: str, purpose: str, audience: str, use_context: str,
    exact_copy: str, constraints: str, preferences: str,
    ratio_width: int, ratio_height: int,
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
    return {
        "deliverable": deliverable.strip(),
        "purpose": purpose.strip(),
        "audience": audience.strip(),
        "use_context": use_context.strip(),
        "exact_copy": split_lines(exact_copy),
        "constraints": split_lines(constraints),
        "preferences": split_lines(preferences),
        "canvas": {
            "aspect_ratio": {
                "width": int(ratio_width), "height": int(ratio_height),
            },
        },
    }


def read_json_artifact(result: RunResult, name: str) -> dict[str, Any]:
    path = result.artifacts.get(name)
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_text_artifact(result: RunResult, name: str) -> str:
    path = result.artifacts.get(name)
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8")


def _reset() -> None:
    for key in ("atelier_app", "result", "ui_error", "ui_failed"):
        st.session_state.pop(key, None)


def _change_case() -> None:
    _, _, _, defaults = CASES[st.session_state.case_label]
    case_brief = load_case(st.session_state.case_label)
    st.session_state.brief_editor = json.dumps(
        case_brief, ensure_ascii=False, indent=2,
    )
    st.session_state.selected_reference_id = defaults
    has_corpus = defaults is not None
    st.session_state.example_generation_mode = (
        "有语料库生成" if has_corpus else "无语料库生成"
    )
    mode = CASE_REFERENCE_MODES.get(st.session_state.case_label)
    if mode:
        st.session_state.example_reference_mode = next(
            label for label, value in REFERENCE_MODES.items() if value == mode
        )


def _reference_field() -> str | None:
    choices = load_reference_choices(str(SNAPSHOT))
    references = [item["id"] for item in choices]
    titles = {item["id"]: item["title"] for item in choices}
    return st.selectbox(
        "参考图像",
        references,
        key="selected_reference_id",
        format_func=lambda reference_id: titles[reference_id],
    )


def _new_design_inputs() -> tuple[str, str, dict[str, Any], str | None, str | None, str]:
    case_id = st.text_input(
        "Case ID",
        placeholder="例如 reading-group-poster",
        help="用于将本次运行归档到 experiments/runs/<case-id>/。",
        key="new_case_id",
    )
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

    fixed_ratio = delivery_ratio(deliverable or "")
    if fixed_ratio is not None:
        ratio_width, ratio_height = fixed_ratio
        st.caption(f"画布比例：{ratio_width}:{ratio_height}（由交付类型确定）")
    else:
        st.caption("自定义交付类型的画布比例")
        ratio_columns = st.columns(2)
        ratio_width = ratio_columns[0].number_input(
            "宽度比例", min_value=1, max_value=100, value=4, step=1,
            key="ratio_width",
        )
        ratio_height = ratio_columns[1].number_input(
            "高度比例", min_value=1, max_value=100, value=5, step=1,
            key="ratio_height",
        )

    brief = build_general_brief(
        deliverable=deliverable or "",
        purpose=purpose,
        audience=audience,
        use_context=use_context,
        exact_copy=exact_copy,
        constraints=constraints,
        preferences=preferences,
        ratio_width=int(ratio_width),
        ratio_height=int(ratio_height),
        validate_required=False,
    )
    reference_id: str | None = None
    reference_mode: str | None = None
    if generation_mode == "with_corpus":
        with st.expander("选择参考图", expanded=True):
            reference_id = _reference_field()
        reference_label = st.selectbox(
            "参考图使用策略", list(REFERENCE_MODES), key="general_reference_mode",
        )
        reference_mode = REFERENCE_MODES[reference_label]
    return DESIGN_METHODS[method], generation_mode, brief, reference_id, reference_mode, case_id


def _example_inputs() -> tuple[str, str, dict[str, Any], str | None, str | None, str]:
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
    reference_id: str | None = None
    reference_mode: str | None = None
    if generation_mode == "with_corpus":
        with st.expander("选择参考图", expanded=True):
            reference_id = _reference_field()
        reference_label = st.selectbox(
            "参考图使用策略", list(REFERENCE_MODES), key="example_reference_mode",
        )
        reference_mode = REFERENCE_MODES[reference_label]
    case_id, profile, _, _ = CASES[st.session_state.case_label]
    return profile, generation_mode, brief, reference_id, reference_mode, case_id


def _validate_start_inputs(
    generation_mode: str, brief: dict[str, Any], reference_id: str | None,
    reference_mode: str | None, case_id: str,
) -> None:
    validate_case_id(case_id)
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
    if generation_mode == "with_corpus" and not reference_id:
        raise ValueError("有语料库生成需要选择一张参考图像。")
    if generation_mode == "with_corpus" and not reference_mode:
        raise ValueError("有语料库生成需要选择参考图使用策略。")
    if generation_mode == "without_corpus" and reference_mode is not None:
        raise ValueError("无语料库生成不能包含参考图使用策略。")


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
            profile, generation_mode, brief, reference_id, reference_mode, case_id = (
                _new_design_inputs()
            )
        else:
            profile, generation_mode, brief, reference_id, reference_mode, case_id = (
                _example_inputs()
            )
        input_error: Exception | None = None
    except (json.JSONDecodeError, ValueError) as exc:
        profile, generation_mode, brief, reference_id, reference_mode, case_id = (
            "", "", {}, None, None, ""
        )
        input_error = exc

    if not st.button("生成设计方案", type="primary", width="stretch"):
        return
    try:
        if input_error is not None:
            raise input_error
        _validate_start_inputs(
            generation_mode, brief, reference_id, reference_mode, case_id,
        )
        reference = None
        snapshot = None
        if generation_mode == "with_corpus":
            reference = {
                "format_version": 1,
                "reference_id": reference_id,
            }
            snapshot = SNAPSHOT
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在准备设计方案…"):
            result = app.start(DesignJob(
                case_id=case_id,
                profile=profile,
                brief=brief,
                generation_mode=generation_mode,
                reference_mode=reference_mode,
                snapshot=snapshot,
                reference=reference,
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
    reference_image = result.artifacts.get("reference_image")
    if reference_image:
        st.caption(f"参考关系：{manifest.get('reference_mode', 'unknown')}")
        with st.expander("查看所选参考图"):
            st.image(reference_image, width="stretch")
    st.write(proposal.get("chosen_direction", "设计方案已准备完成。"))
    rationale = proposal.get("design_rationale")
    if rationale:
        st.caption(rationale)
    canvas = read_json_artifact(result, "canvas")
    if canvas:
        ratio = canvas["ratio"]
        st.info(f"画布：{ratio[0]}:{ratio[1]} · {canvas['size']} px")
    generation_prompt = read_text_artifact(result, "generation_prompt")
    if generation_prompt:
        with st.expander("发送给图像模型的完整提示词", expanded=True):
            st.code(generation_prompt, language=None, wrap_lines=True)
    approve, reject = st.columns(2)
    if approve.button("批准并生成", type="primary", width="stretch"):
        _resume(HumanDecision(True, reviewer="streamlit-user"), "正在生成图片…")
    if reject.button("放弃", width="stretch"):
        _resume(HumanDecision(False, reviewer="streamlit-user"), "正在结束本次实验…")


def _final_decision_page(result: RunResult) -> None:
    st.subheader("查看实验结果")
    _show_image(result)
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
