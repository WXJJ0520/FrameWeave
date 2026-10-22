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
Asset-Based Pipeline UI

Implements the UI for generating videos from user-provided assets.
"""

import inspect
import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.models.progress import ProgressEvent
from web.components.content_input import render_bgm_section
from web.components.creation_flow import CreationFlow
from web.components.creation_uploads import persist_uploaded_files
from web.i18n import get_language, tr
from web.pipelines.api_workflows import (
    list_api_media_workflows,
    render_api_video_controls,
    workflow_select_help,
    workflow_source_label,
)
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.utils.async_helpers import run_async


class AssetBasedPipelineUI(PipelineUI):
    """
    UI for the Asset-Based Video Generation Pipeline.
    Generates videos from user-provided assets (images/videos).
    """
    name = "custom_media"
    icon = "🎨"
    
    @property
    def display_name(self):
        return tr("pipeline.custom_media.name")
    
    @property
    def description(self):
        return tr("pipeline.custom_media.description")
    
    def render(self, pixelle_video: Any):
        zh = get_language() == "zh_CN"
        flow = CreationFlow(self.name, [
            (
                "素材与想法" if zh else "Assets & idea",
                "上传图片或视频，补充标题和创作方向。" if zh
                else "Upload images or videos, then add a title and creative direction.",
            ),
            (
                "画面与配音" if zh else "Visuals & voice",
                "选择素材分析模型，设置画面、配音和背景音乐。" if zh
                else "Choose asset analysis, visuals, voice and background music.",
            ),
            (
                "预览与生成" if zh else "Preview & generate",
                "确认素材和参数后生成视频，也可以返回调整。" if zh
                else "Review your assets and settings, then generate or go back to make changes.",
            ),
        ])
        flow.render_header()

        # 所有输入步骤持续挂载；仅用公共布局隐藏非当前步骤，避免上传和草稿丢失。
        with flow.step(0):
            asset_params = self._render_asset_input()

        with flow.step(1):
            config_params = self._render_video_config(pixelle_video, asset_params)
            bgm_params = render_bgm_section(key_prefix="asset_")

        # 保持原来的参数覆盖顺序，导航本身不调用生成服务。
        video_params = {
            "pipeline": self.name,
            **asset_params,
            **bgm_params,
            **config_params,
        }
        with flow.step(2):
            if flow.is_active(2):
                self._render_output_preview(pixelle_video, video_params)
        flow.render_navigation()
    
    def _render_asset_input(self) -> dict:
        """Render asset upload section"""
        with st.container(border=True):
            st.markdown(f"**{tr('asset_based.section.assets')}**")
            
            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("asset_based.assets.what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("asset_based.assets.how"))
            
            # 长素材可超过旧版默认 200 MB；按当前 Streamlit 能力启用单文件 1 GB，旧版仍可运行。
            supports_upload_limit = "max_upload_size" in inspect.signature(st.file_uploader).parameters
            upload_options = {"max_upload_size": 1024} if supports_upload_limit else {}
            uploaded_files = st.file_uploader(
                tr("asset_based.assets.upload"),
                type=["jpg", "jpeg", "png", "gif", "webp", "mp4", "mov", "avi", "mkv", "webm"],
                accept_multiple_files=True,
                help=tr("asset_based.assets.upload_help"),
                key="asset_files",
                **upload_options,
            )
            if supports_upload_limit:
                st.caption(
                    "视频单文件上传上限 1 GB；图片需不超过 32 MB、6400 万像素。视频分析只发送抽取的画面。"
                    if get_language() == "zh_CN" else "Videos: up to 1 GB per file. Images: up to 32 MB / 64 megapixels. Video analysis sends sampled frames only."
                )
            
            # 步骤切换会触发重绘；相同素材复用会话缓存，避免反复创建副本。
            asset_paths = self._persist_uploaded_assets(uploaded_files or [])
            if uploaded_files:
                st.success(tr("asset_based.assets.count", count=len(asset_paths)))
                
                # 长片常有大量素材，预览默认收起并分页，避免一次挂载所有视频播放器。
                with st.expander(tr("asset_based.assets.preview"), expanded=False):
                    page_size = 9
                    page = 0
                    if len(asset_paths) > page_size:
                        pages = list(range((len(asset_paths) + page_size - 1) // page_size))
                        if st.session_state.get("asset_preview_page") not in pages:
                            st.session_state.pop("asset_preview_page", None)
                        page = st.selectbox(
                            "素材预览页" if get_language() == "zh_CN" else "Asset preview page",
                            pages, format_func=lambda index: str(index + 1), key="asset_preview_page",
                        )
                    cols = st.columns(3)
                    start = page * page_size
                    preview_items = list(zip(uploaded_files, asset_paths))[start:start + page_size]
                    for i, (file, path) in enumerate(preview_items):
                        with cols[i % 3]:
                            # Check if image or video
                            ext = Path(path).suffix.lower()
                            if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                                st.image(file, caption=file.name, use_container_width=True)
                            elif ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                                st.video(file)
                                st.caption(file.name)
            else:
                st.info(tr("asset_based.assets.empty_hint"))
        
        # Video title & intent
        with st.container(border=True):
            st.markdown(f"**{tr('asset_based.section.video_info')}**")
            
            video_title = st.text_input(
                tr("asset_based.video_title"),
                placeholder=tr("asset_based.video_title_placeholder"),
                help=tr("asset_based.video_title_help"),
                key="asset_video_title"
            )
            
            intent = st.text_area(
                tr("asset_based.intent"),
                placeholder=tr("asset_based.intent_placeholder"),
                help=tr("asset_based.intent_help"),
                height=100,
                key="asset_intent"
            )
        
        return {
            "assets": asset_paths,
            "video_title": video_title,
            "intent": intent if intent else None
        }

    @staticmethod
    def _persist_uploaded_assets(uploaded_files: list) -> list[str]:
        """保留本页入口，上传去重逻辑与其他创作页共用同一实现。"""
        return persist_uploaded_files(uploaded_files, key=AssetBasedPipelineUI.name)

    @staticmethod
    def _return_to_analysis() -> None:
        """只更新导航位置，不清空上传缓存、标题、配音或长片参数。"""
        st.session_state["creation_flow_custom_media_step"] = 1
        st.session_state["_creation_flow_navigation"] = st.session_state.get("_creation_flow_navigation", 0) + 1
    
    def _render_video_config(self, pixelle_video: Any, asset_params: dict | None = None) -> dict:
        """Render video configuration section"""
        zh = get_language() == "zh_CN"
        # Duration configuration
        with st.container(border=True):
            st.markdown(f"**{tr('video.title')}**")
            # 短片保留原有精细时长，长片以章节预算驱动，避免只把旧滑块放大。
            length_labels = {
                "short": "短片 · 15–120 秒" if zh else "Short · 15–120 sec",
                "long": "长视频 · 5–10 分钟" if zh else "Long · 5–10 min",
            }
            length_mode = st.radio(
                "成片长度" if zh else "Video length",
                list(length_labels), format_func=lambda value: length_labels[value],
                horizontal=True, key="asset_length_mode",
            )
            narration_language = "zh"
            if length_mode == "long":
                duration_labels = {300: "5 分钟", 480: "8 分钟", 600: "10 分钟"} if zh else {
                    300: "5 minutes", 480: "8 minutes", 600: "10 minutes",
                }
                duration_col, language_col = st.columns(2)
                with duration_col:
                    duration = st.selectbox(
                        "目标时长" if zh else "Target duration", list(duration_labels),
                        format_func=lambda value: duration_labels[value], key="asset_long_duration",
                    )
                with language_col:
                    language_labels = {"zh": "中文", "en": "English"}
                    narration_language = st.selectbox(
                        "旁白语言" if zh else "Narration language", list(language_labels),
                        index=0 if zh else 1, format_func=lambda value: language_labels[value],
                        key="asset_narration_language",
                    )
                st.info(
                    "先理解素材，再分章编写完整旁白、匹配画面并合成长片。请在下方选择对应语言的音色，最后一步查看镜头与素材预算。"
                    if zh else "Analyze your assets, write chapter-based narration, match visuals and assemble a full video. Choose a matching voice below and review the asset budget in the final step."
                )
            else:
                duration = st.slider(
                    tr("asset_based.duration"), min_value=15, max_value=120, value=30, step=5,
                    help=tr("asset_based.duration_help"), key="asset_duration",
                )
                st.caption(tr("asset_based.duration_label", seconds=duration))
        
        # Workflow source selection
        with st.container(border=True):
            st.markdown(f"**{tr('asset_based.section.source')}**")
            
            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("asset_based.source.what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("asset_based.source.how"))
            
            # 素材分析固定使用 VLM API，旧来源值不再决定服务路由。
            st.session_state["asset_source"] = "api"
            api_asset_analysis = getattr(pixelle_video, "api_asset_analysis", None)
            api_vlm_models = (
                api_asset_analysis.list_models(configured_only=True)
                if api_asset_analysis is not None else []
            )
            analysis_options = [model["display_name"] for model in api_vlm_models]
            selected_analysis_workflow = {}
            analysis_provider = None
            analysis_video_max_frames = 16
            # 已配置但尚无目录的服务也要显示，不能让用户困在“无法选择→无法加载”。
            configured_providers = config_manager.get_api_providers_config()
            providers = list(dict.fromkeys(
                [model.get("provider", "dashscope") for model in api_vlm_models]
                + [provider for provider in ("openai", "dashscope")
                   if str(configured_providers.get(provider, {}).get("api_key") or "").strip()]
            ))
            if providers:
                provider_labels = {"openai": "OpenAI / 兼容接口" if zh else "OpenAI / compatible", "dashscope": "通义 / DashScope"}
                if st.session_state.get("asset_analysis_provider") not in providers:
                    st.session_state.pop("asset_analysis_provider", None)
                analysis_provider = st.selectbox(
                    "视觉分析服务商" if zh else "Vision analysis provider", providers,
                    format_func=lambda value: provider_labels.get(value, value), key="asset_analysis_provider",
                )
                api_vlm_models = [model for model in api_vlm_models if model.get("provider", "dashscope") == analysis_provider]
                analysis_options = [model["display_name"] for model in api_vlm_models]
            # 只展示当前连接的已保存目录；刷新或更换服务后，移除失效的旧选择。
            # 手动维护目录也在设置内完成，创作页不能另行插入未加载的候选。
            if st.session_state.get("asset_analysis_workflow") not in analysis_options:
                st.session_state.pop("asset_analysis_workflow", None)
            if not providers:
                st.session_state.pop("asset_analysis_provider", None)
            st.caption(
                "用于看懂上传的图片和视频，帮助文本模型编排内容；它与生成图片、生成视频的模型分开选择。"
                if zh else "Understands uploaded images and videos so the text model can plan the story. This is separate from image and video generation."
            )
            if analysis_options:
                selected_analysis = st.selectbox(
                    "素材分析 API 模型" if get_language() == "zh_CN" else "Asset analysis API model",
                    analysis_options, index=None, key="asset_analysis_workflow",
                    placeholder="选择支持图片输入的模型" if zh else "Choose a model that supports image input",
                    help=("来自当前服务已保存的模型目录。请选择支持图片输入的型号；接口返回名称不代表已验证视觉能力。" if zh else "From the saved catalog for this connection. Choose an image-input model; a listed ID does not verify vision support."),
                )
                if selected_analysis is not None:
                    selected_analysis_workflow = api_vlm_models[analysis_options.index(selected_analysis)]
                st.caption("模型目录在系统配置中加载并保存。接口新增型号后重新加载即可更新；这里没有内置型号兜底。" if zh else "Load and save the catalog in Settings. Reload it to see new IDs from your endpoint; no built-in model list is used here.")
                if selected_analysis_workflow.get("catalog_source") == "manual":
                    st.caption("当前目录为手动维护，尚未通过接口加载验证。" if zh else "This catalog was entered manually and has not been loaded from the API.")
                if not selected_analysis_workflow.get("configured", True):
                    st.warning(
                        "所选视觉服务尚未配置密钥。请到系统配置的对应提供商填写；保存后返回此页即可使用。"
                        if zh else "The selected vision provider has no API key. Configure its matching provider in Settings, then return here."
                    )
            elif analysis_provider:
                st.warning(
                    "视觉服务已配置，但尚未加载有效的模型目录。请点击下方按钮加载并保存，再选择支持图片输入的模型。"
                    if zh else "The vision service is configured, but no current catalog is loaded. Load and save its models below, then choose one that supports image input."
                )
                st.caption("只查询模型名称，不会上传素材、分析画面或生成视频。" if zh else "Reads model IDs only; no assets are uploaded or generated.")
                if st.button(
                    "加载并保存模型列表" if zh else "Load and save model list",
                    key="asset_load_analysis_models", use_container_width=True,
                ):
                    from web.pipelines.asset_catalog import load_and_save_asset_catalog

                    try:
                        with st.spinner("正在加载并保存模型列表…" if zh else "Loading and saving models…"):
                            snapshot = load_and_save_asset_catalog(config_manager, analysis_provider)
                        st.session_state["asset_catalog_feedback"] = {
                            "provider": analysis_provider, "count": len(snapshot["models"]),
                        }
                    except Exception:
                        # 第三方异常可能包含密钥/URL，界面只给固定说明，保持生成阻断。
                        st.error("模型列表加载或保存失败，请检查当前视觉服务的地址、密钥、代理和文件权限后重试。" if zh else "Could not load or save the catalog. Check the vision endpoint, credentials, proxy and file permissions, then retry.")
                    else:
                        # 全页重绘使 get_pixelle_video 根据新配置摘要重建服务，不直接更新旧服务快照。
                        st.rerun()
            else:
                st.warning(
                    "尚未配置视觉分析服务密钥。请在「系统配置 → 图片与视频 → OpenAI 或通义」配置；文本模型的密钥不会自动复用。"
                    if zh else "No vision provider API key is configured. Configure OpenAI or DashScope in Settings → Image & video; text-model credentials are not reused."
                )

            feedback = st.session_state.pop("asset_catalog_feedback", None)
            if feedback and feedback.get("provider") == analysis_provider:
                count = feedback["count"]
                if count:
                    st.success(f"已加载并保存 {count} 个模型，请明确选择支持图片输入的型号。" if zh else f"Loaded and saved {count} models. Choose one that supports image input.")
                else:
                    st.warning("接口返回 0 个模型，当前仍不能生成。请检查该密钥的模型权限或服务目录。" if zh else "The endpoint returned 0 models. Generation remains blocked; check model access and the service catalog.")

            if analysis_provider:
                analysis_video_max_frames = st.select_slider(
                    "视频分析抽帧上限" if zh else "Maximum sampled video frames",
                    options=[8, 16, 32], value=16, key="asset_analysis_video_max_frames",
                )
                st.caption(
                    "视频在本机均匀抽帧后交给视觉模型，并带采样时间；不会把整个视频当图片上传。帧数越多请求越大，抽帧可能遗漏短暂动作，不包含声音识别。"
                    if zh else "Videos are sampled locally at evenly spaced timestamps. More frames increase request size; brief actions may be missed and audio is not transcribed."
                )

            api_video_workflow = None
            api_video_params = {}
            api_video_workflows = list_api_media_workflows(
                pixelle_video,
                "video",
                required_adapter_abilities=["first_frame_i2v"],
                verified_only=True,
            )
            animation_source_options = ["none"]
            if api_video_workflows:
                animation_source_options.append("api")

            if st.session_state.get("asset_animation_source") not in animation_source_options:
                st.session_state.pop("asset_animation_source", None)

            def animation_source_label(value: str) -> str:
                if value == "none":
                    return "不启用" if get_language() == "zh_CN" else "Disabled"
                return workflow_source_label(value)

            animation_source = st.radio(
                "素材动画服务" if get_language() == "zh_CN" else "Asset animation service",
                animation_source_options,
                format_func=animation_source_label,
                horizontal=True,
                key="asset_animation_source",
                help=(
                    "选择是否把匹配到的图片素材动画化。不启用时保留原素材静态合成；API 模型会调用已验证的图生视频模型。"
                    if get_language() == "zh_CN"
                    else "Choose whether to animate matched image assets. Disabled keeps the original static asset composition; API models call verified image-to-video providers."
                ),
            )

            if animation_source == "api":
                animation_workflows = api_video_workflows
                animation_options = [wf["display_name"] for wf in animation_workflows]
                selected_animation = st.selectbox(
                    "素材动画工作流/模型" if get_language() == "zh_CN" else "Asset animation workflow/model",
                    animation_options,
                    index=0,
                    key="asset_animation_workflow",
                    help=workflow_select_help(),
                )
                selected_index = animation_options.index(selected_animation)
                selected_workflow = animation_workflows[selected_index]
                api_video_workflow = selected_workflow["key"]
                api_video_params = render_api_video_controls(
                    selected_workflow,
                    key_prefix="asset",
                    default_duration=5,
                    allow_audio_driven=True,
                    show_duration=False,
                )
        
        # TTS configuration
        with st.container(border=True):
            st.markdown(f"**{tr('section.tts')}**")
            
            # Import voice configuration
            from pixelle_video.tts_voices import EDGE_TTS_VOICES, get_voice_display_name
            
            # Get saved voice from config
            # 保留已存在线配音偏好，不读取旧的工作流模式。
            local_config = config_manager.config.comfyui.tts.local
            saved_voice = local_config.voice
            saved_speed = local_config.speed
            
            # Build voice options with i18n
            voice_options = []
            voice_ids = []
            default_voice_index = 0
            
            for idx, voice_config in enumerate(EDGE_TTS_VOICES):
                voice_id = voice_config["id"]
                display_name = get_voice_display_name(voice_id, tr, get_language())
                voice_options.append(display_name)
                voice_ids.append(voice_id)
                
                if voice_id == saved_voice:
                    default_voice_index = idx
            
            # Two-column layout
            voice_col, speed_col = st.columns([1, 1])
            
            with voice_col:
                selected_voice_display = st.selectbox(
                    tr("tts.voice_selector"),
                    voice_options,
                    index=default_voice_index,
                    key="asset_tts_voice"
                )
                selected_voice_index = voice_options.index(selected_voice_display)
                voice_id = voice_ids[selected_voice_index]
            
            with speed_col:
                tts_speed = st.slider(
                    tr("tts.speed"),
                    min_value=0.5,
                    max_value=2.0,
                    value=saved_speed,
                    step=0.1,
                    format="%.1fx",
                    key="asset_tts_speed"
                )
                st.caption(tr("tts.speed_label", speed=f"{tts_speed:.1f}"))
        
        return {
            "duration": duration,
            "narration_language": narration_language,
            "source": "api",
            "analysis_image_workflow": selected_analysis_workflow.get("image_workflow"),
            "analysis_video_workflow": selected_analysis_workflow.get("video_workflow"),
            "analysis_vlm_model": selected_analysis_workflow.get("model"),
            "analysis_vlm_configured": bool(selected_analysis_workflow) and selected_analysis_workflow.get("configured", True),
            "analysis_vlm_status": (
                "missing_credentials" if not analysis_provider else
                "missing_catalog" if not analysis_options else
                "not_selected" if not selected_analysis_workflow else
                "missing_credentials" if not selected_analysis_workflow.get("configured", True) else "ready"
            ),
            "analysis_vlm_provider": analysis_provider,
            "analysis_video_max_frames": analysis_video_max_frames,
            "api_video_workflow": api_video_workflow,
            "api_video_params": api_video_params,
            "voice_id": voice_id,
            "tts_speed": tts_speed
        }
    
    def _render_output_preview(self, pixelle_video: Any, video_params: dict):
        """Render output preview section"""
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            # 生成前的素材预算只读取表单，不触发视觉分析、配音或付费媒体请求。
            self._render_asset_plan(video_params)
            
            # Check configuration
            if not config_manager.validate():
                st.warning(tr("settings.not_configured"))
            
            # Check if assets are provided
            assets = video_params.get("assets", [])
            if not assets:
                st.info(tr("asset_based.output.no_assets"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="asset_generate_disabled"
                )
                self._render_generated_result()
                return
            
            # 配置不完整时禁止提交，避免后台沿用旧来源或默认工作流。
            if not video_params.get("analysis_vlm_model") or not video_params.get("analysis_vlm_configured", True):
                zh = get_language() == "zh_CN"
                status = video_params.get("analysis_vlm_status")
                if status == "missing_catalog":
                    message = "视觉服务已配置，但缺少当前连接的模型目录。请返回第二步加载并保存模型列表。" if zh else "The vision service is configured, but its current catalog is missing. Return to step 2 to load and save models."
                elif status == "missing_credentials":
                    message = "尚未配置可用的视觉服务密钥，请先在系统设置中配置 OpenAI 或通义视觉服务。" if zh else "No usable vision-provider credentials are configured. Configure OpenAI or DashScope in Settings."
                else:
                    message = "请返回第二步，明确选择支持图片输入的素材分析模型。" if zh else "Return to step 2 and choose an asset-analysis model that supports image input."
                st.info(message)
                st.button(
                    "返回选择素材分析模型" if zh else "Back to asset analysis model",
                    key="asset_return_to_analysis", on_click=self._return_to_analysis, use_container_width=True,
                )
                st.button(tr("btn.generate"), type="primary", use_container_width=True, disabled=True, key="asset_generate_disabled")
                self._render_generated_result()
                return

            # Show asset summary
            st.info(tr("asset_based.output.ready", count=len(assets)))
            
            # Generate button
            if st.button(tr("btn.generate"), type="primary", use_container_width=True, key="asset_generate"):
                # Validate
                if not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    # 只结束输出区域，仍让外层步骤导航渲染，方便返回修正配置。
                    return
                
                # Show progress
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                start_time = time.time()
                
                try:
                    # Import pipeline
                    from pixelle_video.pipelines.asset_based import AssetBasedPipeline
                    
                    # Create pipeline
                    pipeline = AssetBasedPipeline(pixelle_video)
                    
                    # Progress callback
                    def update_progress(event: ProgressEvent):
                        if event.event_type == "analyzing_assets":
                            if event.extra_info == "start":
                                message = tr("asset_based.progress.analyzing_start", total=event.frame_total)
                            else:
                                message = tr("asset_based.progress.analyzing_complete", count=event.frame_total)
                        elif event.event_type == "analyzing_asset":
                            message = tr(
                                "asset_based.progress.analyzing_asset",
                                current=event.frame_current,
                                total=event.frame_total,
                                name=event.extra_info or ""
                            )
                        elif event.event_type == "generating_script":
                            if event.extra_info == "complete":
                                message = tr("asset_based.progress.script_complete")
                            elif event.frame_current and event.frame_total:
                                # 长片逐章生成时显示明确进度，避免长时间只停留在“编写脚本”。
                                current, total = event.frame_current, event.frame_total
                                message = (
                                    f"正在编写第 {current} / {total} 章"
                                    if get_language() == "zh_CN"
                                    else f"Writing chapter {current} / {total}"
                                )
                            else:
                                message = tr("asset_based.progress.generating_script")
                        elif event.event_type == "frame_step":
                            action_key = f"progress.step_{event.action}"
                            action_text = tr(action_key)
                            message = tr(
                                "progress.frame_step",
                                current=event.frame_current,
                                total=event.frame_total,
                                step=event.step,
                                action=action_text
                            )
                        elif event.event_type == "processing_frame":
                            message = tr(
                                "progress.frame",
                                current=event.frame_current,
                                total=event.frame_total
                            )
                        elif event.event_type == "concatenating":
                            if event.extra_info == "complete":
                                message = tr("asset_based.progress.concat_complete")
                            else:
                                message = tr("progress.concatenating")
                        elif event.event_type == "completed":
                            message = tr("progress.completed")
                        else:
                            message = tr(f"progress.{event.event_type}")
                        
                        status_text.text(message)
                        progress_bar.progress(min(int(event.progress * 100), 99))
                    
                    # Execute pipeline with progress callback
                    if not video_params.get("analysis_vlm_model") or not video_params.get("analysis_vlm_configured", True):
                        raise RuntimeError(
                            "请先在素材分析服务中选择 API VLM 模型。"
                            if get_language() == "zh_CN"
                            else "Please select an API VLM model in the asset analysis service settings."
                        )

                    # 动画选择来自同一 API 注册表，旧草稿中的工作流不得进入后端。
                    animation_model = video_params.get("api_video_workflow")
                    if animation_model and not animation_model.startswith("api/"):
                        raise ValueError("请选择 API 动画模型。" if get_language() == "zh_CN" else "Select an API animation model.")

                    ctx = run_async(pipeline(
                        assets=video_params["assets"],
                        video_title=video_params.get("video_title", ""),
                        intent=video_params.get("intent"),
                        duration=video_params.get("duration", 30),
                        source="api",
                        analysis_image_workflow=None,
                        analysis_video_workflow=None,
                        analysis_vlm_model=video_params.get("analysis_vlm_model"),
                        analysis_vlm_provider=video_params.get("analysis_vlm_provider") or "dashscope",
                        analysis_video_max_frames=video_params.get("analysis_video_max_frames", 16),
                        narration_language=video_params.get("narration_language", "zh"),
                        bgm_path=video_params.get("bgm_path"),
                        bgm_volume=video_params.get("bgm_volume", 0.2),
                        bgm_mode=video_params.get("bgm_mode", "loop"),
                        api_video_workflow=video_params.get("api_video_workflow"),
                        api_video_params=video_params.get("api_video_params"),
                        voice_id=video_params.get("voice_id", "zh-CN-YunjianNeural"),
                        tts_speed=video_params.get("tts_speed", 1.2),
                        progress_callback=update_progress
                    ))
                    
                    total_time = time.time() - start_time
                    
                    progress_bar.progress(100)
                    status_text.text(tr("status.success"))
                    
                    # 缓存已完成结果的引用；返回前面的步骤再回来仍可预览、下载。
                    st.session_state["asset_generated_result"] = {
                        "path": ctx.final_video_path,
                        "generation_time": total_time,
                        "scene_count": len(ctx.storyboard.frames) if ctx.storyboard else 0,
                        "duration_report": getattr(ctx, "duration_report", None),
                        "analysis_warning_count": len(getattr(ctx, "analysis_warnings", []) or []),
                    }
                
                except Exception as e:
                    status_text.text("")
                    progress_bar.empty()
                    st.error(tr("status.error", error=str(e)))
                    logger.exception(e)
                    return

            self._render_generated_result()

    @staticmethod
    def _render_asset_plan(params: dict):
        """长片预算与后端共用算法；素材覆盖度只做预估，不承诺独立镜头数量。"""
        duration = params.get("duration", 30)
        if duration < 300:
            return
        from pixelle_video.utils.long_video import build_long_video_plan

        zh = get_language() == "zh_CN"
        plan = build_long_video_plan(
            duration, params.get("narration_language", "zh"), params.get("tts_speed", 1.2),
        )
        assets = params.get("assets") or []
        image_count = sum(Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"} for path in assets)
        video_count = len(assets) - image_count
        st.markdown("**长视频素材计划**" if zh else "**Long-video asset plan**")
        target, scenes, media = st.columns(3)
        target.metric("目标成片" if zh else "Target duration", f"{duration // 60}:00")
        scenes.metric("预计镜头" if zh else "Planned scenes", plan["scene_count"])
        media.metric("已上传素材" if zh else "Uploaded assets", len(assets))
        unit = ("中文字" if zh else "Chinese characters") if params.get("narration_language", "zh") == "zh" else ("英文单词" if zh else "English words")
        st.caption(
            f"{plan['chapter_count']} 个章节 · 约 {plan['target_units']} 个{unit} · {image_count} 张图片 / {video_count} 段视频。目标为估算值，实际时长在合成后检测。"
            if zh else f"{plan['chapter_count']} chapters · about {plan['target_units']} {unit} · {image_count} images / {video_count} videos. The target is estimated; the final duration is measured after composition."
        )
        if assets and len(assets) < plan["scene_count"]:
            st.warning(
                "素材数量少于预计镜头，部分素材可能多次使用。较长视频可以提供多个片段；增加不同场景的图片和视频可减少画面重复。"
                if zh else "There are fewer assets than planned scenes, so some may be reused. Longer videos can supply multiple clips; varied images and scenes reduce repetition."
            )
        st.caption(
            ("已启用图片动画：每次匹配图片都可能额外调用图生视频 API。" if params.get("api_video_workflow") else "图片以静态画面配旁白，视频使用原素材；不调用图生视频模型。")
            if zh else
            ("Image animation is enabled: matched images may require extra image-to-video API requests." if params.get("api_video_workflow") else "Images remain still with narration, and videos use the original footage. No image-to-video generation is requested.")
        )
        if video_count:
            st.caption(
                "同一视频多次引用时按时间均匀取段，并非逐镜头语义定位。原片段短于旁白时可能循环画面；原视频声音不混入成片。"
                if zh else "Repeated video assets use evenly spaced excerpts, not semantic shot matching. Short footage may loop to cover narration; original audio is not mixed in."
            )

    @staticmethod
    def _render_generated_result():
        """只展示本会话已成功生成的结果，不因导航或改参数重复提交任务。"""
        result = st.session_state.get("asset_generated_result")
        if not result:
            return
        video_path = result["path"]
        st.markdown("---")
        st.caption("上次生成结果" if get_language() == "zh_CN" else "Last generated result")
        if not os.path.exists(video_path):
            st.error(tr("status.video_not_found", path=video_path))
            return
        st.success(tr("status.video_generated", path=video_path))
        if result.get("analysis_warning_count"):
            count = result["analysis_warning_count"]
            st.warning(
                f"有 {count} 份素材分析失败，已从本次长片排除；成片使用其余可用素材。"
                if get_language() == "zh_CN" else f"Analysis failed for {count} assets. They were excluded from the long video; the output uses the remaining assets."
            )
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        st.caption(
            f"⏱️ {tr('info.generation_time')} {result['generation_time']:.1f}s   "
            f"📦 {file_size_mb:.2f}MB   🎬 {result['scene_count']}{tr('info.scenes_unit')}"
        )
        report = result.get("duration_report") or {}
        if report:
            zh = get_language() == "zh_CN"
            if report.get("measurement_status") == "measured":
                from web.components.long_video import format_duration

                st.caption(
                    f"{'实际成片' if zh else 'Actual duration'} {format_duration(report['actual_duration_seconds'])} · "
                    f"{'目标' if zh else 'Target'} {format_duration(report['target_duration_seconds'])}"
                )
                if not report.get("within_tolerance", True):
                    st.warning("实际时长与目标有偏差，可调整文案方向或配音语速。" if zh else "The output differs from the target. Adjust the script direction or speech rate if needed.")
            else:
                st.warning("成片已生成，但实际时长检测未成功。" if zh else "The video was generated, but its duration could not be measured.")
        st.video(video_path)
        with open(video_path, "rb") as video_file:
            st.download_button(
                label="⬇️ 下载视频" if get_language() == "zh_CN" else "⬇️ Download Video",
                data=video_file.read(),
                file_name=os.path.basename(video_path),
                mime="video/mp4",
                use_container_width=True,
                key="asset_download",
            )


# Register self
register_pipeline_ui(AssetBasedPipelineUI)
