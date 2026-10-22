import os
import time
from pathlib import Path
from typing import Any

import streamlit as st
from loguru import logger

from pixelle_video.utils.os_util import create_task_output_dir
from web.i18n import get_language, tr
from web.pipelines.api_workflows import (
    is_api_workflow,
    list_api_media_workflows,
    render_api_video_controls,
    workflow_select_help,
)
from web.pipelines.base import PipelineUI, register_pipeline_ui
from web.utils.async_helpers import run_async
from web.utils.history_persistence import save_web_generation_history


def list_compatible_api_models(pixelle_video: Any) -> list[dict]:
    """只使用已接入的图生视频 API 契约，通用视频模型不能替代专有能力。"""
    return list_api_media_workflows(
        pixelle_video,
        "video",
        required_adapter_abilities=["first_frame_i2v"],
        verified_only=True,
    )


class ImageToVideoPipelineUI(PipelineUI):
    """
    UI for the Image To Video Video Generation Pipeline.
    Generates videos from user-provided assets (images&text).
    """

    name = "image_to_video"
    icon = "🎥"

    @property
    def display_name(self):
        return tr("pipeline.i2v.name")

    @property
    def description(self):
        return tr("pipeline.i2v.description")

    def render(self, pixelle_video: Any):
        from web.components.creation_flow import CreationFlow

        zh = get_language() == "zh_CN"
        flow = CreationFlow(
            self.name,
            [
                ("图片与提示词", "上传图片，描述希望画面如何运动。")
                if zh
                else ("Image & prompt", "Upload your images and describe their motion."),
                ("视频参数", "选择 API 视频模型，调整时长与画幅。")
                if zh
                else ("Video settings", "Choose an API model, duration and aspect ratio."),
                ("预览与生成", "确认素材和参数后生成，在这里查看与下载结果。")
                if zh
                else (
                    "Preview & generate",
                    "Generate with your inputs, then preview and download the result.",
                ),
            ],
        )
        flow.render_header()
        # 输入步骤始终渲染，由公共布局隐藏；返回上一步不会卸载上传框与提示词。
        with flow.step(0):
            asset_params = self.render_audio_visual_input(
                pixelle_video, include_model_config=False, border=False
            )
        with flow.step(1):
            model_params = self.render_video_config(pixelle_video, border=False)
        with flow.step(2):
            if flow.is_active(2):
                self._render_output_preview(pixelle_video, {**asset_params, **model_params})
        flow.render_navigation()

    def render_audio_visual_input(
        self, pixelle_video, *, include_model_config: bool = True, border: bool = True
    ) -> dict:
        """兼容原调用入口；步骤页将模型设置独立渲染，避免控件重复。"""
        with st.container(border=border):
            # 公共步骤卡片已显示同名标题，独立调用时才补组件标题。
            if border:
                st.markdown(f"**{tr('i2v.video_generation')}**")

            with st.expander(tr("help.feature_description"), expanded=False):
                st.markdown(f"**{tr('help.what')}**")
                st.markdown(tr("i2v.assets.image_what"))
                st.markdown(f"**{tr('help.how')}**")
                st.markdown(tr("i2v.assets.how"))

            # File uploader for multiple files
            uploaded_files = st.file_uploader(
                tr("i2v.assets.upload"),
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                help=tr("i2v.assets.upload_help"),
                key="material_files",
            )

            # Save uploaded files to temp directory with unique session ID
            from web.components.creation_uploads import persist_uploaded_files

            # 内容不变时复用同一本地路径，避免来回切步骤重复写入素材。
            audio_asset_paths = persist_uploaded_files(uploaded_files or [], key="i2v_images")
            if uploaded_files:
                st.success(tr("i2v.assets.character_sucess"))

                # Preview uploaded assets
                with st.expander(tr("i2v.assets.preview"), expanded=True):
                    # Show in a grid (3 columns)
                    cols = st.columns(3)
                    for i, (file, path) in enumerate(zip(uploaded_files, audio_asset_paths)):
                        with cols[i % 3]:
                            # Check if image
                            ext = Path(path).suffix.lower()
                            if ext in [".jpg", ".jpeg", ".png", ".webp"]:
                                st.image(file, caption=file.name, use_container_width=True)
            else:
                st.info(tr("i2v.assets.character_empty_hint"))

            prompt_text = st.text_area(
                tr("i2v.input_text"),
                placeholder=tr("i2v.input.topic_placeholder"),
                height=200,
                help=tr("input.text_help_audio"),
                key="audio_box",
            )

            params = {"audio_assets": audio_asset_paths, "prompt_text": prompt_text}
            if include_model_config:
                params.update(self.render_video_config(pixelle_video, border=False))
            return params

    def render_video_config(self, pixelle_video, *, border: bool = True) -> dict:
        """API 能力筛选与参数独立成步，原生成契约保持不变。"""
        with st.container(border=border):
            # 将旧会话来源迁移到 API，缺少兼容模型时不再回退到工作流。
            st.session_state["i2v_workflow_source"] = "api"
            i2v_workflows = list_compatible_api_models(pixelle_video)
            if not i2v_workflows:
                st.warning(
                    "当前目录没有已接入的图生视频型号。请到系统配置加载并保存服务模型目录，再选择支持首帧图片输入的型号。"
                    if get_language() == "zh_CN"
                    else "Your catalog contains no integrated image-to-video model. Load and save a provider catalog in Settings, then select a supported first-frame model."
                )
            workflow_options = [wf["display_name"] for wf in i2v_workflows]
            workflow_keys = [wf["key"] for wf in i2v_workflows]
            default_workflow_index = 0

            # 旧下拉框保存的是工作流名称，重新进入页面时清除失效选项。
            if st.session_state.get("i2v_workflow_select") not in workflow_options:
                st.session_state.pop("i2v_workflow_select", None)

            workflow_display = st.selectbox(
                "API 视频模型" if get_language() == "zh_CN" else "API video model",
                workflow_options
                if workflow_options
                else [
                    "暂无可用 API 模型" if get_language() == "zh_CN" else "No API model available"
                ],
                index=default_workflow_index,
                label_visibility="visible",
                key="i2v_workflow_select",
                disabled=not workflow_options,
                help=workflow_select_help(),
            )

            if workflow_options:
                workflow_selected_index = workflow_options.index(workflow_display)
                workflow_key = workflow_keys[workflow_selected_index]
                workflow_info = i2v_workflows[workflow_selected_index]
            else:
                workflow_key = None
                workflow_info = None

            api_video_params = (
                render_api_video_controls(
                    workflow_info,
                    key_prefix="i2v",
                    default_duration=5,
                )
                if is_api_workflow(workflow_key)
                else {}
            )

            return {"workflow_key": workflow_key, "api_video_params": api_video_params}

    def _render_output_preview(self, pixelle_video: Any, video_params: dict):
        """Render output preview section"""
        with st.container(border=True):
            st.markdown(f"**{tr('section.video_generation')}**")

            # 结果与按钮点击解耦：返回前一步再回来时，仍能预览和下载上次成品。
            result_area = st.empty()
            with result_area.container():
                self._render_saved_result()

            audio_assets = video_params.get("audio_assets", [])
            prompt_text = video_params.get("prompt_text", "")
            workflow_key = video_params.get("workflow_key")
            api_video_params = video_params.get("api_video_params") or {}

            # 生成边界再次校验目录，阻止旧会话或伪造值重新进入已移除的执行路径。
            if not any(
                model["key"] == workflow_key for model in list_compatible_api_models(pixelle_video)
            ):
                st.warning(
                    "请选择兼容的 API 视频模型。"
                    if get_language() == "zh_CN"
                    else "Select a compatible API video model."
                )
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="i2v_api_unavailable",
                )
                return

            if not audio_assets:
                st.info(tr("i2v.assets.image_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="audio_visual_generate_disabled",
                )
                return

            if not prompt_text:
                st.info(tr("i2v.assets.prompt_warning"))
                st.button(
                    tr("btn.generate"),
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                    key="audio_visual_generate",
                )
                return

            # Generate button
            if st.button(
                tr("btn.generate"), type="primary", use_container_width=True, key="i2v_generate"
            ):
                progress_bar = st.progress(0)
                status_text = st.empty()

                start_time = time.time()

                try:

                    async def generate_audio_visual_video():
                        # 点击后再次读取能力目录，避免页面显示后模型能力发生变化。
                        if not any(
                            model["key"] == workflow_key
                            for model in list_compatible_api_models(pixelle_video)
                        ):
                            raise ValueError("请选择兼容的 API 视频模型。")
                        task_dir, task_id = create_task_output_dir()
                        logger.info(f"[Initialization] Task Directory: {task_dir}")

                        status_text.text(tr("progress.generation"))
                        progress_bar.progress(10)
                        image_path = audio_assets[0]
                        prompt = prompt_text
                        final_video_path = os.path.join(task_dir, "final.mp4")

                        media_params = {
                            **api_video_params,
                            "prompt": prompt,
                            "workflow": workflow_key,
                            "media_type": "video",
                            "image_path": image_path,
                            "output_path": final_video_path,
                        }
                        media_result = await pixelle_video.media(
                            **media_params,
                        )
                        progress_bar.progress(100)
                        status_text.text(tr("status.success"))
                        await save_web_generation_history(
                            pixelle_video,
                            task_id=task_id,
                            video_path=media_result.url,
                            pipeline="image_to_video",
                            title="图生视频" if get_language() == "zh_CN" else "Image to Video",
                            input_params={
                                "text": prompt,
                                "prompt_text": prompt,
                                "image_assets": audio_assets,
                                "workflow_key": workflow_key,
                                "api_video_params": api_video_params,
                            },
                        )
                        return media_result.url

                    # Execute async generation
                    final_video_path = run_async(generate_audio_visual_video())

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
                    logger.exception(e)
                    status_text.text("")
                    progress_bar.empty()
                    st.error(tr("status.error", error=str(e)))
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


register_pipeline_ui(ImageToVideoPipelineUI)
