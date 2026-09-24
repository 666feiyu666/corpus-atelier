"""Streamlit adapter for the approval-gated, single-generation workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.materials import list_references
from corpus_atelier.state import HumanDecision, NaturalLanguageDesignJob, RunResult


ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
PRODUCT_CASE_ID = "natural-language"
TERMINAL_STATUSES = {"completed", "rejected", "failed"}
DESIGN_METHODS = {
    "修辞导向": "rhetoric-graphic",
    "艺术指导导向": "art-graphic",
}
GENERATION_MODES = {
    "无语料库生成": "without_corpus",
    "有语料库生成": "with_corpus",
}


@st.cache_data(max_entries=4)
def load_reference_choices(snapshot: str) -> list[dict[str, str]]:
    """Load verified reference labels once per snapshot path."""
    return list_references(snapshot)


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
    for key in (
        "atelier_app", "result", "ui_error", "ui_failed", "natural_request",
        "design_method", "new_generation_mode", "selected_reference_id",
    ):
        st.session_state.pop(key, None)


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


def _natural_request_inputs() -> tuple[str, str, str, str | None]:
    request = st.text_area(
        "描述你的设计需求",
        height=220,
        placeholder=(
            "可以直接说你遇到的情境、希望设计起什么作用、给谁看，以及你已经有的想法。"
            "不需要整理成字段。"
        ),
        key="natural_request",
    )
    reference_id: str | None = None
    with st.expander("研究设置", expanded=False):
        method = st.segmented_control(
            "设计方法", list(DESIGN_METHODS), default=list(DESIGN_METHODS)[0],
            key="design_method",
        )
        generation_label = st.segmented_control(
            "研究模式", list(GENERATION_MODES), default="无语料库生成",
            key="new_generation_mode",
        )
        generation_mode = GENERATION_MODES[generation_label]
        if generation_mode == "with_corpus":
            reference_id = _reference_field()
    return DESIGN_METHODS[method], generation_mode, request, reference_id


def _resume(decision: HumanDecision, message: str) -> None:
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
    profile, generation_mode, request, reference_id = _natural_request_inputs()

    if not st.button("生成设计方案", type="primary", width="stretch"):
        return
    if not request.strip():
        st.error("实验输入有误：请先描述你的设计需求。")
        return
    if generation_mode == "with_corpus" and not reference_id:
        st.error("实验输入有误：有语料库生成需要选择一张参考图像。")
        return
    try:
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
        with st.spinner("正在理解需求并准备设计方案…"):
            result = app.start_request(NaturalLanguageDesignJob(
                case_id=PRODUCT_CASE_ID,
                profile=profile,
                request=request,
                generation_mode=generation_mode,
                snapshot=snapshot,
                reference=reference,
            ))
        st.session_state.atelier_app = app
        st.session_state.result = result
        st.session_state.ui_error = ""
        st.session_state.ui_failed = False
        st.rerun()
    except Exception as exc:
        st.error(f"无法生成设计方案：{exc}")


def _generation_preview_page(result: RunResult) -> None:
    proposal = read_json_artifact(result, "proposal")
    brief = read_json_artifact(result, "brief")
    st.subheader("图像模型输入预览")
    st.info("以下内容尚未发送给图像模型。确认无误后，再开始生成图片。")
    manifest = read_json_artifact(result, "manifest")
    mode_label = {
        "without_corpus": "无语料库生成",
        "with_corpus": "有语料库生成",
    }.get(manifest.get("generation_mode"))
    if mode_label:
        st.caption(f"研究模式：{mode_label}")
    if brief:
        with st.expander("系统理解的需求", expanded=False):
            st.markdown(f"**交付物：** {brief.get('deliverable', '未记录')}")
            st.markdown(f"**目的：** {brief.get('purpose', '未记录')}")
            st.markdown(f"**受众：** {brief.get('audience', '未记录')}")
            st.markdown(f"**使用场景：** {brief.get('use_context', '未记录')}")
            exact_copy = brief.get("exact_copy", [])
            if exact_copy:
                st.markdown("**画面文字：**")
                for item in exact_copy:
                    st.markdown(f"- {item}")
    st.markdown("**设计方案**")
    st.write(proposal.get("chosen_direction", "设计方案已准备完成。"))
    description = proposal.get("design_description")
    if description:
        with st.expander("完整视觉描述", expanded=True):
            st.write(description)
    rationale = proposal.get("design_rationale")
    if rationale:
        st.caption(rationale)
    request = read_json_artifact(result, "generation_request_preview")
    generation_prompt = read_text_artifact(result, "generation_prompt")
    with st.container(border=True):
        st.markdown("**将发送的请求**")
        if request:
            parameters = [
                f"模型：`{request.get('model', '未记录')}`",
                f"质量：`{request.get('quality', '未记录')}`",
                f"尺寸：`{request.get('size', '未记录')}`",
                f"格式：`{request.get('output_format', '未记录')}`",
            ]
            st.markdown(" · ".join(parameters))
        reference_image = result.artifacts.get("reference_image")
        if reference_image:
            with st.expander("参考图片", expanded=True):
                st.image(reference_image, width="stretch")
        if generation_prompt:
            with st.expander("完整提示词", expanded=True):
                st.code(generation_prompt, language=None, wrap_lines=True)
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(
            "取消本次生成", key="cancel_generation", width="content",
        ):
            _resume(
                HumanDecision(False, reviewer="streamlit-user"),
                "正在取消本次生成…",
            )
        if st.button(
            "发送并生成图片", type="primary", key="send_generation",
            width="content",
        ):
            _resume(
                HumanDecision(True, reviewer="streamlit-user"),
                "正在生成图片…",
            )


def _terminal_page(result: RunResult) -> None:
    labels = {
        "completed": "生成完成",
        "rejected": "本次图像生成已取消",
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
    st.caption("用自然语言描述情境和目标，把想法转化为可审阅的视觉设计")

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
        _generation_preview_page(result)
    elif result.status in TERMINAL_STATUSES:
        _terminal_page(result)
    else:
        st.info("工作流正在处理，请稍候刷新。")


if __name__ == "__main__":
    main()
