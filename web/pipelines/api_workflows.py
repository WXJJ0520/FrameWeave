"""Helpers for exposing direct API media models in Streamlit pipeline UIs."""

import os
from typing import Any

import streamlit as st
from loguru import logger

from web.i18n import get_language


def is_api_workflow(workflow_key: str | None) -> bool:
    """Return True for direct provider workflow keys such as api/dashscope/xxx."""
    return bool(workflow_key and workflow_key.startswith("api/"))


def is_source_workflow(workflow: dict, source: str) -> bool:
    """Return True when a workflow belongs to a concrete source namespace."""
    key = workflow.get("key") or workflow.get("path") or ""
    return key.startswith(f"{source}/") or workflow.get("source") == source


def workflow_source_label(source: str) -> str:
    """Human-facing label for workflow source selectors."""
    zh = get_language() == "zh_CN"
    labels = {
        "selfhost": "本地 ComfyUI" if zh else "Local ComfyUI",
        "runninghub": "RunningHub",
        "api": "API 模型" if zh else "API models",
    }
    return labels.get(source, source)


def workflow_source_help(subject: str | None = None) -> str:
    """API 入口只解释真实模型用途，不再引导到旧工作流来源。"""
    zh = get_language() == "zh_CN"
    subject = subject or ("当前步骤" if zh else "this step")
    if zh:
        return f"{subject}通过 API 调用模型服务。请在系统配置中填写对应提供商的地址与密钥，加载模型目录后保存；下方只展示目录中已接入且适用于此步骤的型号。"
    return f"Use a provider API for {subject}. Configure its URL and credentials in Settings, load its model catalog and save. Only catalog models integrated for this step are listed below."


def workflow_select_help() -> str:
    """说明目录来源与能力范围，避免把文本/视觉模型误认为视频生成模型。"""
    if get_language() == "zh_CN":
        return (
            "请先在系统配置中加载并保存服务模型目录；不提供目录接口的服务可明确手工填写。"
            "这里仅显示该目录与本项目已接入、适用于当前步骤的图片或视频型号的交集。"
            "未加载或配置变化后目录失效时不会展示固定候选。文本或视觉模型不会自动成为视频生成模型；"
            "实际可用性取决于服务配置、账号权限与模型支持情况。"
        )
    return (
        "Load and save your service's model catalog in Settings first, or explicitly enter IDs if it has no catalog API. "
        "This list only includes catalog models integrated for this image or video step. An absent or outdated catalog "
        "does not fall back to presets. Text or vision models do not automatically "
        "generate video. Availability depends on provider settings, account access and model support."
    )


def list_local_media_workflows(
    pixelle_video: Any,
    media_type: str,
    source: str,
    key_contains: str | None = None,
    key_prefix: str | None = None,
) -> list[dict]:
    """List non-API media workflows by source without mixing provider models."""
    try:
        workflows = []
        seen_keys = set()
        for workflow in pixelle_video.media.list_workflows():
            key = workflow.get("key") or workflow.get("path") or ""
            if not key or key.startswith("api/"):
                continue
            if not is_source_workflow(workflow, source):
                continue
            if key_contains and key_contains.lower() not in key.lower():
                continue
            if key_prefix:
                fname = os.path.basename(key)
                if not fname.startswith(key_prefix):
                    continue
            workflow_media_type = workflow.get("media_type")
            if media_type == "video":
                if workflow_media_type and workflow_media_type != "video":
                    continue
                if not workflow_media_type and "video_" not in key.lower() and not (key_prefix and os.path.basename(key).startswith(key_prefix)):
                    continue
            elif workflow_media_type and workflow_media_type != media_type:
                continue
            elif media_type == "image" and "video_" in key.lower():
                continue
            seen_keys.add(key)
            workflows.append({
                "key": key,
                "display_name": workflow.get("display_name") or key,
                **workflow,
            })

        if key_prefix:
            try:
                from pixelle_video.utils.os_util import get_resource_path, list_resource_files

                for filename in list_resource_files("workflows", source):
                    if not filename.startswith(key_prefix) or not filename.endswith(".json"):
                        continue
                    key = f"{source}/{filename}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    workflows.append({
                        "key": key,
                        "name": filename,
                        "display_name": f"{filename} - {source.title()}",
                        "source": source,
                        "path": get_resource_path("workflows", source, filename),
                        "media_type": media_type,
                    })
            except Exception as exc:
                logger.warning(f"Failed to list {source}/{key_prefix} workflows from files: {exc}")
        return workflows
    except Exception as exc:
        logger.warning(f"Failed to list {source} {media_type} workflows: {exc}")
        return []


