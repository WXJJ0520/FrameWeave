"""按需打开的设置中心：草稿仅保留在本会话，明确保存后才写配置。"""

import streamlit as st

from web.i18n import get_language

_OPEN_KEY = "_studio_settings_open"
_RESTORE_KEY = "_studio_settings_restore"
_DRAFT_KEY = "_studio_settings_draft"
_FIELD_KEYS = {
    "llm_preset_select", "api_media_print_model_input", "api_media_local_proxy",
}
_FIELD_KEYS.update(
    f"api_media_{provider}_{field}"
    for provider in ("openai", "xai", "muse", "dashscope", "ark", "kling")
    for field in ("key", "base_url", "use_proxy", "access_key", "secret_key")
)
# 视觉模型列表与密钥一样保留为当前会话草稿，关闭弹窗不隐式保存。
_FIELD_KEYS.update(f"api_media_{provider}_vision_models" for provider in ("openai", "dashscope"))
# 目录来源及手工 ID 都属于表单草稿；已加载快照留在独立会话缓存中。
_FIELD_KEYS.add("llm_model_source")
_FIELD_KEYS.update(
    f"api_media_{provider}_{field}"
    for provider in ("llm", "openai", "dashscope", "xai", "muse", "ark", "kling")
    for field in ("catalog_mode", "manual_models")
)
_LLM_FIELD_PREFIXES = (
    "llm_api_key_input_", "llm_base_url_input_", "llm_model_select_", "llm_custom_model_input_",
)


def _copy(zh: str, en: str) -> str:
    return zh if get_language().startswith("zh") else en


def _capture_settings_draft():
    """只复制可编辑字段，排除按钮、连接结果和摘要盐；不记录或打印凭据。"""
    st.session_state[_DRAFT_KEY] = {
        key: st.session_state[key]
        for key in st.session_state
        if key in _FIELD_KEYS or key.startswith(_LLM_FIELD_PREFIXES)
    }


def _request_settings_open():
    """打开前标记恢复草稿，弹窗内部的后续交互不重复覆盖新输入。"""
    st.session_state[_OPEN_KEY] = True
    st.session_state[_RESTORE_KEY] = True


def _dismiss_settings():
    """原生关闭、Escape 与关闭按钮共用回调，关闭不会保存到配置文件。"""
    _capture_settings_draft()
    st.session_state[_OPEN_KEY] = False
    st.session_state[_RESTORE_KEY] = False


def _finish_settings_save():
    """成功保存后清理草稿并关闭，下一次打开读取最新配置。"""
    from pixelle_video.config import config_manager

    st.session_state.pop(_DRAFT_KEY, None)
    st.session_state[_OPEN_KEY] = False
    st.session_state[_RESTORE_KEY] = False
    st.session_state["_studio_settings_feedback"] = (
        _copy("配置已保存", "Settings saved")
        if config_manager.validate()
        else _copy("媒体 API 配置已保存；自动文案仍需补全文本模型。", "Media API settings saved. Complete the text model before generating scripts.")
    )
    # 在整个页面重绘后更新实际生成使用的配置，不执行任何生成或测试请求。
    st.rerun()


def render_settings_launcher():
    """公共页头只显示轻量入口，未打开时不加载密钥表单或测试接口。"""
    st.button(
        _copy("设置", "Settings"), icon=":material/tune:",
        key="studio_settings_open", on_click=_request_settings_open,
        use_container_width=True,
    )


def render_pending_settings_dialog():
    """保持弹窗重绘状态，原生关闭回调会先清除标记，避免关闭后又弹出。"""
    feedback = st.session_state.pop("_studio_settings_feedback", None)
    if feedback:
        st.toast(feedback)
    if not st.session_state.get(_OPEN_KEY):
        return

    @st.dialog(_copy("系统设置", "Settings"), width="large", on_dismiss=_dismiss_settings)
    def settings_panel():
        # 延迟导入使创作页正常打开时不渲染全部配置，也不触发外部查询。
        from web.components.settings import render_advanced_settings

        if st.session_state.pop(_RESTORE_KEY, False):
            for key, value in st.session_state.get(_DRAFT_KEY, {}).items():
                st.session_state[key] = value
        with st.container(key="studio-settings-panel"):
            st.caption(_copy(
                "按用途配置服务，只需填写你使用的提供商。关闭会保留本次草稿，点击保存后生效。",
                "Configure the services you use. Closing keeps your draft in this session; changes apply only after saving.",
            ))
            render_advanced_settings(on_saved=_finish_settings_save)
            # 只在正常渲染结束后同步，保存时的 rerun 不会把旧草稿写回来。
            _capture_settings_draft()
            if st.button(_copy("关闭设置", "Close settings"), key="studio_settings_close", on_click=_dismiss_settings):
                st.rerun()

    settings_panel()
