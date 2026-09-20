"""A small Streamlit interface for the review-gated design workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from corpus_atelier.application import CorpusAtelierApplication
from corpus_atelier.state import DesignJob, HumanDecision, RevisionDecision, RunResult


ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "工作坊海报": ("rhetoric-poster", ROOT / "experiments/cases/poster-01/brief.json"),
    "文章封面": ("art-article-cover", ROOT / "experiments/cases/article-cover-01/brief.json"),
}
TERMINAL_STATUSES = {"completed", "rejected", "discarded", "failed"}


def load_case(label: str) -> dict[str, Any]:
    """Load one bundled example brief."""
    return json.loads(CASES[label][1].read_text(encoding="utf-8"))


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
    """Return only concise, user-facing review findings."""
    if "regressions" in review:
        points = list(review.get("requested_change_evidence", []))
        points.extend(review.get("regressions", []))
        return points
    points = list(review.get("observations", []))
    points.extend(review.get("priority_actions", []))
    return points


def _reset() -> None:
    for key in ("atelier_app", "result", "ui_error", "ui_failed", "revision_text"):
        st.session_state.pop(key, None)


def _change_case() -> None:
    st.session_state.brief_editor = json.dumps(
        load_case(st.session_state.case_label), ensure_ascii=False, indent=2,
    )


def _resume(decision: HumanDecision | RevisionDecision, message: str) -> None:
    app: CorpusAtelierApplication = st.session_state.atelier_app
    result: RunResult = st.session_state.result
    st.session_state.ui_error = ""
    try:
        with st.spinner(message):
            st.session_state.result = app.resume(result.run_id, decision)
    except Exception as exc:  # Streamlit must turn provider errors into a recoverable page.
        st.session_state.ui_error = str(exc)
        st.session_state.ui_failed = True
    st.rerun()


def _show_review(result: RunResult) -> None:
    review = read_json_artifact(result, "review")
    if not review:
        return
    verdict = {"accept": "建议接受", "revise": "建议修改", "reject": "建议放弃"}.get(
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
    source = result.artifacts.get("revision_source")
    if source and image:
        before, after = st.columns(2)
        before.image(source, caption="修改前", width="stretch")
        after.image(image, caption="修改后", width="stretch")
    elif image:
        st.image(image, caption="当前版本", width="stretch")


def _start_page() -> None:
    st.subheader("开始一个设计")
    if "case_label" not in st.session_state:
        st.session_state.case_label = next(iter(CASES))
    if "brief_editor" not in st.session_state:
        _change_case()

    st.selectbox(
        "选择示例", list(CASES), key="case_label", on_change=_change_case,
    )
    with st.expander("编辑内容", expanded=False):
        st.text_area("Brief（JSON）", height=280, key="brief_editor")

    if not st.button("生成设计方案", type="primary", width="stretch"):
        return
    try:
        brief = parse_brief(st.session_state.brief_editor)
        profile = CASES[st.session_state.case_label][0]
        load_dotenv(ROOT / ".env")
        app = CorpusAtelierApplication(runs_root=ROOT / "experiments/runs")
        with st.spinner("正在准备设计方案…"):
            result = app.start(DesignJob(
                profile=profile,
                brief=brief,
                snapshot=ROOT / "experiments/atlas-snapshot",
            ))
        st.session_state.atelier_app = app
        st.session_state.result = result
        st.session_state.ui_error = ""
        st.session_state.ui_failed = False
        st.rerun()
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Brief 内容有误：{exc}")
    except Exception as exc:
        st.error(f"无法生成设计方案：{exc}")


def _approval_page(result: RunResult) -> None:
    proposal = read_json_artifact(result, "proposal")
    st.subheader("设计方案")
    st.write(proposal.get("chosen_direction", "设计方案已准备完成。"))
    rationale = proposal.get("design_rationale")
    if rationale:
        st.caption(rationale)
    approve, reject = st.columns(2)
    if approve.button("批准并生成", type="primary", width="stretch"):
        _resume(HumanDecision(True, reviewer="streamlit-user"), "正在生成并审查图片…")
    if reject.button("放弃", width="stretch"):
        _resume(HumanDecision(False, reviewer="streamlit-user"), "正在结束本次设计…")


def _revision_page(result: RunResult) -> None:
    st.subheader("查看设计")
    _show_image(result)
    _show_review(result)

    accept, discard = st.columns(2)
    if accept.button("接受当前版本", type="primary", width="stretch"):
        _resume(RevisionDecision("accept", reviewer="streamlit-user"), "正在保存决定…")
    if discard.button("放弃", width="stretch"):
        _resume(RevisionDecision("discard", reviewer="streamlit-user"), "正在结束本次设计…")

    st.divider()
    st.text_area(
        "想修改什么？", key="revision_text",
        placeholder="例如：放大主标题，并移除左下角的手写元素。",
    )
    if st.button("准备修改", width="stretch"):
        instruction = st.session_state.revision_text.strip()
        if not instruction:
            st.warning("请先写下具体的修改要求。")
        else:
            _resume(
                RevisionDecision("revise", instruction=instruction, reviewer="streamlit-user"),
                "正在整理修改方案…",
            )


def _revision_approval_page(result: RunResult) -> None:
    st.subheader("确认修改")
    _show_image(result)
    plan = read_json_artifact(result, "revision_plan")
    st.write("将进行以下修改：")
    for change in plan.get("requested_changes", []):
        st.write(f"- {change}")
    approve, cancel = st.columns(2)
    if approve.button("确认修改", type="primary", width="stretch"):
        st.session_state.revision_text = ""
        _resume(HumanDecision(True, reviewer="streamlit-user"), "正在修改并比较图片…")
    if cancel.button("取消修改", width="stretch"):
        _resume(HumanDecision(False, reviewer="streamlit-user"), "正在返回当前版本…")


def _terminal_page(result: RunResult) -> None:
    labels = {
        "completed": "当前设计已接受",
        "rejected": "已放弃生成",
        "discarded": "当前设计已放弃",
        "failed": "本次运行失败",
    }
    st.subheader(labels.get(result.status, "本次运行已结束"))
    _show_image(result)
    if st.button("开始新设计", type="primary", width="stretch"):
        _reset()
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Corpus Atelier", page_icon="◫", layout="centered")
    st.title("Corpus Atelier")
    st.caption("从设计方案到图片修改的简洁工作台")

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
    elif result.status == "awaiting_revision":
        _revision_page(result)
    elif result.status == "awaiting_revision_approval":
        _revision_approval_page(result)
    elif result.status in TERMINAL_STATUSES:
        _terminal_page(result)
    else:
        st.info("工作流正在处理，请稍候刷新。")


if __name__ == "__main__":
    main()
