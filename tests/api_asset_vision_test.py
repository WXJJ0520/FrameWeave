"""视觉适配器离线验收：不读取真实凭据、不访问任何模型 API。"""

import asyncio
import base64
import io
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

from pixelle_video.config.schema import APIProvidersConfig
from pixelle_video.services.api_asset_analysis import APIAssetAnalysisService
from pixelle_video.services.api_services import vlm_media
from pixelle_video.services.api_services.model_catalog import make_model_catalog
from pixelle_video.services.api_services.vlm_openai import OpenAIVisionClient


class AssetVisionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.image = Path(self.directory.name) / "测试图片.png"
        Image.new("RGB", (2048, 768), "white").save(self.image)
        self.video = Path(self.directory.name) / "五分钟素材.mp4"
        self.video.write_bytes(b"offline-video-placeholder")
        # 所有 Key 都是专用虚构值，用于证明路由不借用其它服务凭据。
        self.config = {"api_providers": {
            "openai": {"api_key": "fake-openai-key", "base_url": "https://relay.invalid/prefix/v1"},
            "dashscope": {"api_key": "fake-qwen-key", "base_url": "https://qwen.invalid/custom/api/v1"},
            "common": {"local_proxy": "http://127.0.0.1:7890"},
        }, "llm": {"api_key": "fake-text-only-key"}}
        self.service = APIAssetAnalysisService(self.config)

    def response(self, content="素材中有一个白色画面。", status=200, native=False):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        data = {"choices": [{"message": {"content": content}}]}
        if native:
            data = {"output": data}
        response.iter_content.return_value = [json.dumps(data, ensure_ascii=False).encode("utf-8")]
        return response

    def session(self, response):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value = response
        session.proxies = {}
        return session

    def test_model_catalog_custom_ids_and_configured_provider_filter(self):
        """界面只列已读取且仍匹配当前凭据的目录，不受旧预设或vision_models影响。"""
        self.config["api_providers"]["openai"]["vision_models"] = [
            " custom-vision ", "gpt-4o", "custom-vision", "org/model-v2", "", "bad model", 123,
        ]
        self.assertEqual(self.service.list_models(False), [])
        for provider, ids in (("openai", ["new-api-vision", "org/model-v2"]), ("dashscope", ["new-qwen-vision"])):
            cfg = self.config["api_providers"][provider]
            cfg["model_catalog"] = make_model_catalog(provider, cfg, self.config["api_providers"]["common"], ids)
        models = self.service.list_models()
        self.assertEqual(models[0]["model"], "new-api-vision")
        names = [item["model"] for item in models]
        self.assertEqual(names, ["new-api-vision", "org/model-v2", "new-qwen-vision"])
        self.assertEqual(models[1]["key"], "api/vlm/openai/org/model-v2")
        self.assertIn("dashscope", {item["provider"] for item in self.service.list_models(False)})
        self.config["api_providers"]["dashscope"]["api_key"] = "changed-key"
        self.assertTrue(all(item["provider"] == "openai" for item in self.service.list_models(False)))
        self.config["api_providers"]["openai"]["api_key"] = ""
        self.assertEqual(self.service.list_models(), [])

    def test_openai_endpoint_image_resize_and_credentials_are_isolated(self):
        session = self.session(self.response())
        with patch("requests.Session", return_value=session):
            result = asyncio.run(self.service.analyze_image(str(self.image), model="custom-vision", provider="openai"))
        self.assertEqual(result, "素材中有一个白色画面。")
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], "https://relay.invalid/prefix/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-openai-key")
        self.assertFalse(session.trust_env)
        self.assertEqual(session.proxies, {})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (10, 120))
        body = kwargs["json"]
        self.assertEqual(body["model"], "custom-vision")
        self.assertNotIn("temperature", body)
        uri = body["messages"][0]["content"][1]["image_url"]["url"]
        with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
            self.assertEqual(image.size, (1024, 384))
        self.assertNotIn("fake-qwen-key", json.dumps(kwargs))
        self.assertNotIn("fake-text-only-key", json.dumps(kwargs))

    def test_gpt6_visual_requests_use_supported_reasoning_parameters(self):
        """验证实际提交的图像请求，不能只更新下拉名称却仍使用不兼容参数。"""
        for model in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol-2026-10-20"):
            with self.subTest(model=model):
                session = self.session(self.response())
                with patch("requests.Session", return_value=session):
                    asyncio.run(self.service.analyze_image(str(self.image), model=model, provider="openai"))
                body = session.post.call_args.kwargs["json"]
                self.assertEqual(body["model"], model)
                self.assertEqual(body["reasoning_effort"], "low")
                self.assertEqual(body["max_completion_tokens"], 4096)
                for unsupported in ("temperature", "top_p", "top_logprobs", "logprobs", "max_tokens", "tools"):
                    self.assertNotIn(unsupported, body)
        # 自定义模型和旧型号不得凭相似名字套用 GPT-6 的请求约束。
        client = OpenAIVisionClient("fake-key")
        for model in ("gpt-4o", "gpt-5.4", "relay/gpt-6.1-sol", "gpt-6.1-sol-custom", "gpt-6.1-sol-2026-99-99"):
            with self.subTest(model=model):
                self.assertNotIn("reasoning_effort", client._payload(model, []))

    def test_dashscope_default_route_uses_native_endpoint_base_and_proxy(self):
        self.config["api_providers"]["dashscope"]["use_proxy"] = True
        session = self.session(self.response(content=[{"text": "离线通义描述"}], native=True))
        with patch("requests.Session", return_value=session):
            result = asyncio.run(self.service.analyze_image(str(self.image), model="qwen3.6-plus"))
        args, kwargs = session.post.call_args
        self.assertEqual(result, "离线通义描述")
        self.assertEqual(args[0], "https://qwen.invalid/custom/api/v1/services/aigc/multimodal-generation/generation")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-qwen-key")
        self.assertEqual(session.proxies["https"], "http://127.0.0.1:7890")
        self.assertTrue(kwargs["json"]["input"]["messages"][0]["content"][1]["image"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("fake-openai-key", json.dumps(kwargs))

    def test_both_providers_reject_nonempty_truncated_visual_descriptions(self):
        """两家返回非空残稿时也必须失败，不能只依赖空字符串判断输出耗尽。"""
        for provider in ("openai", "dashscope"):
            with self.subTest(provider=provider):
                reply = self.response()
                data = {"choices": [{
                    "finish_reason": "length",
                    "message": {"content": "未完成的素材描述 fake-provider-secret"},
                }]}
                if provider == "dashscope":
                    data = {"output": data}
                reply.iter_content.return_value = [json.dumps(data, ensure_ascii=False).encode("utf-8")]
                with patch("requests.Session", return_value=self.session(reply)):
                    with self.assertRaisesRegex(RuntimeError, "长度上限") as error:
                        asyncio.run(self.service.analyze_image(str(self.image), model="test-vision", provider=provider))
                self.assertNotIn("fake-provider-secret", str(error.exception))

    def test_provider_never_guessed_from_model_and_missing_key_never_falls_back(self):
        session = self.session(self.response(native=True))
        with patch("requests.Session", return_value=session):
            asyncio.run(self.service.analyze_image(str(self.image), model="gpt-4o", provider="dashscope"))
        self.assertIn("qwen.invalid", session.post.call_args.args[0])
        self.config["api_providers"]["openai"]["api_key"] = ""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "fake-env-key"}), patch("requests.Session") as factory:
            with self.assertRaisesRegex(RuntimeError, "API Key"):
                asyncio.run(self.service.analyze_image(str(self.image), model="gpt-4o", provider="openai"))
            with self.assertRaises(ValueError):
                asyncio.run(self.service.analyze_image(str(self.image), model="gpt-4o", provider="unknown"))
            factory.assert_not_called()

    def test_enabled_proxy_without_address_fails_before_request(self):
        self.config["api_providers"]["openai"]["use_proxy"] = True
        self.config["api_providers"]["common"]["local_proxy"] = ""
        with patch("requests.Session") as factory:
            with self.assertRaisesRegex(ValueError, "代理地址"):
                asyncio.run(self.service.analyze_image(str(self.image), model="gpt-4o", provider="openai"))
            factory.assert_not_called()

    def fake_extract(self, command, timeout):
        """只生成小色块，不解码用户视频；保留命令以验证取样边界。"""
        target = Path(command[-1])
        self.sampled_paths.append(target)
        self.sampled_commands.append(command)
        Image.new("RGB", (16, 10), "white").save(target)
        return SimpleNamespace(stdout="")

    def test_long_video_uses_bounded_timestamped_frames_for_both_providers(self):
        for provider in ("openai", "dashscope"):
            with self.subTest(provider=provider):
                self.sampled_paths, self.sampled_commands = [], []
                session = self.session(self.response(native=provider == "dashscope"))
                with patch.object(vlm_media, "video_duration", return_value=600), patch.object(
                    vlm_media, "_run_media_command", side_effect=self.fake_extract
                ), patch("requests.Session", return_value=session):
                    asyncio.run(self.service.analyze_video(
                        str(self.video), provider=provider, model="custom-vision", max_video_frames=32,
                    ))
                self.assertEqual(len(self.sampled_paths), 32)
                times = [float(command[command.index("-ss") + 1]) for command in self.sampled_commands]
                self.assertAlmostEqual(times[0], 9.375)
                self.assertAlmostEqual(times[-1], 590.625)
                self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
                body = json.dumps(session.post.call_args.kwargs["json"], ensure_ascii=False)
                self.assertIn("590.62 秒", body)
                self.assertIn("未分析原声", body)
                self.assertNotIn("data:video", body)
                self.assertNotIn(self.video.name, body)
                self.assertTrue(all(not path.exists() and not path.parent.exists() for path in self.sampled_paths))

    def test_sampling_and_api_failure_both_clean_temporary_files(self):
        for failure in ("sampling", "api"):
            with self.subTest(failure=failure):
                self.sampled_paths, self.sampled_commands = [], []

                def extract(command, timeout):
                    self.fake_extract(command, timeout)
                    if failure == "sampling" and len(self.sampled_paths) == 2:
                        raise RuntimeError("offline extraction failed")

                session = self.session(self.response(status=403))
                with patch.object(vlm_media, "video_duration", return_value=300), patch.object(
                    vlm_media, "_run_media_command", side_effect=extract
                ), patch("requests.Session", return_value=session):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(self.service.analyze_video(str(self.video), model="gpt-4o", provider="openai", max_video_frames=8))
                self.assertTrue(self.sampled_paths)
                self.assertTrue(all(not path.parent.exists() for path in self.sampled_paths))
                if failure == "sampling":
                    session.post.assert_not_called()

    def test_frame_limits_and_short_video_sampling(self):
        for value in (0, -1, 33, True, 8.0, "16"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                vlm_media.frame_timestamps(600, value)
        for duration in (0, -1, math.inf, math.nan):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                vlm_media.frame_timestamps(duration, 16)
        self.assertEqual(vlm_media.frame_timestamps(1, 32), [0.5])
        self.assertEqual(len(vlm_media.frame_timestamps(6, 32)), 3)
        self.assertEqual(len(vlm_media.frame_timestamps(600, 8)), 8)

    def test_network_errors_and_invalid_responses_do_not_expose_secrets(self):
        client = OpenAIVisionClient("fake-secret", "https://relay.invalid/v1")
        for status in (400, 401, 403, 404, 429, 500, 302):
            with self.subTest(status=status):
                response = self.response("fake-secret provider raw message", status=status)
                with patch("requests.Session", return_value=self.session(response)):
                    with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as caught:
                        client.chat([], "test-model")
                self.assertNotIn("fake-secret", str(caught.exception))
                response.iter_content.assert_not_called()
        for error in (requests.Timeout("fake-secret"), requests.ConnectionError("fake-secret")):
            session = self.session(self.response())
            session.post.side_effect = error
            with patch("requests.Session", return_value=session), self.assertRaises(RuntimeError) as caught:
                client.chat([], "test-model")
            self.assertNotIn("fake-secret", str(caught.exception))
        for chunks in ([b"not-json fake-secret"], [b"x" * (1024 * 1024 + 1)], [b"{}"]):
            response = self.response()
            response.iter_content.return_value = chunks
            with patch("requests.Session", return_value=self.session(response)), self.assertRaises(RuntimeError) as caught:
                client.chat([], "test-model")
            self.assertNotIn("fake-secret", str(caught.exception))

    def test_invalid_base_url_and_media_fail_without_echo(self):
        for url in ("https://fake-secret@relay.invalid/v1", "https://relay.invalid/v1?key=fake-secret", "https://relay.invalid/v1/chat/completions"):
            with self.subTest(url=url), self.assertRaises(ValueError) as caught:
                OpenAIVisionClient("fake-secret", url)
            self.assertNotIn("fake-secret", str(caught.exception))
        with self.assertRaises(ValueError):
            vlm_media.image_data_url("data:image/jpeg;base64,invalid!")
        # 无有效视频流时不能把音频/损坏文件当作视频来采样。
        with patch.object(vlm_media, "_run_media_command", return_value=SimpleNamespace(stdout='{"streams":[],"format":{"duration":"300"}}')):
            with self.assertRaises(RuntimeError):
                vlm_media.video_duration(str(self.video))

    def test_schema_preserves_custom_models_without_expanding_unrelated_providers(self):
        model = APIProvidersConfig(openai={"vision_models": ["relay-vision"]})
        config = model.model_dump()
        self.assertEqual(config["openai"]["vision_models"], ["relay-vision"])
        self.assertEqual(config["dashscope"]["vision_models"], [])
        self.assertNotIn("vision_models", config["xai"])

    @unittest.skipUnless(os.environ.get("FRAMEWEAVE_VISION_SMOKE") == "1", "需显式启用本地 FFmpeg 采样验收")
    def test_real_ten_minute_video_sampling_without_model_calls(self):
        """低清静态色块仅验收 10 分钟采样定位，不是实际 AI 成片。"""
        video = Path(self.directory.name) / "ten-minute-offline.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=160x90:r=2", "-t", "600",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(video),
        ], check=True, capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with vlm_media.sampled_video_frames(str(video), 16) as frames:
            self.assertEqual(len(frames), 16)
            self.assertAlmostEqual(frames[-1][0], 581.25)
            paths = [Path(path) for _, path in frames]
            self.assertTrue(all(path.is_file() for path in paths))
        self.assertTrue(all(not path.parent.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
