"""五个创作页共用的步骤布局；输入始终挂载，避免返回上一步时丢失草稿。"""

import re
from contextlib import contextmanager
from html import escape
from pathlib import Path

import streamlit as st

from web.i18n import get_language


class CreationFlow:
    """只负责导航与布局，不自动校验、提交或调用任何生成服务。"""

    def __init__(self, key: str, steps: list[tuple[str, str]]):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or not steps:
            raise ValueError("CreationFlow requires a stable key and at least one step")
        self.key = key
        self.steps = steps
        self.state_key = f"creation_flow_{key}_step"
        self.zh = get_language() == "zh_CN"
        saved = st.session_state.get(self.state_key, 0)
        # 兼容旧会话与步骤数量变化，防止越界后出现空白页面。
        self.current = min(max(saved, 0), len(steps) - 1) if type(saved) is int else 0
        st.session_state[self.state_key] = self.current

    def is_active(self, index: int) -> bool:
        """最终输出区可按此条件渲染，输入区不要条件卸载。"""
        return self.current == index

    def render_header(self) -> None:
        stylesheet = Path(__file__).resolve().parents[1] / "assets" / "creation_flow.css"
        # 隐藏整个容器及其可聚焦元素，但保留 Streamlit widget 的稳定身份。
        hidden = ",".join(
            f".st-key-creation-flow-{self.key}-panel-{i}"
            for i in range(len(self.steps)) if not self.is_active(i)
        )
        visibility = f"{hidden} {{ display: none !important; }}" if hidden else ""
        st.html(f"<style>{stylesheet.read_text(encoding='utf-8')}\n{visibility}</style>")
        items = []
        for i, (title, _) in enumerate(self.steps):
            state = "current" if self.is_active(i) else ("visited" if i < self.current else "pending")
            aria = ' aria-current="step"' if self.is_active(i) else ""
            items.append(
                f'<li class="creation-step {state}"{aria}>'
                f'<span class="creation-step-number">{i + 1:02}</span>'
                f'<span class="creation-step-label">{escape(title)}</span></li>'
            )
        label = "创作步骤" if self.zh else "Creation steps"
        st.html(
            f'<nav class="creation-flow-header" aria-label="{label}">'
            f'<ol>{"".join(items)}</ol></nav>'
        )

    @contextmanager
    def step(self, index: int):
        """每次依序调用全部步骤，不能用 if active 包住含上传框的输入步骤。"""
        title, description = self.steps[index]
        with st.container(key=f"creation-flow-{self.key}-panel-{index}"):
            st.html(
                '<div class="creation-panel-heading">'
                f'<h2>{escape(title)}</h2><p>{escape(description)}</p></div>'
            )
            yield

    def _move(self, index: int) -> None:
        # 回调先更新步骤，再完整重绘；不会清空表单或执行生成按钮。
        st.session_state[self.state_key] = min(max(index, 0), len(self.steps) - 1)
        # 只传递递增的导航序号，让嵌入工作台在换步时回到表单顶部，不传表单内容。
        st.session_state["_creation_flow_navigation"] = (
            st.session_state.get("_creation_flow_navigation", 0) + 1
        )

    def render_navigation(self) -> None:
        """五个页面使用相同的底部位置和导航按钮，最终生成仍由原组件负责。"""
        with st.container(key=f"creation-flow-{self.key}-navigation"):
            back, progress, forward = st.columns([1, 1.3, 1], gap="small")
            with back:
                st.button(
                    "上一步" if self.zh else "Previous",
                    key=f"creation_flow_{self.key}_previous",
                    disabled=self.current == 0,
                    on_click=self._move,
                    args=(self.current - 1,),
                    use_container_width=True,
                )
            with progress:
                status = (
                    f"第 {self.current + 1} 步 / 共 {len(self.steps)} 步"
                    if self.zh else f"Step {self.current + 1} of {len(self.steps)}"
                )
                st.html(f'<div class="creation-flow-progress" role="status">{status}</div>')
            if self.current < len(self.steps) - 1:
                with forward:
                    st.button(
                        "下一步" if self.zh else "Next",
                        key=f"creation_flow_{self.key}_next",
                        type="primary",
                        on_click=self._move,
                        args=(self.current + 1,),
                        use_container_width=True,
                    )
