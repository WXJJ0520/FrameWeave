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

"""数字人口播配音：通过 Edge TTS 在线接口合成，保留音色、语速与试听。"""

import os

import streamlit as st
from loguru import logger

from pixelle_video.config import config_manager
from web.i18n import get_language, tr
from web.utils.async_helpers import run_async


def render_style_config(pixelle_video):
    """渲染在线语音参数，旧会话中的工作流模式不再参与请求。"""
    zh = get_language() == "zh_CN"
    # local 是现有 Edge TTS 适配器的内部名称，不代表离线语音模型。
    st.session_state["digital_tts_inference_mode"] = "local"
    with st.container(border=True):
        st.markdown(f"**{tr('section.tts')}**")
        st.caption(
            "Edge TTS 在线语音接口 · 需要联网，无需 API 密钥。"
            if zh else "Edge TTS online speech API · Internet access required; no API key needed."
        )
        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(
                "选择音色和语速后可先试听，再用于数字人口播配音。该接口由在线服务提供，网络或服务限制可能导致合成失败。"
                if zh else "Choose a voice and speed, then preview before creating narration. Synthesis uses an online service and may be affected by connectivity or service restrictions."
            )

        from pixelle_video.tts_voices import EDGE_TTS_VOICES, get_voice_display_name

        # 使用已经载入的配音偏好，不读取旧工作流选项，也不改写用户配置文件。
        local_config = config_manager.config.comfyui.tts.local
        voice_ids = [voice["id"] for voice in EDGE_TTS_VOICES]
        voice_options = [
            get_voice_display_name(voice_id, tr, get_language())
            for voice_id in voice_ids
        ]
        default_voice_index = (
            voice_ids.index(local_config.voice) if local_config.voice in voice_ids else 0
        )
        voice_col, speed_col = st.columns([1, 1])
        with voice_col:
            selected_voice_display = st.selectbox(
                tr("tts.voice_selector"), voice_options, index=default_voice_index,
                key="digital_tts_local_voice",
            )
            selected_voice = voice_ids[voice_options.index(selected_voice_display)]
        with speed_col:
            tts_speed = st.slider(
                tr("tts.speed"), min_value=0.5, max_value=2.0,
                value=local_config.speed, step=0.1, format="%.1fx",
                key="digital_tts_local_speed",
            )
            st.caption(tr("tts.speed_label", speed=f"{tts_speed:.1f}"))

        # 仅点击试听时请求在线语音；页面初次渲染不会产生网络调用。
        with st.expander(tr("tts.preview_title"), expanded=False):
            preview_text = st.text_input(
                tr("tts.preview_text"),
                value="大家好，这是一段测试语音。" if zh else "Hello, this is a voice preview.",
                placeholder=tr("tts.preview_text_placeholder"),
                key="digital_tts_preview_text",
            )
            if st.button(
                tr("tts.preview_button"), key="gidital_preview_tts", use_container_width=True,
            ):
                with st.spinner(tr("tts.previewing")):
                    try:
                        audio_path = run_async(pixelle_video.tts(
                            text=preview_text, inference_mode="local",
                            voice=selected_voice, speed=tts_speed,
                        ))
                        if audio_path and os.path.exists(audio_path):
                            st.success(tr("tts.preview_success"))
                            st.audio(audio_path, format="audio/mp3")
                        elif isinstance(audio_path, str) and audio_path.startswith(("https://", "http://")):
                            st.success(tr("tts.preview_success"))
                            st.audio(audio_path)
                        else:
                            st.error("未取得试听音频，请稍后重试。" if zh else "No preview audio was returned. Please try again later.")
                    except Exception as error:
                        # 在线服务异常可能携带令牌 URL，界面和日志仅记录固定提示及类型。
                        st.error(
                            "在线语音试听失败，请检查网络连接后重试。"
                            if zh else "Online voice preview failed. Check your connection and try again."
                        )
                        logger.warning("Edge TTS preview failed: {}", type(error).__name__)

    return {
        "tts_inference_mode": "local",
        "tts_voice": selected_voice,
        "tts_speed": tts_speed,
        # 保留原返回字段兼容已有生成调用，但不再传入工作流或参考音频。
        "tts_workflow": None,
        "ref_audio": None,
    }
