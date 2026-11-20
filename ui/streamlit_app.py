"""Streamlit 最小演示前端。

架构硬约束：只通过 HTTP 调 FastAPI，不 import 任何 app.* 代码。
目的是演示「前端 → API → Agent」整条链路，而不是把后端当函数库直接调用。
"""

from __future__ import annotations

import os
import time
import uuid

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")

# 前端自己维护一份展示用映射。只为三个枚举多做一次映射，就省掉了对后端包的依赖。
INTENT_LABELS = {
    "policy_qa": "政策问答",
    "ticket_op": "工单处理",
    "handoff": "转人工",
}


def ask(message: str, session_id: str) -> dict:
    """走 HTTP 调用后端，返回解析后的 JSON。"""
    resp = requests.post(
        f"{API_BASE}/chat",
        json={"message": message, "session_id": session_id},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def render_answer(data: dict, elapsed_ms: float) -> None:
    intent = data.get("intent", "")
    if intent == "handoff":
        st.info("已转人工：这个问题不自动作答。")
    if data.get("fallback"):
        st.warning(f"本次发生了降级：{data.get('fallback_reason') or '未知原因'}")

    st.markdown(data.get("answer", ""))

    steps = data.get("steps") or []
    if steps:
        with st.status(f"执行过程（{len(steps)} 步）", state="complete", expanded=True):
            for i, step in enumerate(steps, 1):
                icon = "✓" if step.get("ok", True) else "✗"
                st.write(f"{icon} **{i}. {step.get('action', '')}** — {step.get('detail', '')}")

    cols = st.columns(4)
    cols[0].metric("意图", INTENT_LABELS.get(intent, intent))
    cols[1].metric("置信度", f"{data.get('confidence', 0):.2f}")
    cols[2].metric("耗时", f"{elapsed_ms:.0f} ms")
    cols[3].metric("服务方", data.get("served_by") or "-")
    st.caption(f"request_id：{data.get('request_id') or '-'}")

    citations = data.get("citations") or []
    if citations:
        st.subheader("引用来源")
        for i, cite in enumerate(citations, 1):
            title = f"[{i}] {cite['policy_id']} · {cite['section']}"
            with st.expander(title):
                st.write(cite["snippet"])
                st.caption(f"{cite['source_file']} · 相似度 {cite['score']}")


st.set_page_config(page_title="HelpDesk Agent", page_icon="🎫", layout="centered")
st.title("企业内部服务台 Agent")
st.caption("政策问答 · 工单操作 · 转人工")

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]

with st.sidebar:
    st.subheader("后端状态")
    if st.button("检查健康"):
        try:
            health = requests.get(f"{API_BASE}/health", timeout=5).json()
            st.success(f"{health.get('status')} · {health.get('model')}")
        except Exception as exc:  # 侧栏只做提示，不中断主流程
            st.error(f"健康检查失败：{type(exc).__name__}")
    st.caption(f"API：{API_BASE}")
    st.caption(f"会话：{st.session_state.session_id}")

    with st.expander("已知限制"):
        st.markdown(
            "- 多轮记忆为进程内存储：3 轮窗口、30 分钟过期，重启后清空\n"
            "- 提交人固定为 E005（陈磊），真实系统应取自登录态\n"
            "- 政策库只有 4 份文档，覆盖范围有限\n"
            "- `deepseek-flash` 单次延迟约 2–4 秒"
        )

with st.form("ask"):
    message = st.text_input("你想问什么？", placeholder="例如：出差住宿能报多少钱？")
    submitted = st.form_submit_button("发送")

if submitted:
    text = (message or "").strip()
    if not text:
        st.warning("先输入一个问题。")
    else:
        started = time.perf_counter()
        with st.spinner("正在理解问题、检索资料…"):
            try:
                data = ask(text, st.session_state.session_id)
            except requests.ConnectionError:
                st.error("连不上后端。请先在另一个终端运行：uvicorn app.main:app --port 8000")
                st.stop()
            except requests.HTTPError as exc:
                st.error(f"后端返回错误：HTTP {exc.response.status_code}")
                st.stop()
            except ValueError:
                st.error("后端返回的不是合法 JSON。")
                st.stop()
        render_answer(data, (time.perf_counter() - started) * 1000)
