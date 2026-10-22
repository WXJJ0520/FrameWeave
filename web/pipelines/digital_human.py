import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.utils.os_util import create_task_output_dir
from web.components.digital_tts_config import render_style_config
from web.i18n import get_language, tr
from web.pipelines.api_workflows import (
    list_api_media_workflows,
    render_api_video_controls,
    workflow_select_help,
)
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.utils.async_helpers import run_async
from web.utils.generation_feedback import (
    GenerationProgress,
    MissingGeneratedVideoError,
    build_generation_failure,
)
from web.utils.history_persistence import save_web_generation_history


def list_digital_human_api_models(pixelle_video: Any) -> list[dict]:
    """参考音频是当前口播流程的必要输入，不能把原生音频输出当作支持输入。"""
    candidates = list_api_media_workflows(
        pixelle_video,
        "video",
        required_adapter_abilities=["digital_human"],
        verified_only=True,
    )
    return [
        model
        for model in candidates
        if "voice_reference" in (model.get("adapter_ability_types") or [])
        and {"image", "audio"}.issubset(
            set((model.get("capabilities") or {}).get("adapter_input_modalities") or [])
        )
    ]


class DigitalHumanPipelineUI(PipelineUI):
    """
    UI for the Digital_Human Video Generation Pipeline.
    Generates videos from user-provided assets (images&videos&audio).
    """

    name = "digital_human"
    icon = "🤖"

    @property
    def display_name(self):
        return tr("pipeline.digital_human.name")

    @property
    def description(self):
        return tr("pipeline.digital_human.description")

    def render(self, pixelle_video: Any):
        from web.components.creation_flow import CreationFlow

        zh = get_language() == "zh_CN"
        flow = CreationFlow(
            self.name,
            [
                ("人物与文案", "上传人物参考图，选择口播模式并填写内容。")
                if zh
                else (
                    "Character & script",
                    "Upload a character reference, choose a mode and add your script.",
                ),
                ("模型与配音", "选择口播 API 模型，设置参考声音与视频参数。")
                if zh
                else (
                    "Model & voice",
                    "Choose a talking-video API, reference voice and video settings.",
                ),
                ("预览与生成", "确认人物和文案后生成，在这里查看与下载结果。")
                if zh
                else (
                    "Preview & generate",
                    "Generate with your character and script, then preview and download.",
                ),
            ],
        )
        flow.render_header()
        # 所有输入步骤固定挂载；切到参数页仍保留人物、商品上传与模式内的文案。
        with flow.step(0):
            character_column, script_column = st.columns(2)
            with character_column:
                asset_params = self.render_digital_human_input(border=False)
            with script_column:
                mode_params = self.render_digital_human_mode(
                    asset_params["character_assets"], border=False
                )
        with flow.step(1):
            model_column, voice_column = st.columns(2)
            with model_column:
                workflow_path = self.workflow_path_config(pixelle_video, border=False)
            with voice_column:
                style_params = render_style_config(pixelle_video)
        with flow.step(2):
            if flow.is_active(2):
                video_params = {
                    **mode_params,
                    **asset_params,
                    **style_params,
                    "workflow_path": workflow_path,
                }
                self._render_output_preview(pixelle_video, video_params)
        flow.render_navigation()

    def render_digital_human_input(self, *, border: bool = True) -> dict:
        """Render digital human character image upload section"""
        with st.container(border=border):
            st.markdown(f"**{tr('digital_human.section.character_assets')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("digital_human.assets.character_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("digital_human.assets.how"))

            # File uploader for multiple files
            uploaded_files = st.file_uploader(
                tr("digital_human.assets.upload"),
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help=tr("digital_human.assets.upload_help"),
                key="character_files",
            )

            # Save uploaded files to temp directory with unique session ID
            from web.components.creation_uploads import persist_uploaded_files

            # 内容不变时复用同一本地路径，避免来回切步骤重复写入素材。
            character_asset_paths = persist_uploaded_files(
                uploaded_files or [], key="digital_human_characters"
            )
            if uploaded_files:
                st.success(tr("digital_human.assets.character_sucess"))

                # Preview uploaded assets
                with st.expander(tr("digital_human.assets.preview"), expanded=True):
                    # Show in a grid (3 columns)
                    cols = st.columns(3)
                    for i, (file, path) in enumerate(zip(uploaded_files, character_asset_paths)):
                        with cols[i % 3]:
                            # Check if image
                            ext = Path(path).suffix.lower()
                            if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                st.image(file, caption=file.name, use_container_width=True)
            else:
                st.info(tr("digital_human.assets.character_empty_hint"))

            return {"character_assets": character_asset_paths}

    def workflow_path_config(self, pixelle_video: Any, *, border: bool = True) -> dict:
        """人物与商品图片直接作为参考输入，只列出实际支持参考声音的 API。"""
        with st.container(border=border):
            zh = get_language() == "zh_CN"
            st.markdown("**口播视频 API**" if zh else "**Talking-video API**")
            st.caption(
                "① 上传人物参考图 → ② 合成参考配音 → ③ 调用口播视频 API。商品模式可同时上传商品图。"
                if zh
                else "1. Upload a character reference → 2. Synthesize reference speech → 3. Generate with a talking-video API. Product mode also accepts a product image."
            )
            st.info(
                "参考声音用于提供音色与口播参考，不保证逐字复现文案或精准口型同步。普通图生视频模型不会作为数字人模型展示。"
                if zh
                else "Reference speech guides the voice and delivery; exact script reproduction and lip synchronization are not guaranteed. Ordinary image-to-video models are excluded."
            )
            # 清除旧来源及图片工作流值，避免已有会话保留不可见的工作流回退。
            st.session_state["digital_human_image_service_source"] = "api"
            st.session_state["digital_human_video_service_source"] = "api"
            st.session_state.pop("digital_human_image_workflow", None)
            video_workflows = list_digital_human_api_models(pixelle_video)
            video_options = [model["display_name"] for model in video_workflows]
            if st.session_state.get("digital_human_video_workflow") not in video_options:
                st.session_state.pop("digital_human_video_workflow", None)
            if not video_workflows:
                st.warning(
                    "当前目录没有同时支持人物参考图与参考声音的已接入型号。请到系统配置加载并保存视频服务的模型目录。"
                    if zh
                    else "Your catalog contains no integrated model supporting both a character image and reference voice. Load and save the video provider's model catalog in Settings."
                )
            selected_name = st.selectbox(
                "API 口播模型" if zh else "Talking-video API model",
                video_options or ["暂无可用 API 模型" if zh else "No API model available"],
                key="digital_human_video_workflow",
                disabled=not video_options,
                help=workflow_select_help(),
            )
            model = video_workflows[video_options.index(selected_name)] if video_options else None
            return {
                "api_video_workflow": model["key"] if model else None,
                "api_video_params": render_api_video_controls(
                    model,
                    key_prefix="digital_human",
                    default_duration=5,
                    default_ratio="9:16",
                )
                if model
                else {},
            }

    def render_digital_human_mode(
        self, character_asset_paths: list, *, border: bool = True
    ) -> dict:
        with st.container(border=border):
            st.markdown(f"**{tr('digital_human.section.select_mode')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("digital_human.assets.mode_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("digital_human.assets.select_how"))

            mode = st.radio(
                "Processing Mode",
                ["digital", "customize"],
                horizontal=True,
                format_func=lambda x: tr(f"mode.{x}"),
                label_visibility="collapsed",
                key="mode_selection",
            )

            # Text input (unified for both modes)
            text_placeholder = (
                tr("digital_human.input.topic_placeholder")
                if mode == "digital"
                else tr("digital_human.input.content_placeholder")
            )
            text_height = 120 if mode == "digital" else 200
            text_help = (
                tr("input.text_help_digital") if mode == "digital" else tr("input.text_help_fixed")
            )

            if mode == "digital":
                # File uploader for multiple files
                uploaded_files = st.file_uploader(
                    tr("digital_human.assets.upload"),
                    type=["jpg", "jpeg", "png", "webp"],
                    accept_multiple_files=True,
                    help=tr("digital_human.assets.upload_help"),
                    key="digital_files",
                )

                # Save uploaded files to temp directory with unique session ID
                from web.components.creation_uploads import persist_uploaded_files

                # 内容不变时复用同一本地路径，避免来回切步骤重复写入素材。
                goods_asset_paths = persist_uploaded_files(
                    uploaded_files or [], key="digital_human_products"
                )
                if uploaded_files:
                    st.success(tr("digital_human.assets.goods_sucess"))

                    # Preview uploaded assets
                    with st.expander(tr("digital_human.assets.preview"), expanded=True):
                        # Show in a grid (3 columns)
                        cols = st.columns(3)
                        for i, (file, path) in enumerate(zip(uploaded_files, goods_asset_paths)):
                            with cols[i % 3]:
                                # Check if image
                                ext = Path(path).suffix.lower()
                                if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                    st.image(file, caption=file.name, use_container_width=True)
                else:
                    st.info(tr("digital_human.assets.goods_empty_hint"))
                    # Text input
                goods_text = st.text_area(
                    tr("digital_human.input_text"),
                    placeholder=text_placeholder,
                    height=text_height,
                    help=text_help,
                    key="digital_box",
                )

                goods_title = st.text_input(
                    tr("digital_human.goods_title"),
                    placeholder=tr("digital_human.goods_title_placeholder"),
                    help=tr("digital_human.goods_title_help"),
                    key="goods_title",
                )

                return {
                    "character_assets": character_asset_paths,
                    "goods_title": goods_title,
                    "goods_assets": goods_asset_paths,
                    "goods_text": goods_text,
                    "mode": mode,
                }

            else:
                goods_text = st.text_area(
                    tr("digital_human.customize_text"),
                    placeholder=text_placeholder,
                    height=text_height,
                    help=text_help,
                    key="customize_box",
                )

                return {
                    "character_assets": character_asset_paths,
                    "goods_text": goods_text,
                    "mode": mode,
                }

    def _render_output_preview(self, pixelle_video: Any, video_params: dict):
        """Render output preview section"""
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            # 结果与按钮点击解耦：返回前一步再回来时，仍能预览和下载上次成品。
            result_area = st.empty()
            with result_area.container():
                self._render_saved_result()

            # Get input data
            character_assets = video_params.get("character_assets", [])
            goods_assets = video_params.get("goods_assets", [])
            goods_title = video_params.get("goods_title", "")
            goods_text = video_params.get("goods_text", "")
            mode = video_params.get("mode")
            # 不记录整份输入；远程参考素材或异常可能带有临时访问令牌。

            # 旧会话中的工作流路径不能触发任何生成服务，先校验实际 API 能力。
            selected_model = (video_params.get("workflow_path") or {}).get("api_video_workflow")
            if not any(
                model["key"] == selected_model
                for model in list_digital_human_api_models(pixelle_video)
            ):
                st.warning(
                    "请选择支持人物参考图和参考声音的 API 口播模型。"
                    if get_language() == "zh_CN"
                    else "Select a talking-video API with character-image and voice-reference support."
                )
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="digital_human_api_unavailable",
                )
                return
            needs_script = mode == "digital" and not goods_text.strip()
            if needs_script and not config_manager.validate():
                st.warning(tr("settings.not_configured"))

            # Validation
            if not character_assets:
                st.info(tr("digital_human.assets.character_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="digital_human_generate_disabled",
                )
                return

            if mode == "digital" and not goods_assets:
                st.info(tr("digital_human.assets.goods_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="digital_human_goods_vaiidation",
                )
                return

            if mode == "digital" and not (goods_text or goods_title):
                st.info(tr("digital_human.assets.digital_mode"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="digital_human_digital_disable",
                )
                return

            if mode == "digital" and (goods_text or goods_title):
                st.warning(tr("digital_human.assets.digital_mode_warning"))

            if mode == "customize" and not goods_text:
                st.info(tr("digital_human.assets.customize_mode"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="digital_human_customize_disable",
                )
                return

            # Generate button
            if st.button(
                tr("btn.generate"),
                type="primary",
                use_container_width=True,
                key="digital_human_generate",
            ):
                # Validate
                if needs_script and not config_manager.validate():
                    st.error(tr("settings.not_configured"))
                    # 只结束当前输出区，让公共“上一步”导航仍可渲染。
                    return

                # Show progress
                progress_bar = st.progress(0)
                status_text = st.empty()

                start_time = time.time()
                # 阶段在实际调用前更新，错误提示不依赖进度百分比或异常字符串推断。
                generation_progress = GenerationProgress()

                try:
                    # Define async generation function
                    async def generate_digital_human_video():
                        # 点击后复核模型，缺失能力时直接终止，不尝试旧工作流。
                        if not any(
                            model["key"] == selected_model
                            for model in list_digital_human_api_models(pixelle_video)
                        ):
                            raise ValueError("请选择支持参考声音的 API 口播模型。")
                        task_dir, task_id = create_task_output_dir()
                        workflow_path = video_params["workflow_path"]
                        api_video_workflow = workflow_path.get("api_video_workflow")
                        api_video_params = dict(workflow_path.get("api_video_params") or {})

                        async def generate_tts_reference(text: str) -> str:
                            generation_progress.stage = "speech"
                            audio_path = os.path.join(task_dir, "narration.mp3")
                            # local 是现有服务对在线 Edge TTS API 的兼容枚举；不接受旧工作流参数。
                            tts_kwargs = {
                                "text": text,
                                "output_path": audio_path,
                                "inference_mode": "local",
                                "voice": video_params.get("tts_voice"),
                                "speed": video_params.get("tts_speed"),
                            }

                            await pixelle_video.tts(**tts_kwargs)
                            return audio_path

                        async def generate_api_digital_human(text: str) -> str:
                            status_text.text(tr("progress.step_audio"))
                            progress_bar.progress(25)
                            audio_path = await generate_tts_reference(text)
                            generation_progress.stage = "video"

                            reference_image_paths = [character_assets[0]]
                            if mode == "digital" and goods_assets:
                                reference_image_paths.append(goods_assets[0])

                            subject_prompt = (
                                "参考图1中的人物面对镜头自然口播。"
                                if get_language() == "zh_CN"
                                else "The person in reference image 1 speaks naturally to camera."
                            )
                            if mode == "digital" and goods_assets:
                                subject_prompt += (
                                    "结合参考图2中的商品，生成竖屏商业口播视频。"
                                    if get_language() == "zh_CN"
                                    else "Use the product in reference image 2 and create a vertical product-promotion talking video."
                                )
                            prompt = f"{subject_prompt} 口播文案：{text}"

                            final_video_path = os.path.join(task_dir, "final.mp4")
                            duration = int(api_video_params.pop("duration", 5))
                            media_params = {
                                **api_video_params,
                                "prompt": prompt,
                                "workflow": api_video_workflow,
                                "media_type": "video",
                                "output_path": final_video_path,
                                "duration": duration,
                                "reference_image_paths": reference_image_paths,
                                "reference_audio_path": audio_path,
                                "audio": True,
                                "video_ratio": api_video_params.get("video_ratio", "9:16"),
                            }
                            progress_bar.progress(60)
                            status_text.text(tr("progress.generation"))
                            media_result = await pixelle_video.media(**media_params)
                            progress_bar.progress(100)
                            status_text.text(tr("status.success"))
                            if not getattr(media_result, "url", None):
                                raise MissingGeneratedVideoError()
                            return media_result.url

                        if mode == "customize":
                            generated_text = goods_text
                        elif goods_text and goods_text.strip():
                            generated_text = goods_text
                        else:
                            generation_progress.stage = "script"
                            generated_text = await pixelle_video.llm(
                                prompt=(
                                    f"请为商品“{goods_title}”写一段适合数字人口播短视频的中文推广文案。"
                                    "要求自然、有吸引力，控制在80字以内，只输出文案正文。"
                                ),
                                temperature=0.7,
                                max_tokens=300,
                            )
                        return await generate_api_digital_human(generated_text)

                    # Execute async generation
                    final_video_path = run_async(generate_digital_human_video())
                    generation_progress.stage = "history"
                    run_async(
                        save_web_generation_history(
                            pixelle_video,
                            task_id=Path(final_video_path).parent.name,
                            video_path=final_video_path,
                            pipeline="digital_human",
                            title="数字人口播" if get_language() == "zh_CN" else "Digital Human",
                            input_params={
                                "text": goods_text or goods_title,
                                "mode": mode,
                                "goods_title": goods_title,
                                "goods_text": goods_text,
                                "character_assets": character_assets,
                                "goods_assets": goods_assets,
                                "workflow_path": video_params.get("workflow_path"),
                                "tts_voice": video_params.get("tts_voice"),
                                "tts_speed": video_params.get("tts_speed"),
                                "tts_inference_mode": video_params.get("tts_inference_mode"),
                            },
                        )
                    )

                    generation_progress.stage = "result"
                    total_time = time.time() - start_time
                    progress_bar.progress(100)
                    status_text.text(tr("status.success"))

                    st.session_state[f"creation_result_{self.name}"] = {
                        "path": str(final_video_path),
                        "elapsed": total_time,
                    }
                    with result_area.container():
                        self._render_saved_result(key_suffix="fresh")

                except Exception as e:
                    status_text.text("")
                    progress_bar.empty()
                    failure = build_generation_failure(generation_progress.stage, e, get_language())
                    st.error(failure.message)
                    st.info(failure.hint)
                    with st.expander(
                        "诊断信息" if get_language() == "zh_CN" else "Diagnostics", expanded=False
                    ):
                        st.code(failure.diagnostic, language="text")
                    # 不输出异常正文或 traceback，防止第三方响应 URL、Key 和请求头泄露。
                    logger.error(
                        "Digital human generation failed: {}",
                        failure.diagnostic.replace("\n", "; "),
                    )
                    # 只结束当前输出区，让公共“上一步”导航仍可渲染。
                    return

    def _render_saved_result(self, *, key_suffix: str = "cached"):
        """只读取最近一次已完成的本地结果，不重发 API 或重复保存作品记录。"""
        result = st.session_state.get(f"creation_result_{self.name}")
        if not result:
            return
        video_path = result.get("path")
        if not video_path or not os.path.isfile(video_path):
            st.warning(
                "上次生成的视频文件已不在本地，请到作品记录中检查。"
                if get_language() == "zh_CN"
                else "The last generated video is no longer available locally. Check History."
            )
            return
        st.markdown(
            "**上次生成结果**" if get_language() == "zh_CN" else "**Last generated result**"
        )
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        st.caption(
            f"{tr('info.generation_time')} {result.get('elapsed', 0):.1f}s · {size_mb:.2f} MB"
        )
        st.video(video_path)
        with open(video_path, "rb") as video_file:
            st.download_button(
                "下载视频" if get_language() == "zh_CN" else "Download video",
                data=video_file.read(),
                file_name=os.path.basename(video_path),
                mime="video/mp4",
                key=f"creation_result_{self.name}_download_{key_suffix}",
                use_container_width=True,
            )


# Register self
register_pipeline_ui(DigitalHumanPipelineUI)
