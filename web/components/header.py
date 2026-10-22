# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Header components for web UI
"""

import streamlit as st

from web.i18n import set_language
from web.components.studio import apply_studio_theme, render_studio_sidebar, studio_text
from web.components.settings_dialog import render_settings_launcher


def render_header():
    """在各页面复用主题、导航与语言选择，不触发任何生成任务。"""
    apply_studio_theme()
    if st.query_params.get("frameweave") == "1":
        # FrameWeave 外层已提供品牌、主导航和语言入口，仅去掉重复的视觉外壳。
        from web.utils.workspace_route import apply_workspace_layout

        apply_workspace_layout()
        return
    render_studio_sidebar()
    with st.container(key="studio-topbar"):
        col1, settings_col, language_col = st.columns([4, 1, 1.6])
        with col1:
            st.html(f'<div class="studio-topbar-title"><strong class="studio-wordmark">Pixelle <em>{studio_text("创作工作台", "Studio")}</em></strong><span>{studio_text("创作空间", "YOUR WORKSPACE")}</span></div>')
        with settings_col:
            render_settings_launcher()
        with language_col:
            render_language_selector()


def render_language_selector():
    """右上角并列显示中文、英文，两种语言均可一键切换。"""
    # 语言名称始终使用自身语言，英文界面也能直接识别“中文”入口。
    languages = {"zh_CN": "中文", "en_US": "English"}
    current_lang = st.session_state.get("language", "zh_CN")
    if current_lang not in languages:
        current_lang = "zh_CN"
    
    def update_language():
        # 回调先于页面重绘执行，避免中途 rerun 清理尚未呈现的草稿控件。
        # 分段控件允许再次点击取消选择；此时恢复当前语言，始终有一个选中项。
        selected_code = st.session_state.studio_language or st.session_state.get("language", "zh_CN")
        st.session_state.studio_language = selected_code
        st.session_state.language = selected_code
        set_language(selected_code)

    st.segmented_control(
        "界面语言 / Language",
        options=list(languages),
        default=current_lang,
        format_func=lambda code: languages[code],
        key="studio_language",
        on_change=update_language,
        label_visibility="collapsed",
        width="stretch",
    )

