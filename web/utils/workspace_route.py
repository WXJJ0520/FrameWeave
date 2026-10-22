"""FrameWeave 工作台入口：复用现有创作流程，不复制配置或生成实现。"""

import json
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

# URL 使用稳定的产品功能名称；右侧对应项目里已经注册的真实流程。
WORKSPACE_PIPELINES = {
    "standard": "quick_create",
    "asset_based": "custom_media",
    "digital_human": "digital_human",
    "i2v": "image_to_video",
    "action_transfer": "action_transfer",
}
WORKSPACE_TOOLS = frozenset((*WORKSPACE_PIPELINES, "settings", "history"))


def is_workspace_embedded() -> bool:
    """仅显式工作台参数启用内嵌布局，独立访问仍保留原来的五个标签页。"""
    return st.query_params.get("frameweave") == "1"


def get_workspace_tool() -> str:
    """拒绝任意模块名或路径，未知工具安全回到真实快速创作流程。"""
    tool = st.query_params.get("tool", "standard")
    return tool if tool in WORKSPACE_TOOLS else "standard"


def apply_workspace_language() -> None:
    """在控件初始化之前同步父工作台语言，白名单之外不覆盖会话选择。"""
    if not is_workspace_embedded():
        return
    language = st.query_params.get("language")
    if language in {"zh_CN", "en_US"}:
        st.session_state.language = language
        from web.i18n import set_language

        set_language(language)


def apply_workspace_layout() -> None:
    """只为工作台载入浅色表单，不改变独立页面或控件的功能与状态。"""
    # 固定资产路径与 UTF-8 编码避免受运行目录、中文系统默认编码影响。
    stylesheet = Path(__file__).resolve().parents[1] / "assets" / "workspace.css"
    st.html(f"<style>{stylesheet.read_text(encoding='utf-8')}</style>")


def render_workspace_pipeline(pixelle_video) -> None:
    """分派到原有 renderer；不创建替代页面，也不更改其输入键与生成行为。"""
    from web.pipelines import get_pipeline_ui

    pipeline_name = WORKSPACE_PIPELINES.get(get_workspace_tool())
    pipeline = get_pipeline_ui(pipeline_name) if pipeline_name else None
    if pipeline is None:
        st.error("该创作流程暂时不可用，请刷新后重试。 / This workflow is unavailable.")
        return
    # 外层工作台已有当前功能说明，避免内嵌表单再重复一行相同说明。
    pipeline.render(pixelle_video)


def render_workspace_settings() -> None:
    """直接呈现完整系统配置，沿用原表单的保存、校验和连接测试逻辑。"""
    from web.components.settings import render_advanced_settings
    from web.i18n import get_language

    zh = get_language() == "zh_CN"
    feedback = st.session_state.pop("_frameweave_settings_saved", None)
    if feedback:
        st.success(feedback)
    st.caption(
        "配置你实际使用的服务，点击页面底部的保存配置后生效。"
        if zh else "Configure the services you use, then save at the bottom to apply."
    )

    def on_saved():
        # 只有原组件保存成功后才执行回调；不会自动提交连接测试或生成任务。
        st.session_state["_frameweave_settings_saved"] = (
            "配置已保存。" if zh else "Settings saved."
        )
        st.rerun()

    render_advanced_settings(on_saved=on_saved)


def parent_origin(value: str) -> str | None:
    """就绪通知仅允许发送给本机工作台，禁止任意站点或含认证信息的地址。"""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            return None
        # 读取 port 同时校验端口格式，避免把错误地址拼进脚本。
        port = parsed.port
        host = f"[{parsed.hostname}]" if parsed.hostname == "::1" else parsed.hostname
        return f"{parsed.scheme}://{host}" + (f":{port}" if port is not None else "")
    except (TypeError, ValueError):
        return None


def notify_workspace_ready() -> None:
    """仅发送工具名与布局高度，表单展开时同步高度以避免两层滚动。"""
    if not is_workspace_embedded():
        return
    origin = parent_origin(st.query_params.get("parent_origin", "http://127.0.0.1:8765"))
    if origin is None:
        return
    import streamlit.components.v1 as components

    payload = json.dumps({
        "type": "frameweave:tool-ready",
        "tool": get_workspace_tool(),
        "navigation": st.session_state.get("_creation_flow_navigation", 0),
    })
    target = json.dumps(origin)
    # 观察 Streamlit 内容块的自然高度，不测量视口高度，避免父子 iframe 互相撑高。
    script = """<script>
        const payload = __PAYLOAD__;
        const target = __TARGET__;
        const host = window.parent;
        const send = value => host.parent.postMessage(value, target);
        send(payload);
        let lastHeight = 0;
        let pending = 0;
        const content = host.document.querySelector('[data-testid="stMainBlockContainer"]');
        const measure = () => {
            cancelAnimationFrame(pending);
            pending = requestAnimationFrame(() => {
                if (!content || content.getBoundingClientRect().width === 0) return;
                const height = Math.ceil(content.getBoundingClientRect().height + 12);
                if (height >= 200 && height <= 20000 && Math.abs(height - lastHeight) > 2) {
                    lastHeight = height;
                    send({type: 'frameweave:tool-size', tool: payload.tool, height});
                }
                // 等新步骤的自然高度算完再通知父页，避免滚动落在上一页的底部。
                if (payload.navigation > 0) {
                    send({type: 'frameweave:tool-step', tool: payload.tool,
                          navigation: payload.navigation});
                }
            });
        };
        const observer = new ResizeObserver(measure);
        if (content) observer.observe(content);
        measure();
        window.addEventListener('unload', () => {
            observer.disconnect();
            cancelAnimationFrame(pending);
        });
    </script>"""
    components.html(script.replace("__PAYLOAD__", payload).replace("__TARGET__", target), height=0)
