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
Content input components for web UI (left column)
"""

import streamlit as st

from web.i18n import get_language, tr


def render_content_input():
    """Render content input section (left column) with batch support"""
    # 外层工作台已提供标题与边框，脚本区避免重复嵌套卡片。
    with st.container(border=False, key="studio-script-form"):
        
        # ====================================================================
        # Step 1: Batch mode toggle (highest priority)
        # ====================================================================
        # 固定控件标识，切换界面语言或重排编辑区时保留当前草稿。
        batch_mode = st.checkbox(
            tr("batch.mode_label"),
            value=False,
            help=tr("batch.mode_help"),
            key="quick_create_batch_mode",
        )
        
        if not batch_mode:
            zh = get_language() == "zh_CN"
            # 时长模式只作用于单条创作；批量入口继续沿用原有短片参数。
            length_labels = {
                "short": "短视频" if zh else "Short video",
                "long": "长视频 · 5–10 分钟" if zh else "Long video · 5–10 min",
            }
            length_mode = st.radio(
                "成片长度" if zh else "Video length",
                options=list(length_labels),
                format_func=lambda value: length_labels[value],
                key="quick_create_length_mode",
                horizontal=True,
            )
            target_duration = None
            narration_language = None
            if length_mode == "long":
                duration_col, language_col = st.columns(2)
                duration_labels = {300: "5 分钟", 480: "8 分钟", 600: "10 分钟"} if zh else {
                    300: "5 minutes", 480: "8 minutes", 600: "10 minutes",
                }
                with duration_col:
                    target_duration = st.selectbox(
                        "目标时长" if zh else "Target duration",
                        options=list(duration_labels),
                        format_func=lambda value: duration_labels[value],
                        key="quick_create_target_duration",
                    )
                language_labels = {"zh": "中文", "en": "English"}
                with language_col:
                    narration_language = st.selectbox(
                        "旁白语言" if zh else "Narration language",
                        options=list(language_labels),
                        index=0 if zh else 1,
                        format_func=lambda value: language_labels[value],
                        key="quick_create_narration_language",
                    )
                st.info(
                    "自动规划章节和镜头，逐段配音与生成画面，再合成为一条长视频。目标时长为规划值，实际长度由旁白和语速决定。"
                    if zh else "Plan chapters and scenes, produce narration and visuals, then assemble one video. The target is an estimate; narration and speech rate determine the actual duration."
                )
                st.caption(
                    "旁白语言用于生成文案，请在第 2 步选择对应语言的配音音色。"
                    if zh else "Narration language controls the script. Choose a matching voice in step 2."
                )
            # ================================================================
            # Single task mode (original logic, unchanged)
            # ================================================================
            # Processing mode selection
            # Streamlit 的 radio 会把翻译后的选项计入身份；重建时沿用当前业务值。
            mode_options = ["generate", "fixed"]
            # 固定本次渲染的显示名，后续控件序列化不会借用其他线程的语言上下文。
            mode_labels = {value: tr(f"mode.{value}") for value in mode_options}
            current_mode = st.session_state.get("quick_create_mode", "generate")
            mode = st.radio(
                "Processing Mode",
                mode_options,
                index=mode_options.index(current_mode) if current_mode in mode_options else 0,
                horizontal=True,
                format_func=lambda x: mode_labels[x],
                label_visibility="collapsed",
                key="quick_create_mode",
            )
            
            # Text input (unified for both modes)
            text_placeholder = tr("input.topic_placeholder") if mode == "generate" else tr("input.content_placeholder")
            text_height = 120 if mode == "generate" else 200
            text_help = tr("input.text_help_generate") if mode == "generate" else tr("input.text_help_fixed")
            
            text = st.text_area(
                tr("input.text"),
                placeholder=text_placeholder,
                height=text_height,
                help=text_help,
                key="quick_create_text",
            )
            
            # Split mode selector (only show in fixed mode)
            if mode == "fixed":
                split_mode_options = {
                    "paragraph": tr("split.mode_paragraph"),
                    "line": tr("split.mode_line"),
                    "sentence": tr("split.mode_sentence"),
                }
                split_mode = st.selectbox(
                    tr("split.mode_label"),
                    options=list(split_mode_options.keys()),
                    format_func=lambda x: split_mode_options[x],
                    index=0,  # Default to paragraph mode
                    help=tr("split.mode_help"),
                    key="quick_create_split_mode",
                )
            else:
                split_mode = "paragraph"  # Default for generate mode (not used)
            
            # Title input (optional for both modes)
            title = st.text_input(
                tr("input.title"),
                placeholder=tr("input.title_placeholder"),
                help=tr("input.title_help"),
                key="quick_create_title",
            )
            
            # Number of scenes (only show in generate mode)
            if mode == "generate" and length_mode == "short":
                n_scenes = st.slider(
                    tr("video.frames"),
                    min_value=3,
                    max_value=30,
                    value=5,
                    help=tr("video.frames_help"),
                    label_visibility="collapsed",
                    key="quick_create_n_scenes",
                )
                st.caption(tr("video.frames_label", n=n_scenes))
            elif length_mode == "long":
                # 长片镜头预算由后端按时长与语速统一计算，不再受短片 30 镜上限限制。
                n_scenes = 5
                st.caption(
                    ("章节与镜头数会自动规划，第 3 步可查看生成预算。" if mode == "generate"
                     else "使用完整原稿并自动拆分长段落；不会补写或重复文案来凑时长。第 3 步可查看预计长度。")
                    if zh else
                    ("Chapters and scenes are planned automatically. Review the production estimate in step 3."
                     if mode == "generate" else "Your complete script is preserved and long sections are split. Text is never extended or repeated to reach the target. Review the estimated duration in step 3.")
                )
            else:
                # Fixed mode: n_scenes is ignored, set default value
                n_scenes = 5
                st.info(tr("video.frames_fixed_mode_hint"))
            
            params = {
                "batch_mode": False,
                "mode": mode,
                "text": text,
                "title": title,
                "n_scenes": n_scenes,
                "split_mode": split_mode
            }
            if target_duration is not None:
                params.update(
                    target_duration_seconds=target_duration,
                    narration_language=narration_language,
                )
            return params
        
        else:
            # ================================================================
            # Batch mode (simplified YAGNI version)
            # ================================================================
            st.markdown(f"**{tr('batch.section_title')}**")
            
            # Batch rules info
            st.info(f"""
