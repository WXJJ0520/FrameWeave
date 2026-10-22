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
Output preview components for web UI (right column)
"""

import os
from html import escape
from math import gcd
from pathlib import Path

import streamlit as st
from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.models.progress import ProgressEvent
from web.i18n import get_language, tr
from web.utils.async_helpers import run_async


def _render_studio_overview(video_params):
    """概览只读取当前表单和模板尺寸；所有动态 HTML 均进行转义。"""
    zh = get_language() == "zh_CN"
    if video_params.get("batch_mode"):
        count = len(video_params.get("topics") or [])
        scenes = video_params.get("n_scenes", 5)
        scene_value = f"{count} 条 · 每条 {scenes} 镜" if zh else f"{count} videos · {scenes} scenes each"
    elif video_params.get("mode", "generate") == "fixed":
        scene_value = "按脚本分段" if zh else "From script sections"
    elif video_params.get("target_duration_seconds"):
        scene_value = "按目标时长规划" if zh else "Planned from target duration"
    else:
        scene_value = str(video_params.get("n_scenes", 5))

    width = video_params.get("media_width") or st.session_state.get("template_media_width")
    height = video_params.get("media_height") or st.session_state.get("template_media_height")
    ratio = (video_params.get("api_video_params") or {}).get("video_ratio")
    if width and height:
        divisor = gcd(int(width), int(height))
        ratio = ratio or f"{int(width) // divisor}:{int(height) // divisor}"
        canvas_value = f"{ratio} · {width} × {height}"
    else:
        canvas_value = ratio or ("随模板确定" if zh else "From template")

    voice_value = "Edge TTS"
    voice_detail = video_params.get("tts_voice") or voice_value
    workflow = video_params.get("media_workflow") or ""
    if workflow.startswith("api/"):
        provider = workflow.split("/")[1]
        source_value = {"xai": "xAI / Grok", "muse": "Meta Muse", "ark": "ARK"}.get(provider, provider.title())
    elif Path(video_params.get("frame_template") or "").name.startswith("static_"):
        source_value = "静态模板" if zh else "Static template"
    else:
        source_value = "待选择" if zh else "Not selected"

    fields = (
        ("分镜" if zh else "Scenes", scene_value, scene_value),
        ("素材画幅" if zh else "Media format", canvas_value, canvas_value),
        ("配音" if zh else "Voice", voice_value, voice_detail),
        ("画面来源" if zh else "Visual source", source_value, workflow or source_value),
    )
    items = "".join(
        '<div class="studio-overview-item">'
        f'<span>{escape(label)}</span><strong title="{escape(str(detail), quote=True)}">'
        f'{escape(str(value))}</strong></div>'
        for label, value, detail in fields
    )
    st.markdown(f'<div class="studio-overview">{items}</div>', unsafe_allow_html=True)


def _render_studio_monitor(video_params, *, show_result=True):
    """未生成时显示明确空态；已有成片只从会话中的本地路径读取，不触发生成。"""
    zh = get_language() == "zh_CN"
    cached = st.session_state.get("studio_last_video_result") if show_result else None
    if cached and os.path.isfile(cached.get("video_path", "")):
        st.caption("上次生成的成片" if zh else "Last generated video")
        st.video(cached["video_path"])
        caption = (
            f"{cached['n_scenes']} {'个分镜' if zh else 'scenes'} · "
            f"{cached['width']} × {cached['height']} · "
            f"{cached['file_size'] / (1024 * 1024):.2f} MB · "
            f"{'生成耗时' if zh else 'Generated in'} {cached['generation_time']:.1f}s"
        )
        st.caption(caption)
        # 实际时长来自后端成片检测，旧会话没有该字段时不编造一个值。
        duration_report = cached.get("duration_report") or {}
        if duration_report.get("measurement_status") == "unavailable":
            st.warning(
                "成片已生成，但暂未检测到实际时长，不能确认是否达到目标。"
                if zh else "The video was generated, but its duration could not be measured against the target."
            )
        elif cached.get("duration") is not None:
            from web.components.long_video import format_duration

            measured = format_duration(cached["duration"])
            target_seconds = cached.get("target_duration_seconds")
            text = f"实际成片时长 {measured}" if zh else f"Actual duration {measured}"
            if target_seconds:
                text += f" · {'目标' if zh else 'Target'} {format_duration(target_seconds)}"
            st.caption(text)
            if target_seconds and abs(cached["duration"] - target_seconds) > max(15, target_seconds * 0.15):
                st.warning(
                    "实际时长与目标有偏差，当前展示的是完整成片；可以调整稿件长度或语速。"
                    if zh else "The complete output differs from the target duration. Adjust the script length or speech rate if needed."
                )
        with open(cached["video_path"], "rb") as video_file:
            st.download_button(
                "下载视频" if zh else "Download video",
                data=video_file.read(),
                file_name=os.path.basename(cached["video_path"]),
                mime="video/mp4",
                use_container_width=True,
                key="studio_download_video",
            )
        return

    if cached:
        # 文件已移走时清除失效引用，避免把缓存记录误当作可播放成片。
        st.session_state.pop("studio_last_video_result", None)
        st.caption("上次成片文件已移动，可到历史记录中查看。" if zh else "The previous file was moved. Check History for its record.")
    heading = "视频预览" if zh else "Video preview"
    message = "生成后在这里查看成片" if zh else "Your finished video will appear here"
    status = "尚未生成" if zh else "No video generated"
    # 此处是原有单条视频预览，不引入独立项目概念。
    title = video_params.get("title") or ("未命名视频" if zh else "Untitled video")
    # 纯 SVG 只表达画框占位，不展示虚构视频画面、进度或播放状态。
    st.markdown(
        '<div class="studio-monitor">'
        f'<div class="monitor-topbar"><span>{escape(heading)}</span><span>{escape(status)}</span></div>'
        '<div class="monitor-canvas"><div class="monitor-empty">'
        '<svg class="monitor-frame-art" width="160" height="120" viewBox="0 0 160 120" '
        'fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<rect x="26" y="19" width="108" height="82" rx="12" stroke="currentColor" stroke-width="1.5"/>'
        '<rect x="37" y="30" width="86" height="60" rx="5" stroke="currentColor" stroke-opacity=".35"/>'
        '<path d="M71 47L92 60L71 73V47Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M12 38V27C12 15 18 9 30 9H41M119 111H130C142 111 148 105 148 93V82" '
        'stroke="currentColor" stroke-opacity=".35" stroke-linecap="round"/>'
        '</svg>'
        f'<strong>{escape(heading)}</strong><p>{escape(message)}</p></div></div>'
        f'<div class="monitor-footer"><span>{escape(str(title))}</span>'
        f'<span>{"准备创作" if zh else "Ready to create"}</span></div></div>',
        unsafe_allow_html=True,
    )


def _api_media_ready(video_params):
    """在单条/批量提交前校验来源，防止空选择或旧草稿触发后端默认工作流。"""
    workflow = video_params.get("media_workflow") or ""
    if workflow:
        return workflow.startswith("api/")
    requires_media = video_params.get("requires_api_media")
    if requires_media is not None:
        return not requires_media
    from pixelle_video.utils.template_util import get_template_type
    return bool(video_params.get("frame_template")) and get_template_type(video_params["frame_template"]) == "static"


def _api_media_warning():
    """缺少模型时提供同一提示，不把旧工作流重新暴露给用户。"""
    st.warning("请先选择适用于当前模板的 API 模型。" if get_language() == "zh_CN" else "Select an API model compatible with this template first.")


def render_output_preview(pixelle_video, video_params):
    """Render output preview section (right column)"""
    # Check if batch mode
    is_batch = video_params.get("batch_mode", False)
    
    if is_batch:
        # Batch generation mode
        render_batch_output(pixelle_video, video_params)
    else:
        # Single video generation mode (original logic)
        render_single_output(pixelle_video, video_params)


def render_single_output(pixelle_video, video_params):
    """Render single video generation output (original logic, unchanged)"""
    # Extract parameters from video_params dict
    text = video_params.get("text", "")
    mode = video_params.get("mode", "generate")
    title = video_params.get("title")
    n_scenes = video_params.get("n_scenes", 5)
    split_mode = video_params.get("split_mode", "paragraph")
    target_duration_seconds = video_params.get("target_duration_seconds")
    narration_language = video_params.get("narration_language", "zh")
    bgm_path = video_params.get("bgm_path")
    bgm_volume = video_params.get("bgm_volume", 0.2)
    
    # 当前 Web 配音只走在线 Edge TTS，不能从旧草稿恢复工作流模式。
    tts_mode = "local"
    selected_voice = video_params.get("tts_voice")
    tts_speed = video_params.get("tts_speed")
    
    frame_template = video_params.get("frame_template")
    custom_values_for_video = video_params.get("template_params", {})
    workflow_key = video_params.get("media_workflow")
    api_video_params = video_params.get("api_video_params")
    prompt_prefix = video_params.get("prompt_prefix", "")
    
    with st.container(border=False):
        _render_studio_monitor(video_params)
        _render_studio_overview(video_params)
        long_video_ready = True
        if target_duration_seconds is not None:
            from web.components.long_video import render_long_video_summary

            long_video_ready = render_long_video_summary(video_params)
        
        # Check if system is configured
        if not config_manager.validate():
            st.warning(tr("settings.not_configured"))
        
        media_ready = _api_media_ready(video_params)
        if not media_ready:
            _api_media_warning()

        # Generate Button
        if st.button(tr("btn.generate"), type="primary", use_container_width=True, key="studio_generate", disabled=not (media_ready and long_video_ready)):
            # Validate system configuration
            if not config_manager.validate():
                st.error(tr("settings.not_configured"))
                # 只结束当前输出处理，让外层“上一步”继续渲染以便修正配置。
                return
            
            # Validate input
            if not text:
                st.error(tr("error.input_required"))
                return

            # 二次校验是提交边界，禁用按钮不是唯一保护。
            if not _api_media_ready(video_params):
                _api_media_warning()
                return
            if not long_video_ready:
                return

            # Show progress
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Record start time for generation
            import time
            start_time = time.time()
            
            try:
                # Progress callback to update UI
                def update_progress(event: ProgressEvent):
                    """Update progress bar and status text from ProgressEvent"""
                    # Translate event to user-facing message
                    if event.event_type == "frame_step":
                        # Frame step: "分镜 3/5 - 步骤 2/4: 生成插图"
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
                        # Processing frame: "分镜 3/5"
                        message = tr(
                            "progress.frame",
                            current=event.frame_current,
                            total=event.frame_total
                        )
                    else:
                        # Simple events: use i18n key directly
                        message = tr(f"progress.{event.event_type}")
                    
                    # Append extra_info if available (e.g., batch progress)
                    if event.extra_info:
                        message = f"{message} - {event.extra_info}"
                    
                    status_text.text(message)
                    progress_bar.progress(min(int(event.progress * 100), 99))  # Cap at 99% until complete
                
                # Generate video (directly pass parameters)
                # Note: media_width and media_height are auto-determined from template
                video_params = {
                    "text": text,
                    "mode": mode,
                    "title": title if title else None,
                    "n_scenes": n_scenes,
                    "split_mode": split_mode,
                    "media_workflow": workflow_key,
                    "api_video_params": api_video_params,
                    "frame_template": frame_template,
                    "prompt_prefix": prompt_prefix,
                    "bgm_path": bgm_path,
                    "bgm_volume": bgm_volume if bgm_path else 0.2,
                    "progress_callback": update_progress,
                    "media_width": st.session_state.get('template_media_width'),
                    "media_height": st.session_state.get('template_media_height'),
                }
                video_params["tts_inference_mode"] = tts_mode
                video_params["tts_voice"] = selected_voice
                video_params["tts_speed"] = tts_speed
                if target_duration_seconds is not None:
                    # 与短片使用同一生成服务，后端按目标规划章节并忽略旧分镜数滑块。
                    video_params["target_duration_seconds"] = target_duration_seconds
                    video_params["narration_language"] = narration_language

                # Add custom template parameters if any
                if custom_values_for_video:
                    video_params["template_params"] = custom_values_for_video
                
                result = run_async(pixelle_video.generate_video(**video_params))
                
                # Calculate total generation time
                total_generation_time = time.time() - start_time
                
                progress_bar.progress(100)
                status_text.text(tr("status.success"))
                
                # 只缓存播放所需路径与轻量元数据；切换标签或下载触发 rerun 时无需重跑生成。
                from pixelle_video.utils.template_util import (
                    parse_template_size,
                    resolve_template_path,
                )
                template_path = resolve_template_path(result.storyboard.config.frame_template)
                video_width, video_height = parse_template_size(template_path)
                if os.path.isfile(result.video_path):
                    st.session_state["studio_last_video_result"] = {
                        "video_path": str(result.video_path),
                        "title": str(title or ""),
                        "file_size": result.file_size,
                        "n_scenes": len(result.storyboard.frames),
                        "width": video_width,
                        "height": video_height,
                        "generation_time": total_generation_time,
                        "duration": getattr(result, "duration", None),
                        "target_duration_seconds": target_duration_seconds,
                        "duration_report": getattr(result, "duration_report", None),
                    }
                    st.rerun()
                else:
                    st.error(tr("status.video_not_found", path=result.video_path))
                
            except Exception as e:
                status_text.text("")
                progress_bar.empty()
                st.error(tr("status.error", error=str(e)))
                logger.exception(e)
                return


def _render_cached_batch_result():
    """只展示最近完成的批次摘要；重新进入步骤时绝不重新提交任务。"""
    cached = st.session_state.get("studio_last_batch_result")
    if not cached:
        return
    zh = get_language() == "zh_CN"
    st.markdown("---")
    st.markdown("**上次批量结果**" if zh else "**Last batch results**")
    st.caption(
        "这是上次执行的结果，修改当前设置不会重新生成。"
        if zh else "These are the previous results. Editing the current settings does not generate again."
    )
    col1, col2, col3 = st.columns(3)
    col1.metric(tr("batch.total"), cached["total_count"])
    col2.metric(f"✅ {tr('batch.success')}", cached["success_count"])
    col3.metric(f"❌ {tr('batch.failed')}", cached["failed_count"])
    minutes, seconds = divmod(int(cached["duration_seconds"]), 60)
    st.caption(f"⏱️ {tr('batch.total_time')}: {minutes}{tr('batch.minutes')}{seconds}{tr('batch.seconds')}")
    if cached["failed_count"]:
        st.warning(
            "部分任务未完成，请查看下方失败清单；已完成的视频可到作品记录查看。"
            if zh else "Some tasks did not complete. Review the failed tasks below; completed videos are in History."
        )
    else:
        st.success(tr("batch.success_message"))
    st.info(tr("batch.view_in_history"))
    st.markdown(f"[📚 {tr('batch.goto_history')}](/History)")
    if cached["errors"]:
        st.markdown(f"#### {tr('batch.failed_list')}")
        for item in cached["errors"]:
            with st.expander(f"🔴 {tr('batch.task')} {item['index']}: {item['topic']}", expanded=False):
                # 第三方异常可能包含 API Key 或签名链接；展示失败任务，不缓存原始堆栈。
                st.error(
                    "该任务未完成。请检查模型、配音和连接设置，详细原因可查看本地运行日志。"
                    if zh else "This task did not complete. Check the model, voice and connection settings; see local logs for details."
                )


def _render_batch_execution_failure(exception_type):
    """整体批次异常只显示固定建议及安全类型，不显示第三方响应或 URL。"""
    zh = get_language() == "zh_CN"
    st.error(
        "最近一次批量任务未能完成。请检查设置后重试，已生成的视频可到作品记录查看。"
        if zh else "The latest batch did not complete. Check the settings before trying again; generated videos are in History."
    )
    st.caption(f"{'错误类型' if zh else 'Error type'}: {exception_type}")


def render_batch_output(pixelle_video, video_params):
    """Render batch generation output (minimal, redirect to History)"""
    topics = video_params.get("topics", [])
    
    with st.container(border=False):
        _render_studio_monitor(video_params, show_result=False)
        _render_studio_overview(video_params)
        st.markdown(f"**{tr('batch.section_generation')}**")
        # 结果先于本次草稿校验展示，修改输入或模型后仍可查看上次执行的统计。
        _render_cached_batch_result()
        execution_failure = st.empty()
        if st.session_state.get("studio_last_batch_failure"):
            with execution_failure.container():
                _render_batch_execution_failure(st.session_state["studio_last_batch_failure"])
        
        # Check if topics are provided
        if not topics:
            st.warning(tr("batch.no_topics"))
            return
        
        # Check system configuration
        if not config_manager.validate():
            st.warning(tr("settings.not_configured"))
            return
        
        if not _api_media_ready(video_params):
            _api_media_warning()
            return

        batch_count = len(topics)
        
        # Display batch info
        st.info(tr("batch.prepare_info", count=batch_count))
        
        # Estimated time (optional)
        estimated_minutes = batch_count * 3  # Assume 3 minutes per video
        st.caption(tr("batch.estimated_time", minutes=estimated_minutes))
        
        # Generate button with batch semantics
        if st.button(
            tr("batch.generate_button", count=batch_count),
            type="primary",
            use_container_width=True,
            help=tr("batch.generate_help")
        ):
            # 只有明确提交新批次才清除上次整体异常；已完成的摘要保留到新批次完成。
            st.session_state.pop("studio_last_batch_failure", None)
            execution_failure.empty()
            # Prepare shared config
            shared_config = {
                "title_prefix": video_params.get("title_prefix"),
                "n_scenes": video_params.get("n_scenes") or 5,
                "media_workflow": video_params.get("media_workflow"),
                "api_video_params": video_params.get("api_video_params"),
                "frame_template": video_params.get("frame_template"),
                "prompt_prefix": video_params.get("prompt_prefix") or "",
                "bgm_path": video_params.get("bgm_path"),
                "bgm_volume": video_params.get("bgm_volume") or 0.2,
                "tts_inference_mode": "local",
                "media_width": video_params.get("media_width"),
                "media_height": video_params.get("media_height"),
            }
            # 批量任务同样固定走在线配音，不透传旧工作流参数。
            for key in ("tts_voice", "tts_speed"):
                if video_params.get(key) is not None:
                    shared_config[key] = video_params[key]

            # Add template parameters
            if video_params.get("template_params"):
                shared_config["template_params"] = video_params["template_params"]
            
            # UI containers
            overall_progress_container = st.container()
            current_task_container = st.container()
            
            # Overall progress UI
            overall_progress_bar = overall_progress_container.progress(0)
            overall_status = overall_progress_container.empty()
            
            # Current task progress UI
            current_task_title = current_task_container.empty()
            current_task_progress = current_task_container.progress(0)
            current_task_status = current_task_container.empty()
            
            # Overall progress callback
            def update_overall_progress(current, total, topic):
                progress = (current - 1) / total
                overall_progress_bar.progress(progress)
                overall_status.markdown(
                    f"📊 **{tr('batch.overall_progress')}**: {current}/{total} ({int(progress * 100)}%)"
                )
            
            # Single task progress callback factory
            def make_task_progress_callback(task_idx, topic):
                def callback(event: ProgressEvent):
                    # Display current task title
                    current_task_title.markdown(f"🎬 **{tr('batch.current_task')} {task_idx}**: {topic}")
                    
                    # Update task detailed progress
                    if event.event_type == "frame_step":
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
                    else:
                        message = tr(f"progress.{event.event_type}")
                    
                    current_task_progress.progress(event.progress)
                    current_task_status.text(message)
                
                return callback
            
            # Execute batch generation
            import time

            from web.utils.batch_manager import SimpleBatchManager
            
            start_time = time.time()
            try:
                batch_manager = SimpleBatchManager()
                batch_result = batch_manager.execute_batch(
                    pixelle_video=pixelle_video,
                    topics=topics,
                    shared_config=shared_config,
                    overall_progress_callback=update_overall_progress,
                    task_progress_callback_factory=make_task_progress_callback
                )
            except Exception as error:
                # 不使用 st.stop，确保外层仍能渲染“上一步”，也不输出可能带凭据的异常正文。
                exception_type = type(error).__name__
                if not exception_type.isidentifier() or len(exception_type) > 80:
                    exception_type = "Exception"
                st.session_state["studio_last_batch_failure"] = exception_type
                overall_progress_bar.empty()
                overall_status.empty()
                current_task_title.empty()
                current_task_progress.empty()
                current_task_status.empty()
                with execution_failure.container():
                    _render_batch_execution_failure(exception_type)
                logger.warning("Batch execution did not complete (error_type={})", exception_type)
                return
            
            total_time = time.time() - start_time
            
            # Clear progress displays
            overall_progress_bar.progress(1.0)
            overall_status.markdown(f"✅ **{tr('batch.completed')}**")
            current_task_title.empty()
            current_task_progress.empty()
            current_task_status.empty()
            
            # 只保存结果摘要和失败任务标识，不把原始异常、堆栈或服务配置放入会话缓存。
            st.session_state["studio_last_batch_result"] = {
                "total_count": batch_result["total_count"],
                "success_count": batch_result["success_count"],
                "failed_count": batch_result["failed_count"],
                "duration_seconds": total_time,
                "errors": [
                    {"index": item["index"], "topic": item["topic"]}
                    for item in batch_result["errors"]
                ],
            }
            # 完成后重绘稳定的缓存结果区，避免同一轮同时显示新旧批次统计。
            st.rerun()
