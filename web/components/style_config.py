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
Style configuration components for web UI (middle column)
"""

import base64
import os
from pathlib import Path

import streamlit as st
from loguru import logger

from pixelle_video.config import config_manager
from web.i18n import get_language, tr
from web.pipelines.api_workflows import (
    list_api_media_workflows,
    render_api_video_controls,
    workflow_select_help,
    workflow_source_help,
)
from web.utils.async_helpers import run_async


def is_api_workflow(workflow_key: str | None) -> bool:
    """Return True for direct provider workflow keys such as api/dashscope/xxx."""
    return bool(workflow_key and workflow_key.startswith("api/"))


def migrate_template_branding(state, parameters, preview_default_text):
    """仅升级内置模板的旧品牌默认缓存，用户自定义的文字始终保留。"""
    replacements = {
        "author": (("@Pixelle.AI", "Pixelle.AI"), "@镜织 FrameWeave"),
        "signature": (("@Pixelle.AI",), "@镜织 FrameWeave"),
        "brand": (("Pixelle-Video",), "镜织 FrameWeave"),
        "describe": (("Open Source Omnimodal AI Creative Agent",), "用 AI 把想法变成视频"),
    }
    for name, (old_defaults, new_default) in replacements.items():
        # 自定义模板若使用不同默认值，不应被产品品牌迁移覆盖。
        if parameters.get(name, {}).get("default") != new_default:
            continue
        widget_key = f"video_custom_{name}"
        marker = f"_frameweave_brand_migrated_{widget_key}"
        if state.get(marker):
            continue
        if state.get(widget_key) in old_defaults:
            state[widget_key] = new_default
        # 每个字段只迁移一次，之后用户即使主动填写旧品牌也不再强制替换。
        state[marker] = True

    preview_marker = "_frameweave_brand_migrated_preview_text"
    old_preview_defaults = (
        "Pixelle.AI 正在用人工智能改变内容创作的方式，让每个人都能轻松制作专业级视频。",
        "Artificial intelligence is transforming the way Pixelle.AI creates content, making it easy for everyone to produce professional-grade videos.",
    )
    if not state.get(preview_marker):
        if state.get("preview_text") in old_preview_defaults:
            state["preview_text"] = preview_default_text
        state[preview_marker] = True


def get_template_preview_path(template_path: str, language: str = "zh_CN") -> str:
    """优先使用镜织内置预览；用户自定义模板仍沿用其原有预览图片。"""
    template = Path(template_path)
    if len(template.parts) != 2:
        return ""
    size, filename = template.parts
    suffix = "" if language == "zh_CN" else "_en"
    preview_roots = [Path("docs/images")]
    if not (Path("data/templates") / template).is_file():
        preview_roots.insert(0, Path("docs/images/frameweave"))
    for root in preview_roots:
        for language_suffix in dict.fromkeys((suffix, "")):
            for extension in (".png", ".jpg"):
                preview = root / size / f"{Path(filename).stem}{language_suffix}{extension}"
                if preview.is_file():
                    return str(preview)
    return ""


def render_style_config(pixelle_video):
    """Render style configuration section (middle column)"""
    # TTS Section (moved from left column)
    # ====================================================================
    with st.container(border=True):
        st.markdown(f"**{tr('section.tts')}**")

        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            st.markdown(tr("tts.what"))
            st.markdown(f"**{tr('help.how')}**")
            st.markdown(tr("tts.how"))

        # Web 入口仅使用在线语音接口；覆盖旧会话中的工作流模式，避免隐式回退。
        tts_mode = "local"
        st.session_state["tts_inference_mode"] = "local"
        st.caption(
            "在线配音 · Edge TTS，需要联网，无需单独填写密钥。"
            if get_language() == "zh_CN"
            else "Online speech · Edge TTS requires internet access, with no separate API key."
        )

        # Import voice configuration
        from pixelle_video.tts_voices import EDGE_TTS_VOICES, get_voice_display_name

        # Get saved voice from config
        # 真实管理器的扁平 getter 不含音色偏好，从已载入 schema 读取。
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

            # Set default index if matches saved voice
            if voice_id == saved_voice:
                default_voice_index = idx

        # Two-column layout: Voice | Speed
        voice_col, speed_col = st.columns([1, 1])

        with voice_col:
            # Voice selector
            selected_voice_display = st.selectbox(
                tr("tts.voice_selector"),
                voice_options,
                index=default_voice_index,
                key="tts_local_voice"
            )

            # Get actual voice ID
            selected_voice_index = voice_options.index(selected_voice_display)
            selected_voice = voice_ids[selected_voice_index]

        with speed_col:
            # Speed slider
            tts_speed = st.slider(
                tr("tts.speed"),
                min_value=0.5,
                max_value=2.0,
                value=saved_speed,
                step=0.1,
                format="%.1fx",
                key="tts_local_speed"
            )
            st.caption(tr("tts.speed_label", speed=f"{tts_speed:.1f}"))


        # ================================================================
        # TTS Preview (works for both modes)
        # ================================================================
        with st.expander(tr("tts.preview_title"), expanded=False):
            # Preview text input
            preview_text = st.text_input(
                tr("tts.preview_text"),
                value="大家好，这是一段测试语音。",
                placeholder=tr("tts.preview_text_placeholder"),
                key="tts_preview_text"
            )

            # Preview button
            if st.button(tr("tts.preview_button"), key="preview_tts", use_container_width=True):
                with st.spinner(tr("tts.previewing")):
                    try:
                        # Build TTS params based on mode
                        tts_params = {
                            "text": preview_text,
                            "inference_mode": tts_mode
                        }

                        # 试听与最终生成使用同一在线接口，不再传递工作流或克隆音频。
                        tts_params["voice"] = selected_voice
                        tts_params["speed"] = tts_speed

                        audio_path = run_async(pixelle_video.tts(**tts_params))

                        # Play the audio
                        if audio_path:
                            st.success(tr("tts.preview_success"))
                            if os.path.exists(audio_path):
                                st.audio(audio_path, format="audio/mp3")
                            elif audio_path.startswith('http'):
                                st.audio(audio_path)
                            else:
                                st.error("Failed to generate preview audio")

                            # Show file path
                            st.caption(f"📁 {audio_path}")
                        else:
                            st.error("Failed to generate preview audio")
                    except Exception as e:
                        st.error(tr("tts.preview_failed", error=str(e)))
                        logger.exception(e)

    # ====================================================================
    # Storyboard Template Section
    # ====================================================================

    with st.container(border=True):
        st.markdown(f"**{tr('section.template')}**")

        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            st.markdown(tr("template.what"))
            st.markdown(f"**{tr('help.how')}**")
            st.markdown(tr("template.how"))

        # Template preview link (based on language)
        current_lang = get_language()

        # Import template utilities
        from pixelle_video.utils.template_util import (
            get_template_type,
            get_templates_grouped_by_size_and_type,
        )

        # Template type selector
        st.markdown(f"**{tr('template.type_selector')}**")

        template_type_options = {
            'static': tr('template.type.static'),
            'image': tr('template.type.image'),
            'video': tr('template.type.video'),
        }

        # Radio buttons in horizontal layout
        selected_template_type = st.radio(
            tr('template.type_selector'),
            options=list(template_type_options.keys()),
            format_func=lambda x: template_type_options[x],
            index=1,  # Default to 'image'
            key="template_type_selector",
            label_visibility="collapsed",
            horizontal=True
        )

        # Display hint based on selected type (below radio buttons)
        if selected_template_type == 'static':
            st.info(tr('template.type.static_hint'))
        elif selected_template_type == 'image':
            st.info(tr('template.type.image_hint'))
        elif selected_template_type == 'video':
            st.info(tr('template.type.video_hint'))

        # Get templates grouped by size, filtered by selected type
        grouped_templates = get_templates_grouped_by_size_and_type(selected_template_type)

        if not grouped_templates:
            st.warning(f"No {template_type_options[selected_template_type]} templates found. Please select a different type or add templates.")
            st.stop()

        # Build orientation i18n mapping
        ORIENTATION_I18N = {
            'portrait': tr('orientation.portrait'),
            'landscape': tr('orientation.landscape'),
            'square': tr('orientation.square')
        }

        # Get default template from config
        template_config = pixelle_video.config.get("template", {})
        config_default_template = template_config.get("default_template", "1080x1920/image_default.html")

        # Backward compatibility
        if config_default_template == "1080x1920/default.html":
            config_default_template = "1080x1920/image_default.html"

        # Determine type-specific default template
        type_default_templates = {
            'static': '1080x1920/static_default.html',
            'image': '1080x1920/image_default.html',
            'video': '1080x1920/video_default.html',
        }
        type_specific_default = type_default_templates.get(selected_template_type, config_default_template)

        # Initialize selected template in session state if not exists
        if 'selected_template' not in st.session_state:
            st.session_state['selected_template'] = type_specific_default

        # Track last selected template type to detect type changes
        last_template_type = st.session_state.get('last_template_type', None)
        if last_template_type != selected_template_type:
            # Template type changed, reset to type-specific default
            st.session_state['selected_template'] = type_specific_default
            st.session_state['last_template_type'] = selected_template_type

        # Collect size groups and prepare tabs
        size_groups = []
        size_labels = []

        for size, templates in grouped_templates.items():
            if not templates:
                continue

            # Filter templates to only include those with proper naming convention
            # Only show templates starting with static_, image_, or video_
            valid_templates = []
            for template in templates:
                template_name = template.display_info.name
                if template_name.startswith(('static_', 'image_', 'video_')):
                    valid_templates.append(template)

            # Skip if no valid templates after filtering
            if not valid_templates:
                continue

            # Separate templates into two groups: with preview and without preview
            templates_with_preview = []
            templates_without_preview = []

            for template in valid_templates:
                preview_path = get_template_preview_path(template.template_path, current_lang)
                if preview_path and os.path.exists(preview_path):
                    templates_with_preview.append(template)
                else:
                    templates_without_preview.append(template)

            # Skip this group if no templates at all
            if not templates_with_preview and not templates_without_preview:
                continue

            # Combine: templates with preview first, then without preview
            all_templates = templates_with_preview + templates_without_preview

            # Get orientation from first template in group
            orientation = ORIENTATION_I18N.get(
                all_templates[0].display_info.orientation,
                all_templates[0].display_info.orientation
            )
            width = all_templates[0].display_info.width
            height = all_templates[0].display_info.height

            # Create tab label
            tab_label = f"{orientation} {width}×{height}"
            size_labels.append(tab_label)
            size_groups.append(all_templates)

        # Create tabs for each size group (wrapped in expander)
        # 模板库保留完整入口，默认收起以缩短编辑面板。
        with st.expander(tr("template.gallery_view"), expanded=False):
            if size_groups:
                tabs = st.tabs(size_labels)

                for tab, all_templates in zip(tabs, size_groups):
                    with tab:
                        # Create grid layout (5 columns)
                        num_cols = 5
                        cols = st.columns(num_cols)

                        for idx, template in enumerate(all_templates):
                            col_idx = idx % num_cols
                            with cols[col_idx]:
                                # Get preview image path
                                preview_path = get_template_preview_path(template.template_path, current_lang)

                                # Display preview image or placeholder
                                if preview_path and os.path.exists(preview_path):
                                    st.image(preview_path, use_container_width=True)
                                else:
                                    # Placeholder for templates without preview (fixed height, compact layout)
                                    st.markdown(
                                        f"""
                                        <div style="
                                            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                            height: 150px;
                                            display: flex;
                                            align-items: center;
                                            justify-content: center;
                                            text-align: center;
                                            border-radius: 8px;
                                            color: white;
                                            margin-bottom: 15px;
                                            padding: 10px;
                                        ">
                                            <div style="
                                                font-size: 14px;
                                                opacity: 0.95;
                                                overflow: hidden;
                                                text-overflow: ellipsis;
                                                display: -webkit-box;
                                                -webkit-line-clamp: 5;
                                                -webkit-box-orient: vertical;
                                                word-break: break-all;
                                            ">{template.display_info.name}</div>
                                        </div>
                                        """,
                                        unsafe_allow_html=True
                                    )

                                # Select button (unified label)
                                is_selected = (st.session_state['selected_template'] == template.template_path)
                                button_label = f"{tr('template.selected')}" if is_selected else tr('template.select_button')
                                button_type = "primary" if is_selected else "secondary"

                                if st.button(
                                    button_label,
                                    key=f"template_{template.template_path}",
                                    use_container_width=True,
                                    type=button_type,
                                ):
                                    st.session_state['selected_template'] = template.template_path
                                    st.rerun()
            else:
                st.warning(tr("template.no_templates_with_preview"))

            # Display selected template name (inside expander, below tabs)
            frame_template = st.session_state['selected_template']

            # Find the selected template's display name
            selected_template_name = None
            for size, templates in grouped_templates.items():
                for template in templates:
                    if template.template_path == frame_template:
                        selected_template_name = template.display_info.name
                        break
                if selected_template_name:
                    break

        if selected_template_name:
            st.info(f"📋 {tr('template.selected_template')}: **{selected_template_name}**")


        # Display video size from template
        from pixelle_video.utils.template_util import parse_template_size
        video_width, video_height = parse_template_size(frame_template)
        st.caption(tr("template.video_size_info", width=video_width, height=video_height))

        # Custom template parameters (for video generation)
        from pixelle_video.services.frame_html import HTMLFrameGenerator

        # Resolve template path to support both data/templates/ and templates/
        from pixelle_video.utils.template_util import resolve_template_path
        template_path_for_params = resolve_template_path(frame_template)
        generator_for_params = HTMLFrameGenerator(template_path_for_params)
        custom_params_for_video = generator_for_params.parse_template_parameters()
        # 必须在控件创建前迁移，否则 Streamlit 仍会优先使用旧会话默认值。
        migrate_template_branding(st.session_state, custom_params_for_video, tr("template.preview_default_text"))

        # Get media size from template (for image/video generation)
        media_width, media_height = generator_for_params.get_media_size()
        st.session_state['template_media_width'] = media_width
        st.session_state['template_media_height'] = media_height

        # Detect template media type

        template_name = Path(frame_template).name
        template_media_type = get_template_type(template_name)
        template_requires_media = (template_media_type in ["image", "video"])

        # Store in session state for workflow filtering
        st.session_state['template_media_type'] = template_media_type
        st.session_state['template_requires_media'] = template_requires_media

        # Backward compatibility
        st.session_state['template_requires_image'] = (template_media_type == "image")

        custom_values_for_video = {}
        if custom_params_for_video:
            st.markdown("📝 " + tr("template.custom_parameters"))

            # Render custom parameter inputs in 2 columns
            video_custom_col1, video_custom_col2 = st.columns(2)

            param_items = list(custom_params_for_video.items())
            mid_point = (len(param_items) + 1) // 2

            # Left column parameters
            with video_custom_col1:
                for param_name, config in param_items[:mid_point]:
                    param_type = config['type']
                    default = config['default']
                    label = config['label']

                    if param_type == 'text':
                        custom_values_for_video[param_name] = st.text_input(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'number':
                        custom_values_for_video[param_name] = st.number_input(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'color':
                        custom_values_for_video[param_name] = st.color_picker(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'bool':
                        custom_values_for_video[param_name] = st.checkbox(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )

            # Right column parameters
            with video_custom_col2:
                for param_name, config in param_items[mid_point:]:
                    param_type = config['type']
                    default = config['default']
                    label = config['label']

                    if param_type == 'text':
                        custom_values_for_video[param_name] = st.text_input(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'number':
                        custom_values_for_video[param_name] = st.number_input(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'color':
                        custom_values_for_video[param_name] = st.color_picker(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )
                    elif param_type == 'bool':
                        custom_values_for_video[param_name] = st.checkbox(
                            label,
                            value=default,
                            key=f"video_custom_{param_name}"
                        )

        # Template preview expander
        with st.expander(tr("template.preview_title"), expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                preview_title = st.text_input(
                    tr("template.preview_param_title"),
                    value=tr("template.preview_default_title"),
                    key="preview_title"
                )
                preview_image = st.text_input(
                    tr("template.preview_param_image"),
                    value="resources/example.png",
                    help=tr("template.preview_image_help"),
                    key="preview_image"
                )

            with col2:
                preview_text = st.text_area(
                    tr("template.preview_param_text"),
                    value=tr("template.preview_default_text"),
                    height=100,
                    key="preview_text"
                )

            # Info: Size is auto-determined from template
            from pixelle_video.utils.template_util import parse_template_size, resolve_template_path
            template_width, template_height = parse_template_size(resolve_template_path(frame_template))
            st.info(f"📐 {tr('template.size_info')}: {template_width} × {template_height}")

            # Preview button
            if st.button(tr("template.preview_button"), key="btn_preview_template", use_container_width=True):
                with st.spinner(tr("template.preview_generating")):
                    try:
                        from pixelle_video.services.frame_html import HTMLFrameGenerator

                        # Use the currently selected template (size is auto-parsed)
                        from pixelle_video.utils.template_util import resolve_template_path
                        template_path = resolve_template_path(frame_template)
                        generator = HTMLFrameGenerator(template_path)

                        # Build ext dict with auto-injected parameters (same as FrameProcessor)
                        ext = {
                            "index": 1,  # Preview uses index 1
                        }

                        # Add custom parameters from user input
                        if custom_values_for_video:
                            ext.update(custom_values_for_video)

                        # Generate preview
                        preview_path = run_async(generator.generate_frame(
                            title=preview_title,
                            text=preview_text,
                            image=preview_image,
                            ext=ext
                        ))

                        # Display preview
                        if preview_path:
                            st.success(tr("template.preview_success"))
                            st.image(
                                preview_path,
                                caption=tr("template.preview_caption", template=frame_template),
                            )

                            # Show file path
                            st.caption(f"📁 {preview_path}")
                        else:
                            st.error("Failed to generate preview")

                    except Exception as e:
                        st.error(tr("template.preview_failed", error=str(e)))
                        logger.exception(e)

    # ====================================================================
    # Media Generation Section (conditional based on template)
    # ====================================================================
    # Check if current template requires media generation
    template_media_type = st.session_state.get('template_media_type', 'image')
    template_requires_media = st.session_state.get('template_requires_media', True)

    api_video_params = {}

    if template_requires_media:
        comfyui_config = config_manager.get_comfyui_config()
        media_width = st.session_state.get('template_media_width')
        media_height = st.session_state.get('template_media_height')
        media_config_key = "video" if template_media_type == "video" else "image"
        saved_workflow = comfyui_config.get(media_config_key, {}).get("default_workflow") or ""
        workflow_key = None

        with st.container(border=True):
            section_title = tr('section.video') if template_media_type == "video" else tr('section.image')
            st.markdown(f"**{section_title}**")

            # 当前连接的已保存模型目录先与能力适配取交集，再展示对应媒体类型。
            st.caption(workflow_source_help())
            source_key = "standard_video_workflow_source" if template_media_type == "video" else "standard_image_workflow_source"
            st.session_state[source_key] = "api"
            if template_media_type == "video":
                workflows = list_api_media_workflows(
                    pixelle_video, "video", required_adapter_abilities=["text_to_video"], verified_only=True,
                )
            else:
                workflows = list_api_media_workflows(pixelle_video, "image")

            # Build options for selectbox
            # 控件保存展示名称，生成参数使用注册表中的 API 标识。
            workflow_options = [wf["display_name"] for wf in workflows]
            workflow_keys = [wf["key"] for wf in workflows]

            # 只有仍在当前连接可用目录中的历史选择才可恢复。
            default_workflow_index = 0

            # If user has a saved preference in config, try to match it
            if saved_workflow and saved_workflow in workflow_keys:
                default_workflow_index = workflow_keys.index(saved_workflow)

            if st.session_state.get(f"{source_key}_select") not in workflow_options:
                st.session_state.pop(f"{source_key}_select", None)
            workflow_display = st.selectbox(
                "API 模型" if get_language() == "zh_CN" else "API model",
                workflow_options if workflow_options else ["暂无可用 API 模型" if get_language() == "zh_CN" else "No API models available"],
                index=default_workflow_index,
                label_visibility="visible",
                key=f"{source_key}_select",
                disabled=not workflow_options,
                help=workflow_select_help(),
            )

            # 空模型列表保留 None，由生成入口阻止调用，不能走旧配置的默认工作流。
            if workflow_options:
                workflow_selected_index = workflow_options.index(workflow_display)
                workflow_key = workflow_keys[workflow_selected_index]
                workflow_info = workflows[workflow_selected_index]
            else:
                workflow_key = None
                workflow_info = None
                st.warning(
                    "暂无适用于当前模板的 API 模型。请在系统配置中加载模型并保存；此处只显示目录中已适配当前功能的型号。"
                    if get_language() == "zh_CN"
                    else "No API model is available for this template. Load and save models in Settings; only catalog entries adapted for this feature are shown here."
                )

            # Display media size info (read-only)
            if template_media_type == "video":
                size_info_text = tr('style.video_size_info', width=media_width, height=media_height)
            else:
                size_info_text = tr('style.image_size_info', width=media_width, height=media_height)
            st.info(f"📐 {size_info_text}")

            if template_media_type == "video" and media_width and media_height:
                default_video_ratio = "1:1" if media_width == media_height else ("9:16" if media_height > media_width else "16:9")
            else:
                default_video_ratio = "9:16"

            if template_media_type == "video" and is_api_workflow(workflow_key):
                api_video_params = render_api_video_controls(
                    workflow_info,
                    key_prefix="standard_video",
                    default_duration=5,
                    allow_audio_driven=False,
                    show_duration=False,
                    default_ratio=default_video_ratio,
                )

            # Prompt prefix input
            # Get current prompt_prefix from config (based on media type)
            current_prefix = comfyui_config.get(media_config_key, {}).get("prompt_prefix", "")

            # Prompt prefix input (temporary, not saved to config)
            prompt_prefix = st.text_area(
                tr('style.prompt_prefix'),
                value=current_prefix,
                placeholder=tr("style.prompt_prefix_placeholder"),
                height=80,
                label_visibility="visible",
                help=tr("style.prompt_prefix_help")
            )

            # Media preview expander
            preview_title = tr("style.video_preview_title") if template_media_type == "video" else tr("style.preview_title")
            with st.expander(preview_title, expanded=False):
                # Test prompt input
                test_prompt_label = tr("style.test_video_prompt") if template_media_type == "video" else tr("style.test_prompt")
                test_prompt_value = "a peaceful lake, gentle camera movement" if template_media_type == "video" else "a dog"

                test_prompt = st.text_input(
                    test_prompt_label,
                    value=test_prompt_value,
                    help=tr("style.test_prompt_help"),
                    key="style_test_prompt"
                )

                # Preview button
                preview_button_label = tr("style.video_preview") if template_media_type == "video" else tr("style.preview")
                if st.button(preview_button_label, key="preview_style", use_container_width=True):
                    if not is_api_workflow(workflow_key):
                        st.error(
                            "请先选择可用的 API 模型。"
                            if get_language() == "zh_CN"
                            else "Please select an available API model first."
                        )
                        st.stop()
                    previewing_text = tr("style.video_previewing") if template_media_type == "video" else tr("style.previewing")
                    with st.spinner(previewing_text):
                        try:
                            from pixelle_video.utils.prompt_helper import build_image_prompt

                            # Build final prompt with prefix
                            final_prompt = build_image_prompt(test_prompt, prompt_prefix)

                            preview_params = dict(api_video_params) if template_media_type == "video" else {}

                            # Generate preview media with the selected source only.
                            media_result = run_async(pixelle_video.media(
                                prompt=final_prompt,
                                workflow=workflow_key,
                                media_type=template_media_type,
                                width=int(media_width),
                                height=int(media_height),
                                duration=5 if template_media_type == "video" else None,
                                **preview_params,
                            ))
                            preview_media_path = media_result.url

                            # Display preview (support both URL and local path)
                            if preview_media_path:
                                success_text = tr("style.video_preview_success") if template_media_type == "video" else tr("style.preview_success")
                                st.success(success_text)

                                if template_media_type == "video":
                                    st.video(preview_media_path)
                                else:
                                    if preview_media_path.startswith('http'):
                                        # URL - use directly
                                        img_html = f'<div class="preview-image"><img src="{preview_media_path}" alt="Style Preview"/></div>'
                                    else:
                                        # Local file - encode as base64
                                        with open(preview_media_path, 'rb') as f:
                                            img_data = base64.b64encode(f.read()).decode()
                                        img_html = f'<div class="preview-image"><img src="data:image/png;base64,{img_data}" alt="Style Preview"/></div>'

                                    st.markdown(img_html, unsafe_allow_html=True)

                                # Show the final prompt used
                                st.info(f"**{tr('style.final_prompt_label')}**\n{final_prompt}")

                                # Show file path
                                st.caption(f"📁 {preview_media_path}")
                            else:
                                st.error(tr("style.preview_failed_general"))
                        except Exception as e:
                            st.error(tr("style.preview_failed", error=str(e)))
                            logger.exception(e)


    else:
        # Template doesn't need images - show simplified message
        with st.container(border=True):
            st.markdown(f"**{tr('section.image')}**")
            st.info("ℹ️ " + tr("image.not_required"))
            st.caption(tr("image.not_required_hint"))

            # Get media size from template (even though not used, for consistency)
            media_width = st.session_state.get('template_media_width')
            media_height = st.session_state.get('template_media_height')

            # Set default values for later use
            workflow_key = None
            prompt_prefix = ""

    # Return all style configuration parameters
    final_media_workflow = workflow_key

    return {
        "tts_inference_mode": tts_mode,
        "tts_voice": selected_voice,
        "tts_speed": tts_speed,
        "tts_workflow": None,
        "ref_audio": None,
        "frame_template": frame_template,
        "template_params": custom_values_for_video if custom_values_for_video else None,
        "media_workflow": final_media_workflow,
        "requires_api_media": bool(template_requires_media),
        "api_video_params": api_video_params if template_media_type == "video" else None,
        "prompt_prefix": prompt_prefix if prompt_prefix else "",
        "media_width": media_width,
        "media_height": media_height
    }
