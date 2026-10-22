"""muse2api 协议离线回归：不加载用户配置，不联网，也不消耗真实生成额度。"""

import base64
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests


# 隔离导入适配器：项目顶层 __init__ 会初始化配置，本测试不应触及它。
MODULE_ROOT = Path(__file__).resolve().parents[1] / "pixelle_video/services/api_services"
PACKAGE_NAME = "_pixelle_muse_adapter_tests"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MODULE_ROOT)]
sys.modules[PACKAGE_NAME] = package
config_module = types.ModuleType(f"{PACKAGE_NAME}.config")
config_module.Config = types.SimpleNamespace(MUSE_API_KEY="", MUSE_BASE_URL="")
sys.modules[config_module.__name__] = config_module
spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.video_muse", MODULE_ROOT / "video_muse.py")
video_muse = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = video_muse
spec.loader.exec_module(video_muse)
MuseVideoClient = video_muse.MuseVideoClient


def json_response(data, status=200):
    """构造 requests 响应替身，任何测试都不会访问真实服务器。"""
    response = Mock()
    response.status_code = status
    response.json.return_value = data
    return response


def download_response(content=None, status=200, content_type="video/mp4", content_length=None):
    """使用最小 MP4 文件头验证保存流程，无需调用视频生成服务。"""
    content = content if content is not None else b"\x00\x00\x00\x18ftypmp42" + b"test-video-payload"
    response = Mock()
    response.status_code = status
    response.headers = {"Content-Type": content_type, "Content-Length": str(len(content) if content_length is None else content_length)}
    response.iter_content.return_value = iter([content])
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class MuseAdapterTests(unittest.TestCase):
    """验证任务契约、失败边界和凭据隔离，而非仅复述实现。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "视频.mp4"
        self.client = MuseVideoClient(
            api_key="m2a_offline_secret", base_url="https://muse.test", poll_interval=0,
            max_polls=3, poll_timeout=60,
        )
        self.client._session = Mock()
        self.client._download_session = Mock()
        self.client._download_session.get.return_value = download_response()

    def arrange(self, *responses):
        self.client._session.request.side_effect = responses

    def generate(self, **kwargs):
        return self.client.generate_video("树叶轻轻摇动", None, str(self.output), **kwargs)

    def test_base_url_root_and_v1_normalization(self):
        for value in ("https://muse.test", "https://muse.test/", "https://muse.test/v1/"):
            self.assertEqual(MuseVideoClient._normalize_base_url(value), "https://muse.test/v1")
        self.assertEqual(MuseVideoClient._normalize_base_url("https://muse.test/proxy/v1"), "https://muse.test/proxy/v1")

    def test_base_url_rejects_query_credentials_and_non_http(self):
        for value in ("", "file:///tmp", "https://key@muse.test", "https://muse.test?key=secret", "https://muse.test/#fragment"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MuseVideoClient._normalize_base_url(value)

    def test_text_video_pending_completed_relative_media(self):
        self.arrange(json_response({"id": "task-1", "status": "queued"}),
                     json_response({"status": "processing"}),
                     json_response({"status": "completed", "result": {"url": "/v1/media/one.mp4"}}))
        remote = self.generate(duration=6, aspect_ratio="9:16")
        self.assertEqual(remote, "https://muse.test/v1/media/one.mp4")
        self.assertTrue(self.output.is_file())
        requests_made = self.client._session.request.call_args_list
        self.assertEqual([call.args[0] for call in requests_made], ["POST", "GET", "GET"])
        self.assertEqual(requests_made[0].kwargs["json"], {
            "model": "muse-video", "prompt": "树叶轻轻摇动", "duration": 6, "size": "9:16",
        })
        self.assertEqual(requests_made[1].args[1], "https://muse.test/v1/videos/task-1")
        self.assertFalse(requests_made[0].kwargs["allow_redirects"])

    def test_image_video_encodes_current_local_reference(self):
        reference = Path(self.temp.name) / "首帧.png"
        reference.write_bytes(b"offline-image")
        self.arrange(json_response({"task_id": "task-img"}),
                     json_response({"status": "succeeded", "video": {"url": "https://cdn.test/result.mp4"}}))
        self.client.generate_video("镜头缓慢拉远", str(reference), str(self.output))
        payload = self.client._session.request.call_args_list[0].kwargs["json"]
        self.assertEqual(payload["reference_image"], "data:image/png;base64," + base64.b64encode(b"offline-image").decode())

    def test_data_url_and_http_reference_preserved(self):
        for value in ("data:image/png;base64,aW1hZ2U=", "https://images.test/frame.png"):
            self.assertEqual(self.client._reference_image(value), value)
        with self.assertRaises(ValueError):
            self.client._reference_image("data:image/png;base64,%%%")

    def test_input_validation_prevents_submission(self):
        cases = [{"duration": 4}, {"duration": True}, {"duration": "5"}, {"aspect_ratio": "1:1"},
                 {"resolution": "720p"}, {"generate_audio": False}, {"model": "muse-spark"}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.generate(**kwargs)
        self.client._session.request.assert_not_called()

    def test_missing_reference_does_not_submit(self):
        with self.assertRaises(FileNotFoundError):
            self.client.generate_video("测试", str(Path(self.temp.name) / "missing.png"), str(self.output))
        self.client._session.request.assert_not_called()

    def test_creation_timeout_never_reposts_or_leaks_key(self):
        self.arrange(requests.Timeout("m2a_offline_secret internal URL"))
        with self.assertRaises(RuntimeError) as captured:
            self.generate()
        self.assertNotIn("m2a_offline_secret", str(captured.exception))
        self.assertIn("未自动重试", str(captured.exception))
        self.assertEqual(self.client._session.request.call_count, 1)

    def test_poll_transport_and_503_recover_without_post(self):
        self.arrange(json_response({"id": "task-retry"}), requests.ConnectionError("offline"),
                     json_response({}, 503), json_response({"status": "completed", "url": "/v1/media/done.mp4"}))
        self.generate()
        methods = [call.args[0] for call in self.client._session.request.call_args_list]
        self.assertEqual(methods, ["POST", "GET", "GET", "GET"])

    def test_failed_task_does_not_echo_upstream_secret(self):
        self.arrange(json_response({"id": "task-failed"}), json_response({
            "status": "failed", "error": "Authorization: Bearer m2a_offline_secret; cookie=private",
        }))
        with self.assertRaises(RuntimeError) as captured:
            self.generate()
        self.assertIn("task-failed", str(captured.exception))
        self.assertNotIn("private", str(captured.exception))
        self.assertNotIn("m2a_offline_secret", str(captured.exception))
        self.client._download_session.get.assert_not_called()

    def test_timeout_preserves_task_identifier_and_single_post(self):
        self.arrange(json_response({"id": "task-long"}), *[json_response({"status": "processing"}) for _ in range(3)])
        with self.assertRaises(TimeoutError) as captured:
            self.generate()
        self.assertIn("task-long", str(captured.exception))
        self.assertIn("未自动重新生成", str(captured.exception))
        self.assertEqual(sum(call.args[0] == "POST" for call in self.client._session.request.call_args_list), 1)

    def test_poll_401_fails_immediately_with_id_and_no_raw_body(self):
        self.arrange(json_response({"id": "task-auth"}), json_response({"error": "secret"}, 401))
        with self.assertRaises(RuntimeError) as captured:
            self.generate()
        self.assertIn("401", str(captured.exception))
        self.assertIn("task-auth", str(captured.exception))
        self.assertNotIn("secret", str(captured.exception))
        self.assertEqual(self.client._session.request.call_count, 2)

    def test_auth_not_forwarded_to_cross_origin_download(self):
        self.arrange(json_response({"id": "task-cdn"}),
                     json_response({"status": "done", "url": "https://cdn.test/result.mp4?signature=abc"}))
        self.generate()
        download_kwargs = self.client._download_session.get.call_args.kwargs
        self.assertNotIn("Authorization", download_kwargs.get("headers", {}))
        self.assertNotIn("auth", download_kwargs)
        self.assertNotIn("m2a_offline_secret", repr(self.client._download_session.get.call_args))

    def test_api_redirect_is_rejected_without_resubmission(self):
        self.arrange(json_response({}, 307))
        with self.assertRaises(RuntimeError):
            self.generate()
        self.assertEqual(self.client._session.request.call_count, 1)
        self.assertFalse(self.client._session.request.call_args.kwargs["allow_redirects"])

    def test_invalid_media_scheme_is_rejected(self):
        self.arrange(json_response({"id": "task-url"}),
                     json_response({"status": "completed", "url": "file:///private/video.mp4"}))
        with self.assertRaises(RuntimeError):
            self.generate()
        self.client._download_session.get.assert_not_called()

    def test_download_failure_keeps_existing_video_and_cleans_partial(self):
        self.output.write_bytes(b"previous-video")
        response = download_response()
        def interrupted_chunks():
            yield b"\x00\x00\x00\x18ftypmp42"
            raise requests.ConnectionError("m2a_offline_secret")
        response.iter_content.return_value = interrupted_chunks()
        self.client._download_session.get.return_value = response
        with self.assertRaises(RuntimeError) as captured:
            self.client._download_video("https://cdn.test/video.mp4", str(self.output))
        self.assertEqual(self.output.read_bytes(), b"previous-video")
        self.assertEqual(list(Path(self.temp.name).glob("*.part")), [])
        self.assertNotIn("m2a_offline_secret", str(captured.exception))

    def test_cover_image_or_html_never_saved_as_video(self):
        for content, content_type in ((b"<html>error</html>", "text/html"), (b"\x89PNG\r\n\x1a\ncover", "video/mp4")):
            with self.subTest(content_type=content_type):
                self.client._download_session.get.return_value = download_response(content, content_type=content_type)
                with self.assertRaises(RuntimeError):
                    self.client._download_video("https://cdn.test/result", str(self.output))
                self.assertFalse(self.output.exists())
                self.assertEqual(list(Path(self.temp.name).glob("*.part")), [])

    def test_truncated_video_is_not_published(self):
        self.client._download_session.get.return_value = download_response(content_length=999)
        with self.assertRaises(RuntimeError):
            self.client._download_video("https://cdn.test/result", str(self.output))
        self.assertFalse(self.output.exists())
        self.assertEqual(list(Path(self.temp.name).glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
