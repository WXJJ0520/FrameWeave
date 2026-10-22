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
Session state management for web UI
"""

import streamlit as st
from loguru import logger

from web.i18n import set_language
from web.utils.async_helpers import run_async


def init_session_state():
    """Initialize session state variables"""
    if "language" not in st.session_state:
        # 新会话以中文为主，不继承系统或其他会话最后选中的语言。
        st.session_state.language = "zh_CN"


def init_i18n():
    """Initialize internationalization"""
    # 保留本会话手动选择；只有尚未设置语言时才使用默认中文。
    if "language" not in st.session_state:
        st.session_state.language = "zh_CN"
    
    # Set current language
    set_language(st.session_state.language)


def get_pixelle_video():
    """
    Get initialized Pixelle-Video instance with proper caching and cleanup
    
    Uses st.session_state to cache the instance per user session.
    Recreates cached service snapshots when their configuration changes.
    ComfyKit remains lazily initialized for legacy CLI compatibility.
    """
    # Compute config hash for change detection
    import hashlib
    import json

    from pixelle_video.config import config_manager
    from pixelle_video.service import PixelleVideoCore
    config_dict = config_manager.config.to_dict()
    # VLM 和文本服务持有创建时配置快照；API 凭据或模型变更后必须重建。
    # comfyui 段仍保存既有音色等兼容配置，不能从变更检测中遗漏。
    service_config = {
        section: config_dict.get(section, {})
        for section in ("api_providers", "llm", "comfyui")
    }
    config_hash = hashlib.sha256(
        json.dumps(service_config, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    
    # Check if we need to create or recreate core instance
    need_recreate = False
    if 'pixelle_video' not in st.session_state:
        need_recreate = True
        logger.info("Creating new PixelleVideoCore instance (first time)")
    elif st.session_state.get('pixelle_video_config_hash') != config_hash:
        need_recreate = True
        logger.info("Configuration changed, recreating PixelleVideoCore instance")
        # Cleanup old instance
        old_core = st.session_state.pixelle_video
        try:
            run_async(old_core.cleanup())
        except Exception as e:
            logger.warning(f"Failed to cleanup old PixelleVideoCore: {e}")
    
    if need_recreate:
        # Create and initialize new instance
        pixelle_video = PixelleVideoCore()
        run_async(pixelle_video.initialize())
        
        # Cache in session state
        st.session_state.pixelle_video = pixelle_video
        st.session_state.pixelle_video_config_hash = config_hash
        logger.info("✅ PixelleVideoCore initialized and cached")
    else:
        pixelle_video = st.session_state.pixelle_video
        logger.debug("Reusing cached PixelleVideoCore instance")
    
    return pixelle_video

