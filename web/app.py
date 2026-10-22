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
Pixelle-Video Web UI - Main Entry Point

This is the entry point for the Streamlit multi-page application.
Uses st.navigation to define pages and set the default page to Home.
"""

import sys
from pathlib import Path

# Add project root to sys.path for module imports
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

# Setup page config (must be first Streamlit command)
st.set_page_config(
    page_title="镜织 FrameWeave - AI 视频创作工作台",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="auto",
)


def main():
    """Main entry point with navigation"""
    from web.utils.workspace_route import is_workspace_embedded, notify_workspace_ready

    if is_workspace_embedded():
        # 内嵌入口保持查询参数与 URL 不变，避免多页跳转清掉 tool/语言参数。
        import runpy

        runpy.run_path(str(_script_dir / "pages" / "1_🎬_Home.py"), run_name="__main__")
        notify_workspace_ready()
        return

    # Define pages using st.Page
    home_page = st.Page(
        "pages/1_🎬_Home.py",
        title="Home",
        icon="🎬",
        default=True
    )
    
    history_page = st.Page(
        "pages/2_📚_History.py",
        title="History",
        icon="📚"
    )
    
    # Set up navigation and run
    # 导航由公共侧栏统一呈现，避免原生列表与工作台导航重复。
    pg = st.navigation([home_page, history_page], position="hidden")
    pg.run()
    # 主页面控件全部渲染后才打开设置：保存引发的 rerun 不会清理尚未渲染的创作草稿。
    from web.components.settings_dialog import render_pending_settings_dialog
    render_pending_settings_dialog()


if __name__ == "__main__":
    main()
