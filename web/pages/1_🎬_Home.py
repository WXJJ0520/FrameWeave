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
Home Page - Main video generation interface
"""

import sys
from pathlib import Path

# Add project root to sys.path
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

# Import state management
from web.state.session import init_session_state, init_i18n, get_pixelle_video

# Import components
from web.components.header import render_header
from web.components.faq import render_faq_sidebar
from web.components.studio import render_studio_intro

# Page config
st.set_page_config(
    page_title="创作 - 镜织 FrameWeave",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="auto",
)


def main():
    """Main UI entry point"""
    from web.utils.workspace_route import (
        apply_workspace_language,
        get_workspace_tool,
        is_workspace_embedded,
        render_workspace_pipeline,
        render_workspace_settings,
    )

    # Initialize session state and i18n
    init_session_state()
    apply_workspace_language()
    init_i18n()
    
    # Render header (title + language selector)
    render_header()

    if is_workspace_embedded():
        tool = get_workspace_tool()
        if tool == "settings":
            # 配置页面独立于生成核心，未配置 ComfyUI 也必须能正常打开与保存。
            render_workspace_settings()
        elif tool == "history":
            import runpy

            history = runpy.run_path(str(_script_dir / "2_📚_History.py"))
            history["main"]()
        else:
            render_workspace_pipeline(get_pixelle_video())
        return

    render_studio_intro()
    
    # Render FAQ in sidebar
    render_faq_sidebar()
    
    # Initialize Pixelle-Video
    pixelle_video = get_pixelle_video()
    
    # 设置已移至公共页头的独立弹窗，主区保持脚本与预览的连续布局。
    
    # ========================================================================
    # Pipeline Selection & Delegation
    # ========================================================================
    from web.pipelines import get_all_pipeline_uis
    
    # Get all registered pipelines
    pipelines = get_all_pipeline_uis()
    
    # Use Tabs for pipeline selection
    # Note: st.tabs returns a list of containers, one for each tab
    tab_labels = [p.display_name for p in pipelines]
    tabs = st.tabs(tab_labels)
    
    # Render each pipeline in its corresponding tab
    for i, pipeline in enumerate(pipelines):
        with tabs[i]:
            # Show description if available
            # 快速创作已有顶部引导和编辑标签，其他流程保留自己的使用说明。
            if pipeline.description and pipeline.name != "quick_create":
                st.caption(pipeline.description)
            
            # Delegate rendering
            pipeline.render(pixelle_video)


if __name__ == "__main__":
    main()

