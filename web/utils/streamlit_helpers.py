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
Streamlit helper functions
"""

import streamlit as st

from web.i18n import tr
from pixelle_video.config import config_manager


def safe_rerun():
    """Safe rerun that works with both old and new Streamlit versions"""
    if hasattr(st, 'rerun'):
        st.rerun()
    else:
        st.experimental_rerun()


# ============================================================================
# SelfHost 工作流前置说明
# ============================================================================
# 在当前工作流下保留可随时查看的说明，避免页面重绘时原生弹窗阻断操作。

def check_and_warn_selfhost_workflow(workflow_path: str):
    """仅为本地工作流展示调试前置说明，不改变工作流选择或生成验证。"""
    if not workflow_path or not workflow_path.startswith("selfhost/"):
        return

    _render_selfhost_workflow_warning(workflow_path)


def _render_selfhost_workflow_warning(workflow_path: str):
    """复用完整中英文说明与当前地址、路径，以折叠内容替代浏览器弹窗。"""
    comfyui_config = config_manager.get_comfyui_config()
    comfyui_url = comfyui_config.get("comfyui_url", "http://localhost:8188")

    title = tr("selfhost.warning.title")
    message = tr(
        "selfhost.warning.message",
        comfyui_url=comfyui_url,
        workflow_path=f"workflows/{workflow_path}",
    )
    hint = tr("selfhost.warning.hint")

    # 保留独立运行、节点及模型检查、调试通过后返回项目等全部原有要求。
    with st.expander(title, expanded=False):
        st.markdown(message)
        st.warning(hint)

