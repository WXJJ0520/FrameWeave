# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0

"""
API VLM-based asset analysis service.

This service mirrors the text description contract of ImageAnalysisService and
VideoAnalysisService, but uses direct provider VLM APIs instead of ComfyUI or
RunningHub workflows.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger


class APIAssetAnalysisService:
    """Analyze image/video assets with a direct VLM API provider."""

    VLM_PROVIDER_LABELS = {
        "openai": "OpenAI / Compatible",
        "dashscope": "DashScope",
    }

    IMAGE_PROMPT = """请分析这张素材图片，用中文给出适合视频解说脚本创作的简洁描述。

请重点说明：
1. 画面主体、人物/商品/场景
2. 可用于营销或叙事的关键信息
3. 画面风格、氛围、颜色和构图

输出 2-5 句话，不要编造图片中不存在的信息。"""

    VIDEO_PROMPT = """请分析这个上传的视频素材，用中文概括视频内容。

请重点说明：
1. 视频中的主体、场景和动作变化
2. 可用于视频解说脚本的卖点或叙事信息
3. 整体风格、节奏和氛围

输出 3-6 句话，不要编造关键帧中看不到的信息。"""

    def __init__(self, config: dict, core=None):
        self.config = config
        self.core = core

    def list_models(self, configured_only: bool = True) -> list[dict]:
        """只展示与当前接口匹配的已加载目录，不把内置或旧手填值伪装成接口结果。"""
        from pixelle_video.services.api_services.model_catalog import get_configured_model_ids

        providers = self.config.get("api_providers", {}) or {}
        models = []

        for provider in self.VLM_PROVIDER_LABELS:
            provider_config = providers.get(provider, {}) or {}
            configured = bool(str(provider_config.get("api_key") or "").strip())
            if configured_only and not configured:
                continue

            provider_label = self.VLM_PROVIDER_LABELS.get(provider, provider.title())
            # configured_only=False 也不能显示无目录的候选；目录条目本身不证明视觉能力。
            available_models = get_configured_model_ids(provider, provider_config, providers.get("common", {}))
            for model in available_models:
                key = f"api/vlm/{provider}/{model}"
                models.append({
                    "key": key,
                    "name": model,
                    "display_name": f"{model} - API {provider_label}",
                    "source": "api",
                    "configured": configured,
                    "catalog_source": provider_config.get("model_catalog", {}).get("source", "api"),
                    "provider": provider,
                    "model": model,
                    "media_type": "asset_analysis",
                    "ability_type": "vlm_asset_analysis",
                    "ability_types": ["vlm_asset_analysis"],
                })

        return models

    async def analyze_image(
        self,
        image_path: str,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        provider: str = "dashscope",
        max_video_frames: int = 16,
        **_: object,
    ) -> str:
        image_file = Path(image_path)
        if not image_file.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        return await self._query_vlm(
            prompt=prompt or self.IMAGE_PROMPT,
            image_paths=[str(image_file)],
            model=model,
            provider=provider,
            max_video_frames=max_video_frames,
        )

    async def analyze_video(
        self,
        video_path: str,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        provider: str = "dashscope",
        max_video_frames: int = 16,
        **_: object,
    ) -> str:
        video_file = Path(video_path)
        if not video_file.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        return await self._query_vlm(
            prompt=prompt or self.VIDEO_PROMPT,
            image_paths=[],
            video_paths=[str(video_file)],
            model=model,
            provider=provider,
            max_video_frames=max_video_frames,
        )

    async def __call__(self, asset_path: str, asset_type: Optional[str] = None, **kwargs) -> str:
        path = Path(asset_path)
        resolved_type = asset_type or self._get_asset_type(path)
        if resolved_type == "image":
            return await self.analyze_image(asset_path, **kwargs)
        if resolved_type == "video":
            return await self.analyze_video(asset_path, **kwargs)
        raise ValueError(f"Unsupported asset type for VLM analysis: {asset_path}")

    async def _query_vlm(
        self,
        prompt: str,
        image_paths: list[str],
        model: Optional[str],
        video_paths: Optional[list[str]] = None,
        provider: str = "dashscope",
        max_video_frames: int = 16,
    ) -> str:
        from pixelle_video.services.api_services.vlm_client import VLM

        if provider not in self.VLM_PROVIDER_LABELS:
            raise ValueError("请选择已接入的 OpenAI/兼容服务或 DashScope 视觉分析提供商。")
        selected_model = (model or "").strip()
        if not selected_model:
            raise RuntimeError(
                "API VLM analysis requires an explicitly selected VLM model. "
                "Please choose one in the asset analysis service settings."
            )

        logger.info(
            f"Analyzing asset via API VLM provider={provider}, "
            f"images={len(image_paths)}, videos={len(video_paths or [])}"
        )

        providers = self.config.get("api_providers", {}) or {}
        selected_provider = providers.get(provider, {}) or {}
        common = providers.get("common", {}) or {}
        local_proxy = ""
        if selected_provider.get("use_proxy"):
            local_proxy = str(common.get("local_proxy") or "").strip()
            if not local_proxy:
                raise ValueError("已开启视觉服务代理，请先在系统配置填写代理地址。")

        # 只传被选中的服务凭据；其它 provider 和文案 LLM 的 Key 均不读取。
        client = VLM(
            provider=provider,
            local_proxy=local_proxy,
            **{
                f"{provider}_api_key": selected_provider.get("api_key"),
                f"{provider}_base_url": selected_provider.get("base_url"),
            },
        )
        result = await asyncio.to_thread(
            client.query,
            prompt,
            image_paths,
            selected_model,
            None,
            video_paths,
            max_video_frames=max_video_frames,
        )
        description = str(result or "").strip()
        if not description:
            raise RuntimeError("API VLM analysis returned empty description")
        return description

    def _get_asset_type(self, path: Path) -> str:
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        ext = path.suffix.lower()
        if ext in image_exts:
            return "image"
        if ext in video_exts:
            return "video"
        return "unknown"
