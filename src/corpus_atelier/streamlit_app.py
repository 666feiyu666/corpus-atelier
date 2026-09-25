"""Streamlit adapter for the product and corpus-comparison workflows."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import (
    ComparisonResult,
    CorpusComparisonJob,
    CorpusExperimentJob,
    HumanDecision,
    NaturalLanguageDesignJob,
    RunResult,
)


ROOT = Path(__file__).resolve().parents[2]
PRODUCT_CASE_ID = "natural-language"
SNAPSHOT = ROOT / "experiments/atlas-snapshot/mucha-commercial"
REFERENCE = {
    "format_version": 1,
    "reference_id": "mucha-poster-124474232",
}
TERMINAL_STATUSES = {"completed", "rejected", "failed"}
DESIGN_METHODS = {
    "修辞导向": "rhetoric-graphic",
    "艺术指导导向": "art-graphic",
}
EXPERIMENT_MODES = {
    "成对比较": "paired",
    "无显式语料": "baseline_no_explicit_corpus",
    "有显式语料": "explicit_corpus",
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


def _reset_design() -> None:
    for key in (
        "design_app",
        "design_result",
        "design_ui_error",
        "design_ui_failed",
        "design_request",
        "design_method",
    ):
        st.session_state.pop(key, None)


def _reset_experiment() -> None:
    for key in (
        "experiment_app",
        "experiment_result",
        "experiment_ui_error",
        "experiment_ui_failed",
        "experiment_request",
        "experiment_design_method",
        "experiment_mode",
        "comparison_result",
    ):
        st.session_state.pop(key, None)


def _brand() -> None:
    st.title("Corpus Atelier")


def _design_inputs() -> tuple[str, str]:
    request = st.text_area(
        "描述你的设计需求",
        height=220,
        placeholder="制作一张穆夏风格的手表广告……",
        key="design_request",
    )
    method = st.segmented_control(
        "设计偏好",
        list(DESIGN_METHODS),
        default=list(DESIGN_METHODS)[0],
        key="design_method",
    )
    return DESIGN_METHODS[method], request


def _experiment_inputs() -> tuple[str, str, str]:
    request = st.text_area(
        "描述你的设计需求",
        height=220,
        placeholder="制作一张穆夏风格的手表广告……",
        key="experiment_request",
    )
    method = st.segmented_control(
        "设计偏好",
        list(DESIGN_METHODS),
        default=list(DESIGN_METHODS)[0],
        key="experiment_design_method",
    )
    mode_label = st.segmented_control(
        "实验条件",
        list(EXPERIMENT_MODES),
        default="成对比较",
        key="experiment_mode",
    )
    with st.expander("实验材料", expanded=False):
        st.markdown("**Mucha/JOB corpus**")
        st.caption(
            "实验比较模型既有知识与显式语料证据。参考图不会直接发送给图像生成模型。"
        )
    return DESIGN_METHODS[method], request, EXPERIMENT_MODES[mode_label]


def _resume(
    decision: HumanDecision,
    message: str,
    *,
    scope: str,
    arm: str | None = None,
) -> None:
    app: CorpusAtelierApplication = st.session_state[f"{scope}_app"]
    comparison: ComparisonResult | None = (
        st.session_state.get("comparison_result") if scope == "experiment" else None
    )
    result: RunResult = (
        getattr(comparison, arm)
        if comparison is not None and arm
        else st.session_state[f"{scope}_result"]
    )
    st.session_state[f"{scope}_ui_error"] = ""
    try:
        with st.spinner(message):
            updated = app.resume(result.run_id, decision)
            if comparison is not None and arm:
                st.session_state.comparison_result = replace(
                    comparison, **{arm: updated},
                )
            else:
                st.session_state[f"{scope}_result"] = updated
    except Exception as exc:  # Streamlit turns provider failures into a recoverable page.
        st.session_state[f"{scope}_ui_error"] = str(exc)
        st.session_state[f"{scope}_ui_failed"] = True
    st.rerun()


def _show_image(result: RunResult) -> None:
    image = result.artifacts.get("image")
    if image:
        st.image(image, caption="生成结果", width="stretch")


def _start_design() -> None:
    st.subheader("创建设计")
    st.caption("说说你想做一张怎样的平面设计吧。一句话也可以，写得越具体越好。")
    profile, request = _design_inputs()

    if not st.button(
        "生成设计方案",
        type="primary",
        width="stretch",
        key="start_design",
    ):
        return
    if not request.strip():
        st.error("请先描述你的设计需求。")
        return
    try:
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在理解需求并准备设计方案…"):
            result = app.start_request(NaturalLanguageDesignJob(
                case_id=PRODUCT_CASE_ID,
                profile=profile,
                request=request,
            ))
        st.session_state.design_app = app
        st.session_state.design_result = result
        st.session_state.design_ui_error = ""
        st.session_state.design_ui_failed = False
        st.rerun()
    except Exception as exc:
        st.error(f"无法生成设计方案：{exc}")


def _start_experiment() -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader("语料对比实验")
        st.badge("实验性", icon=":material/science:", color="orange")
    st.caption(
        "用同一份设计需求，对比模型仅依赖既有知识与使用显式语料证据时的设计结果。"
    )
    profile, request, run_mode = _experiment_inputs()

    button_label = "开始对比实验" if run_mode == "paired" else "开始实验"
    if not st.button(
        button_label,
        type="primary",
        width="stretch",
        key="start_experiment",
    ):
        return
    if not request.strip():
        st.error("请先描述用于实验的设计需求。")
        return
    try:
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在准备实验方案…"):
            if run_mode == "paired":
                comparison = app.start_comparison(CorpusComparisonJob(
                    case_id=PRODUCT_CASE_ID,
                    profile=profile,
                    request=request,
                    snapshot=SNAPSHOT,
                    reference=REFERENCE,
                ))
                result = None
            else:
                explicit = run_mode == "explicit_corpus"
                result = app.start_experiment(CorpusExperimentJob(
                    case_id=PRODUCT_CASE_ID,
                    profile=profile,
                    request=request,
                    condition=run_mode,
                    snapshot=SNAPSHOT if explicit else None,
                    reference=REFERENCE if explicit else None,
                ))
                comparison = None
        st.session_state.experiment_app = app
        st.session_state.experiment_result = result
        st.session_state.comparison_result = comparison
        st.session_state.experiment_ui_error = ""
        st.session_state.experiment_ui_failed = False
        st.rerun()
    except Exception as exc:
        st.error(f"无法开始实验：{exc}")


def _generation_preview_page(
    result: RunResult,
    *,
    scope: str,
    key_prefix: str = "",
    show_heading: bool = True,
) -> None:
    action_key = f"{scope}_{key_prefix}_" if key_prefix else f"{scope}_"
    proposal = read_json_artifact(result, "proposal")
    brief = read_json_artifact(result, "brief")
    if show_heading:
        st.subheader("图像模型输入预览")
    st.info("以下内容尚未发送给图像模型。确认无误后，再开始生成图片。")
    manifest = read_json_artifact(result, "manifest")
    condition = manifest.get("experiment", {}).get("condition")
    if condition:
        label = {
            "baseline_no_explicit_corpus": "无显式语料基线",
            "explicit_corpus": "有显式语料",
        }[condition]
        st.caption(f"实验条件：{label}")
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
            with st.expander("实验使用的 corpus 参考图", expanded=False):
                st.image(reference_image, width="stretch")
        if generation_prompt:
            with st.expander("完整提示词", expanded=True):
                st.code(generation_prompt, language=None, wrap_lines=True)
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button(
            "取消本次生成",
            key=f"{action_key}cancel_generation",
            width="content",
        ):
            _resume(
                HumanDecision(False, reviewer="streamlit-user"),
                "正在取消本次生成…",
                scope=scope,
                arm=key_prefix or None,
            )
        if st.button(
            "发送并生成图片",
            type="primary",
            key=f"{action_key}send_generation",
            width="content",
        ):
            _resume(
                HumanDecision(True, reviewer="streamlit-user"),
                "正在生成图片…",
                scope=scope,
                arm=key_prefix or None,
            )


def _comparison_page(comparison: ComparisonResult) -> None:
    st.subheader("有／无显式语料对比实验")
    st.caption(
        "两个条件共享同一次自然语言解释和同一个冻结 brief；"
        "每个条件仍需独立审批后才会调用图像模型。"
    )
    for arm, label in (
        ("baseline", "无显式语料基线"),
        ("corpus", "有显式语料"),
    ):
        result: RunResult = getattr(comparison, arm)
        with st.container(border=True):
            st.markdown(f"### {label}")
            if result.status == "awaiting_approval":
                _generation_preview_page(
                    result,
                    scope="experiment",
                    key_prefix=arm,
                    show_heading=False,
                )
            elif result.status in TERMINAL_STATUSES:
                terminal_label = {
                    "completed": "生成完成",
                    "rejected": "已取消",
                    "failed": "运行失败",
                }[result.status]
                st.markdown(f"**状态：{terminal_label}**")
                _show_image(result)
            else:
                st.info("工作流正在处理，请稍候刷新。")
    if all(
        getattr(comparison, arm).status in TERMINAL_STATUSES
        for arm in ("baseline", "corpus")
    ):
        if st.button("开始新实验", type="primary", width="stretch"):
            _reset_experiment()
            st.rerun()


def _terminal_page(result: RunResult, *, scope: str) -> None:
    labels = {
        "completed": "生成完成",
        "rejected": "本次图像生成已取消",
        "failed": "本次生成失败" if scope == "design" else "本次实验失败",
    }
    st.subheader(labels.get(result.status, "本次运行已结束"))
    _show_image(result)
    button_label = "创建新设计" if scope == "design" else "开始新实验"
    if st.button(button_label, type="primary", width="stretch"):
        (_reset_design if scope == "design" else _reset_experiment)()
        st.rerun()


def render_design_page() -> None:
    _brand()
    if st.session_state.get("design_ui_error"):
        st.error(f"操作失败：{st.session_state.design_ui_error}")
    if st.session_state.get("design_ui_failed"):
        if st.button("重新开始", type="primary", width="stretch"):
            _reset_design()
            st.rerun()
        return

    result: RunResult | None = st.session_state.get("design_result")
    if result is None:
        _start_design()
    elif result.status == "awaiting_approval":
        _generation_preview_page(result, scope="design")
    elif result.status in TERMINAL_STATUSES:
        _terminal_page(result, scope="design")
    else:
        st.info("工作流正在处理，请稍候刷新。")


def render_experiment_page() -> None:
    _brand()
    if st.session_state.get("experiment_ui_error"):
        st.error(f"操作失败：{st.session_state.experiment_ui_error}")
    if st.session_state.get("experiment_ui_failed"):
        if st.button("重新开始", type="primary", width="stretch"):
            _reset_experiment()
            st.rerun()
        return

    comparison: ComparisonResult | None = st.session_state.get("comparison_result")
    result: RunResult | None = st.session_state.get("experiment_result")
    if comparison is not None:
        _comparison_page(comparison)
    elif result is None:
        _start_experiment()
    elif result.status == "awaiting_approval":
        _generation_preview_page(result, scope="experiment")
    elif result.status in TERMINAL_STATUSES:
        _terminal_page(result, scope="experiment")
    else:
        st.info("工作流正在处理，请稍候刷新。")


def main() -> None:
    st.set_page_config(page_title="Corpus Atelier", page_icon="◫", layout="centered")
    page = st.navigation(
        [
            st.Page(
                "app_pages/create_design.py",
                title="创建设计",
                icon=":material/palette:",
                default=True,
            ),
            st.Page(
                "app_pages/corpus_experiment.py",
                title="语料对比实验",
                icon=":material/science:",
            ),
        ],
        position="top",
    )
    page.run()


if __name__ == "__main__":
    main()
