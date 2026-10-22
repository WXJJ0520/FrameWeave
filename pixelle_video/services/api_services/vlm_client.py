"""素材视觉分析路由：显式选提供商，统一图片和视频关键帧输入。"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Optional

from .vlm_media import image_data_url, sampled_video_frames, validate_frame_limit
from .vlm_openai import OpenAIVisionClient


class DashScopeVisionClient(OpenAIVisionClient):
    """保持通义原生协议，修复旧 SDK 忽略 Base URL 和代理的问题。

    协议：https://help.aliyun.com/zh/model-studio/vision
    原生多图消息支持 image=data:image/jpeg;base64,...。
    """

    label = "DashScope 视觉服务"
    default_url = "https://dashscope.aliyuncs.com/api/v1"
    endpoint = "/services/aigc/multimodal-generation/generation"

    def _payload(self, model: str, content: list[dict]) -> dict:
        native_content = [
            {"text": item["text"]} if item["type"] == "text"
            else {"image": item["image_url"]["url"]}
            for item in content
        ]
        return {
            "model": model,
            "input": {"messages": [{"role": "user", "content": native_content}]},
            "parameters": {"enable_thinking": False, "max_tokens": 2048},
        }

    def _extract(self, data: dict) -> str:
        return super()._extract(data["output"])


class VLM:
    def __init__(
        self,
        dashscope_api_key: Optional[str] = None,
        dashscope_base_url: Optional[str] = None,
        *,
        openai_api_key: Optional[str] = None,
        openai_base_url: Optional[str] = None,
        provider: str = "dashscope",
        local_proxy: str = "",
    ):
        # 不按模型名推断提供商，也不从其它 provider/env 借用 API Key。
        if provider == "openai":
            self.client = OpenAIVisionClient(openai_api_key, openai_base_url, local_proxy)
        elif provider == "dashscope":
            self.client = DashScopeVisionClient(dashscope_api_key, dashscope_base_url, local_proxy)
        else:
            raise ValueError("素材视觉分析仅支持已接入的 OpenAI/兼容服务和 DashScope。")
        self.provider = provider

    def query(
        self,
        prompt: str,
        image_paths: Optional[list[str]] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        video_paths: Optional[list[str]] = None,
        *,
        max_video_frames: int = 16,
    ) -> str:
        selected_model = (model or "").strip()
        if not selected_model:
            raise RuntimeError("请先选择素材视觉分析模型。")
        validate_frame_limit(max_video_frames)
        images, videos = image_paths or [], video_paths or []
        # 目前素材分析按单素材调用；避免调用者一次塞入任意数量的大文件。
        if len(videos) > 1 or len(images) > 32 or (images and videos):
            raise ValueError("请逐个分析视频，或每次最多分析 32 张图片。")
        if not images and not videos:
            raise ValueError("视觉分析至少需要一张图片或一个视频。")
        content = [{"type": "text", "text": prompt}]
        with ExitStack() as resources:
            for path in images:
                content.append({"type": "image_url", "image_url": {"url": image_data_url(path)}})
            for path in videos:
                frames = resources.enter_context(sampled_video_frames(path, max_video_frames))
                content.append({"type": "text", "text": (
                    f"以下为全片均匀采样的 {len(frames)} 张关键帧，按时间排序。"
                    "仅依据这些画面描述；未分析原声，不能确定采样间隔内发生的动作或台词。"
                )})
                for timestamp, frame in frames:
                    content.append({"type": "text", "text": f"画面时间戳：{timestamp:.2f} 秒"})
                    content.append({"type": "image_url", "image_url": {"url": image_data_url(frame)}})
            return self.client.chat(content, selected_model)