def list_api_media_workflows(
    pixelle_video: Any,
    media_type: str,
    required_adapter_abilities: list[str] | tuple[str, ...] | set[str] | None = None,
    verified_only: bool = False,
) -> list[dict]:
    """List API-backed media workflows in the same option shape used by UIs."""
    api_media = getattr(pixelle_video, "api_media", None)
    if api_media is None:
        return []

    required = set(required_adapter_abilities or [])

    try:
        workflows = []
        # Web 只能使用绑定当前配置的已加载目录，不能回退内部固定协议注册表。
        for workflow in api_media.list_available_workflows():
            # 即使第三方注册表混入旧条目，Web 选择器也不提供工作流回退。
            if not is_api_workflow(workflow.get("key")):
                continue
            if workflow.get("media_type") != media_type:
                continue

            if verified_only and not workflow.get("api_contract_verified", True):
                continue

            adapter_abilities = set(workflow.get("adapter_ability_types") or [])
            if required and not required.intersection(adapter_abilities):
                continue

            workflows.append({
                "key": workflow["key"],
                "display_name": workflow.get("display_name") or workflow["key"],
                **workflow,
            })

        return workflows
    except Exception as exc:
        logger.warning(f"Failed to list API {media_type} workflows: {exc}")
        return []


def render_api_video_controls(
    workflow: dict | None,
    key_prefix: str,
    default_duration: int = 5,
    allow_audio_driven: bool = False,
    show_duration: bool = True,
    default_ratio: str | None = None,
) -> dict:
    """Render common API video controls based on verified adapter capability metadata."""
    if not workflow or not is_api_workflow(workflow.get("key")):
        return {}

    zh = get_language() == "zh_CN"
    capabilities = workflow.get("capabilities") or {}
    adapter_abilities = set(workflow.get("adapter_ability_types") or [])
    provider = workflow.get("provider")
    params: dict[str, Any] = {}

    title = "API 视频模型参数" if zh else "API video model options"
    with st.expander(title, expanded=False):
        ability_text = ", ".join(sorted(adapter_abilities)) or ("未标注" if zh else "unknown")
        st.caption(("已接入能力：" if zh else "Adapter abilities: ") + ability_text)

        if not workflow.get("api_contract_verified", False):
            st.warning(
                "这个模型的公开 API 数据契约尚未完全确认，只会传递最基础的图生视频参数。"
                if zh
                else "This model's public API contract is not fully verified; only basic image-to-video parameters will be passed."
            )

        duration_contract = capabilities.get("duration") or {}
        min_duration = int(duration_contract.get("min", 3))
        max_duration = int(duration_contract.get("max", 15))
        if show_duration:
            default_value = min(max(int(default_duration or min_duration), min_duration), max_duration)
            allowed_durations = duration_contract.get("allowed_values")
            if allowed_durations:
                # Muse 只接收离散时长，不能用连续滑块展示不支持的 7/9 秒。
                params["duration"] = st.select_slider(
                    "视频时长（秒）" if zh else "Duration (seconds)",
                    options=allowed_durations,
                    value=min(allowed_durations, key=lambda value: abs(value - default_value)),
                    key=f"{key_prefix}_api_duration",
                )
            else:
                params["duration"] = st.slider(
                    "视频时长（秒）" if zh else "Duration (seconds)",
                    min_value=min_duration,
                    max_value=max_duration,
                    value=default_value,
                    step=1,
                    key=f"{key_prefix}_api_duration",
                )
        else:
            st.caption(
                f"视频时长将自动跟随每段旁白音频长度，并限制在模型支持范围 {min_duration}-{max_duration}s。"
                if zh
                else f"Duration follows each scene's narration audio and is clamped to the model range {min_duration}-{max_duration}s."
            )

        resolutions = capabilities.get("resolutions") or []
        # 可灵当前适配器使用 mode 控制质量，没有传递 resolution 字段。
        # 模型产品能力不等于本项目已接入的参数，避免展示无效设置。
        if resolutions and provider != "kling":
            params["resolution"] = st.selectbox(
                "分辨率" if zh else "Resolution",
                resolutions,
                index=0,
                key=f"{key_prefix}_api_resolution",
            )

        ratios = capabilities.get("ratios") or []
        if ratios:
            preferred_ratio = default_ratio or "9:16"
            default_ratio_index = ratios.index(preferred_ratio) if preferred_ratio in ratios else 0
            params["video_ratio"] = st.selectbox(
                "画幅比例" if zh else "Aspect ratio",
                ratios,
                index=default_ratio_index,
                key=f"{key_prefix}_api_ratio",
            )

        # 只展示对应接口真正支持的参数，避免用户填写后被静默丢弃。
        if provider not in {"xai", "muse"}:
            negative_prompt = st.text_area(
                "负向提示词（可选）" if zh else "Negative prompt (optional)",
                value="",
                height=70,
                key=f"{key_prefix}_api_negative_prompt",
            )
            if negative_prompt.strip():
                params["negative_prompt"] = negative_prompt.strip()

        if provider not in {"xai", "muse", "kling"} and workflow.get("api_contract_verified", False):
            params["watermark"] = st.checkbox(
                "添加水印" if zh else "Add watermark",
                value=False,
                key=f"{key_prefix}_api_watermark",
            )

        if provider in {"seedance", "xai"} and workflow.get("api_contract_verified", False):
            params["generate_audio"] = st.checkbox(
                "让模型生成原生音频" if zh else "Generate native audio",
                value=False,
                key=f"{key_prefix}_api_generate_audio",
            )

        if provider == "xai":
            st.caption(
                "图生视频的画幅跟随输入图片；1.5-lite 的 1080p 为升采样输出。"
                if zh else "Image-to-video follows the input image's aspect ratio; 1.5-lite upscales to 1080p."
            )
        elif provider == "muse":
            st.caption(
                "通过自建 muse2api 生成；时长按最接近的 5/6/8/10 秒请求，实际长度由上游决定。"
                if zh else "Uses your muse2api server. Requests the nearest 5/6/8/10 seconds; final duration depends on the upstream service."
            )

        if provider == "kling":
            st.caption(
                "当前接入使用专业模式；图生视频画幅跟随输入图片。分辨率和水印由服务决定。"
                if zh else "This adapter uses pro mode. Image-to-video follows the input image; resolution and watermark are controlled by the service."
            )

        # v2.5-turbo 不接收 sound；旧页面残留的勾选值也不能进入该型号请求。
        if (provider == "kling" and "native_audio" in adapter_abilities
                and workflow.get("api_contract_verified", False)):
            params["sound"] = "on" if st.checkbox(
                "让模型生成原生音频" if zh else "Generate native audio",
                value=False,
                key=f"{key_prefix}_api_kling_sound",
            ) else "off"

        if allow_audio_driven and "audio_driven_i2v" in adapter_abilities:
            params["use_narration_audio_as_driving_audio"] = st.checkbox(
                "使用本场景旁白音频驱动画面" if zh else "Use narration audio as driving audio",
                value=False,
                help=(
                    "仅对已验证支持 driving_audio 的 API 模型生效。"
                    if zh
                    else "Only applies to verified API models that support driving_audio."
                ),
                key=f"{key_prefix}_api_audio_driven",
            )

    return {key: value for key, value in params.items() if value not in (None, "")}
