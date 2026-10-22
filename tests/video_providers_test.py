"""验证新视频入口的注册、参数流转和失败行为；不调用真实生成服务。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pixelle_video.services.api_media import APIProviderMediaService
from pixelle_video.services.api_services.video_client import VideoClient
from web.pipelines.api_workflows import list_api_media_workflows


class VideoProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.service = APIProviderMediaService({})
        # 参数流转测试使用已加载目录替身，不读取用户凭据或发起模型目录查询。
        self.enterContext(patch.object(self.service, "list_available_workflows", side_effect=self.service.list_workflows))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = str(Path(self.temp.name) / "video.mp4")

    def generate(self, provider="xai", model="grok-imagine-video", **params):
        """从真实媒体服务入口调用，输出文件由模拟客户端创建。"""
        return asyncio.run(self.service(
            prompt="一只纸船漂在水面上",
            workflow=f"api/{provider}/{model}",
            output_path=self.output,
            **params,
        ))

    def client(self):
        fake = Mock()
        fake.generate_video.side_effect = lambda **kwargs: Path(kwargs["save_path"]).write_bytes(b"local-test")
        return fake

    def test_models_visible_in_text_and_image_workflows(self):
        for ability in ("text_to_video", "first_frame_i2v"):
            with self.subTest(ability=ability):
                models = list_api_media_workflows(
                    SimpleNamespace(api_media=self.service), "video", [ability], verified_only=True,
                )
                self.assertEqual(
                    {m["model"] for m in models if m["provider"] in {"xai", "muse"}},
                    {"grok-imagine-video", "grok-imagine-video-1.5", "grok-imagine-video-1.5-lite", "muse-video"},
                )

    def test_grok_text_generation_defaults_and_clamps_duration(self):
        client = self.client()
        with patch.object(self.service, "_create_video_client", return_value=client):
            result = self.generate(duration=30, width=1080, height=1920)
        call = client.generate_video.call_args.kwargs
        self.assertEqual(call["duration"], 15)
        self.assertEqual(call["resolution"], "720p")
        self.assertEqual(call["video_ratio"], "9:16")
        self.assertFalse(call["generate_audio"])
        self.assertIsNone(call["image_path"])
        self.assertEqual(result.url, self.output)

    def test_grok_image_and_audio_forwarded_without_unsupported_fields(self):
        client = self.client()
        with patch.object(self.service, "_create_video_client", return_value=client):
            self.generate(model="grok-imagine-video-1.5", image_path="first-frame.png", generate_audio=True, resolution="1080P")
        call = client.generate_video.call_args.kwargs
        self.assertEqual(call["image_path"], "first-frame.png")
        self.assertEqual(call["resolution"], "1080p")
        self.assertTrue(call["generate_audio"])
        self.assertNotIn("watermark", call)
        self.assertNotIn("negative_prompt", call)

    def test_muse_uses_supported_duration_and_reports_measured_duration(self):
        client = self.client()
        with patch.object(self.service, "_create_video_client", return_value=client), patch(
            "ffmpeg.probe", return_value={"format": {"duration": "5.7"}},
        ):
            result = self.generate(provider="muse", model="muse-video", duration=9)
        call = client.generate_video.call_args.kwargs
        self.assertEqual(call["duration"], 8)
        self.assertNotIn("resolution", call)
        self.assertNotIn("generate_audio", call)
        self.assertEqual(result.duration, 5.7)

    def test_muse_unknown_actual_duration_is_not_request_duration(self):
        with patch.object(self.service, "_create_video_client", return_value=self.client()), patch(
            "ffmpeg.probe", side_effect=FileNotFoundError,
        ):
            result = self.generate(provider="muse", model="muse-video", duration=10)
        self.assertIsNone(result.duration)

    def test_muse_selects_nearest_duration_before_truncating_narration(self):
        for requested, expected in ((7.9, 8), (9.9, 10)):
            with self.subTest(requested=requested):
                client = self.client()
                with patch.object(self.service, "_create_video_client", return_value=client), patch(
                    "ffmpeg.probe", return_value={"format": {"duration": "8.0"}},
                ):
                    self.generate(provider="muse", model="muse-video", duration=requested)
                self.assertEqual(client.generate_video.call_args.kwargs["duration"], expected)

    def test_rejections_are_not_rewritten_or_resubmitted(self):
        for provider, model in (("xai", "grok-imagine-video"), ("muse", "muse-video")):
            with self.subTest(provider=provider):
                client = Mock()
                client.generate_video.side_effect = RuntimeError("content inspection rejected")
                with patch.object(self.service, "_create_video_client", return_value=client), patch.object(
                    self.service, "_neutralize_video_prompt",
                ) as rewrite:
                    with self.assertRaises(RuntimeError):
                        self.generate(provider=provider, model=model, prompt_safety_retries=3)
                self.assertEqual(client.generate_video.call_count, 1)
                rewrite.assert_not_called()

    def test_reference_inputs_are_rejected_before_creating_client(self):
        with patch.object(self.service, "_create_video_client") as create:
            with self.assertRaises(ValueError):
                self.generate(reference_image_paths=["reference.png"])
        create.assert_not_called()

    def test_router_only_initializes_selected_provider(self):
        # 未配置其它供应商时仍能选择新入口；此处仅构造 mock，不发出网络请求。
        with patch("pixelle_video.services.api_services.video_client.Config") as config, patch(
            "pixelle_video.services.api_services.video_client.GrokVideoClient",
        ) as grok, patch("pixelle_video.services.api_services.video_muse.MuseVideoClient") as muse:
            config.PRINT_MODEL_INPUT = False
            client = VideoClient(xai_api_key="test-xai", muse_api_key="test-muse", muse_base_url="http://localhost/v1")
            client.generate_video("test", None, self.output, model="grok-imagine-video", generate_audio=False)
            grok.assert_called_once()
            muse.assert_not_called()
            client.generate_video("test", None, self.output, model="muse-video")
            muse.assert_called_once()
            self.assertIsNone(client._dashscope_client)
            self.assertIsNone(client._kling_client)
            self.assertIsNone(client._seedance_client)


if __name__ == "__main__":
    unittest.main()
