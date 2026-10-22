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
Standard Pipeline UI

快速创作工作台：脚本、画面与配音、预览与生成三个连续步骤。
"""

from typing import Any

import streamlit as st

# Import components
from web.components.content_input import render_bgm_section, render_content_input
from web.components.creation_flow import CreationFlow
from web.components.output_preview import render_output_preview
from web.components.style_config import render_style_config
from web.i18n import get_language, tr
from web.pipelines.base import PipelineUI, register_pipeline_ui


class StandardPipelineUI(PipelineUI):
    """
    UI for the Standard Video Generation Pipeline.
    保留完整业务参数，与其余创作页共用连续步骤布局。
    """
    name = "quick_create"
    icon = "⚡"
    
    @property
    def display_name(self):
        return tr("pipeline.quick_create.name")
    
    @property
    def description(self):
        return tr("pipeline.quick_create.description")
    
    def render(self, pixelle_video: Any):
        zh = get_language() == "zh_CN"
        flow = CreationFlow(self.name, [
            ("视频脚本", "输入创作想法或完整文案，也可以一次准备多条内容。"),
            ("画面与配音", "选择画面模板、API 模型、音色和背景音乐。"),
            ("预览与生成", "确认设置后生成视频，完成后可预览和下载。"),
        ] if zh else [
            ("Script", "Start with an idea or a complete script. Batch creation is available."),
            ("Visuals & voice", "Choose a template, API model, voice and background music."),
            ("Preview & generate", "Review your settings, then generate, preview and download."),
        ])
        flow.render_header()
        # 所有输入步骤保持挂载；只改变可见性，上传文件与脚本不会被步骤切换清空。
        with flow.step(0):
            content_params = render_content_input()
        with flow.step(1):
            style_params = render_style_config(pixelle_video)
            with st.expander("背景音乐" if zh else "Background music", expanded=False):
                bgm_params = render_bgm_section()
        with flow.step(2):
            if flow.is_active(2):
                video_params = {
                    "pipeline": self.name,
                    **content_params,
                    **bgm_params,
                    **style_params,
                }
                render_output_preview(pixelle_video, video_params)
        flow.render_navigation()


# Register self
register_pipeline_ui(StandardPipelineUI)