**{tr('batch.rules_title')}**
- ✅ {tr('batch.rule_1')}
- ✅ {tr('batch.rule_2')}
- ✅ {tr('batch.rule_3')}
            """)
            
            # Batch topics input
            # 批量主题与单条脚本使用不同标识，避免两种输入互相覆盖。
            text_input = st.text_area(
                tr("batch.topics_label"),
                height=300,
                placeholder=tr("batch.topics_placeholder"),
                help=tr("batch.topics_help"),
                key="quick_create_batch_topics",
            )
            
            # Split topics by newline
            if text_input:
                # Simple split by newline, filter empty lines
                topics = [
                    line.strip() 
                    for line in text_input.strip().split('\n') 
                    if line.strip()
                ]
                
                if topics:
                    # Check count limit
                    if len(topics) > 100:
                        st.error(tr("batch.count_error", count=len(topics)))
                        topics = []
                    else:
                        st.success(tr("batch.count_success", count=len(topics)))
                        
                        # Preview topics list
                        with st.expander(tr("batch.preview_title"), expanded=False):
                            for i, topic in enumerate(topics, 1):
                                st.markdown(f"`{i}.` {topic}")
                else:
                    topics = []
            else:
                topics = []
            
            st.markdown("---")
            
            # Title prefix (optional)
            title_prefix = st.text_input(
                tr("batch.title_prefix_label"),
                placeholder=tr("batch.title_prefix_placeholder"),
                help=tr("batch.title_prefix_help"),
                key="quick_create_batch_title_prefix",
            )
            
            # Number of scenes (unified for all videos)
            n_scenes = st.slider(
                tr("batch.n_scenes_label"),
                min_value=3,
                max_value=30,
                value=5,
                help=tr("batch.n_scenes_help"),
                key="quick_create_batch_n_scenes",
            )
            st.caption(tr("batch.n_scenes_caption", n=n_scenes))
            
            # Config info
            st.info(f"📌 {tr('batch.config_info')}")
            
            return {
                "batch_mode": True,
                "topics": topics,
                "mode": "generate",  # Fixed to AI generate content
                "title_prefix": title_prefix,
                "n_scenes": n_scenes,
            }


def render_bgm_section(key_prefix=""):
    """Render BGM selection section"""
    with st.container(border=True):
        st.markdown(f"**{tr('section.bgm')}**")
        
        with st.expander(tr("help.feature_description"), expanded=False):
            st.markdown(f"**{tr('help.what')}**")
            st.markdown(tr("bgm.what"))
            st.markdown(f"**{tr('help.how')}**")
            st.markdown(tr("bgm.how"))
        
        # Dynamically scan bgm folder for music files (merged from bgm/ and data/bgm/)
        from pixelle_video.utils.os_util import list_resource_files
        
        try:
            all_files = list_resource_files("bgm")
            # Filter to audio files only
            audio_extensions = ('.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg')
            bgm_files = sorted([f for f in all_files if f.lower().endswith(audio_extensions)])
        except Exception as e:
            st.warning(f"Failed to load BGM files: {e}")
            bgm_files = []
        
        # Add special "None" option
        bgm_options = [tr("bgm.none")] + bgm_files
        
        # Default to "default.mp3" if exists, otherwise first option
        default_index = 0
        if "default.mp3" in bgm_files:
            default_index = bgm_options.index("default.mp3")
        
        bgm_choice = st.selectbox(
            "BGM",
            bgm_options,
            index=default_index,
            label_visibility="collapsed",
            key=f"{key_prefix}bgm_selector"
        )
        
        # BGM volume slider (only show when BGM is selected)
        if bgm_choice != tr("bgm.none"):
            bgm_volume = st.slider(
                tr("bgm.volume"),
                min_value=0.0,
                max_value=0.5,
                value=0.2,
                step=0.01,
                format="%.2f",
                key=f"{key_prefix}bgm_volume_slider",
                help=tr("bgm.volume_help")
            )
        else:
            bgm_volume = 0.2  # Default value when no BGM selected
        
        # BGM preview button (only if BGM is not "None")
        if bgm_choice != tr("bgm.none"):
            if st.button(tr("bgm.preview"), key=f"{key_prefix}preview_bgm", use_container_width=True):
                from pixelle_video.utils.os_util import get_resource_path, resource_exists
                try:
                    if resource_exists("bgm", bgm_choice):
                        bgm_file_path = get_resource_path("bgm", bgm_choice)
                        st.audio(bgm_file_path)
                    else:
                        st.error(tr("bgm.preview_failed", file=bgm_choice))
                except Exception as e:
                    st.error(f"{tr('bgm.preview_failed', file=bgm_choice)}: {e}")
        
        # Use full filename for bgm_path (including extension)
        bgm_path = None if bgm_choice == tr("bgm.none") else bgm_choice
    
    return {
        "bgm_path": bgm_path,
        "bgm_volume": bgm_volume
    }
