"""Grok 适配器离线回归：不加载用户配置，不调用真实收费接口。"""

import base64
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from PIL import Image

# 按文件加载，避免导入应用包时读取 config.yaml 或初始化其它供应商。
MODULE_PATH = Path(__file__).resolve().parents[1] / "pixelle_video/services/api_services/video_grok.py"
SPEC = importlib.util.spec_from_file_location("grok_adapter_under_test", MODULE_PATH)
grok = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grok)

# 仅用于协议/文件头测试的最小 MP4 ftyp 数据，不宣称是可播放生成视频。
MP4_FIXTURE = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"local-video-fixture"


def json_response(data, status=200):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = data
    return response


def media_response(chunks=(MP4_FIXTURE,), content_type="video/mp4", headers=None):
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = {"Content-Type": content_type}
    response.headers.update(headers or {})
    response.iter_content.return_value = iter(chunks)
    return response


class GrokAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "输出视频.mp4"
        self.client = grok.GrokVideoClient(api_key="fake-private-api-key", poll_interval=0.001)
        self.addCleanup(self.client._session.close)
        self.addCleanup(self.client._download_session.close)
        self.api = Mock(spec=requests.Session)
        self.download = Mock(spec=requests.Session)
        self.client._session = self.api
        self.client._download_session = self.download
        self.done = {"status": "done", "video": {"url": "https://media.example/video.mp4", "respect_moderation": True}}

    def ready(self, *statuses):
        self.api.request.side_effect = [json_response({"request_id": "job-1"}), *(json_response(item) for item in (statuses or (self.done,)))]
        self.download.get.return_value = media_response()

    def generate(self, **kwargs):
        args = {"prompt": "镜头缓缓前进", "image_path": None, "save_path": str(self.output), "model": "grok-imagine-video"}
        args.update(kwargs)
        return self.client.generate_video(**args)

    def test_text_submission_polling_download_and_credentials(self):
        self.ready({"status": "pending"}, self.done)
        self.assertEqual(self.generate(generate_audio=False), self.done["video"]["url"])
        calls = self.api.request.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["POST", "GET", "GET"])
        self.assertEqual(calls[0].args[1], "https://api.x.ai/v1/videos/generations")
        self.assertEqual(calls[0].kwargs["json"], {"model": "grok-imagine-video", "prompt": "镜头缓缓前进", "duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "generate_audio": False})
        self.assertFalse(calls[0].kwargs["allow_redirects"])
        self.assertNotIn("Authorization", self.download.get.call_args.kwargs["headers"])
        self.assertFalse(self.download.get.call_args.kwargs["allow_redirects"])
        self.assertEqual(self.output.read_bytes(), MP4_FIXTURE)
        self.assertEqual(list(self.output.parent.glob("*.part")), [])

    def test_all_models_support_text_generation(self):
        for model in sorted(grok.GROK_VIDEO_MODELS):
            with self.subTest(model=model):
                self.ready()
                resolution = "720p" if model == "grok-imagine-video" else "1080p"
                self.generate(model=model, duration=15, resolution=resolution)
                payload = self.api.request.call_args_list[-2].kwargs["json"]
                self.assertEqual(payload["model"], model)
                self.assertNotIn("generate_audio", payload)

    def test_none_resolution_uses_720p(self):
        self.ready()
        self.generate(resolution=None)
        self.assertEqual(self.api.request.call_args_list[0].kwargs["json"]["resolution"], "720p")

    def test_api_key_with_newline_is_rejected_before_requests(self):
        with patch.object(grok.requests, "Session") as session:
            for key in ("fake-key\n", "fake\rkey", "fake\r\nkey"):
                with self.subTest(key=repr(key)), self.assertRaisesRegex(ValueError, "单行"):
                    grok.GrokVideoClient(api_key=key)
            session.assert_not_called()

    def test_image_local_url_and_data_uri_payloads(self):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(buffer, format="PNG")
        content = buffer.getvalue()
        image = Path(self.temp.name) / "首帧.jpg"
        image.write_bytes(content)  # 故意使用不同扩展名，验证实际格式识别。
        data_uri = "data:image/png;base64," + base64.b64encode(content).decode("ascii")
        for image_input, expected in [(str(image), data_uri), (data_uri, data_uri), ("https://images.example/start.png", "https://images.example/start.png")]:
            with self.subTest(image=image_input[:30]):
                self.ready()
                self.generate(prompt="", image_path=image_input, aspect_ratio="ignored")
                payload = self.api.request.call_args_list[-2].kwargs["json"]
                self.assertEqual(payload["image"], {"url": expected})
                self.assertNotIn("aspect_ratio", payload)
                self.assertNotIn("prompt", payload)

    def test_invalid_input_never_submits_paid_request(self):
        cases = [
            {"duration": 0}, {"duration": 16}, {"duration": True}, {"duration": 5.5},
            {"resolution": "1080p"}, {"resolution": "4k"}, {"model": "grok-wrong"},
            {"aspect_ratio": "8:7"}, {"prompt": " "}, {"generate_audio": "false"},
            {"image_path": "data:image/png;base64,broken!"}, {"image_path": str(self.output)},
        ]
        for params in cases:
            with self.subTest(params=params), self.assertRaises((ValueError, FileNotFoundError)):
                self.generate(**params)
        self.api.request.assert_not_called()

    def test_failed_expired_and_moderated_jobs_do_not_download(self):
        cases = [
            {"status": "failed", "error": {"code": "invalid_argument", "message": "blocked"}},
            {"status": "expired"},
            {"status": "done", "video": {"url": "https://example/video.mp4", "respect_moderation": False}},
            {"status": "done", "video": {}},
            {"status": "done", "video": {"url": "file:///private.mp4"}},
            {"status": "unexpected"},
        ]
        for status in cases:
            with self.subTest(status=status):
                self.ready(status)
                with self.assertRaises(RuntimeError):
                    self.generate()
        self.download.get.assert_not_called()

    def test_relative_content_urls_are_normalized_and_only_api_origin_is_authenticated(self):
        cases = [
            ("/v1/videos/job-1/content", "https://api.x.ai/v1/videos/job-1/content", True),
            ("videos/job-1/content", "https://api.x.ai/v1/videos/job-1/content", True),
            ("//media.example/clip.mp4", "https://media.example/clip.mp4", False),
            ("  https://api.x.ai:443/v1/videos/job-1/content  ", "https://api.x.ai:443/v1/videos/job-1/content", True),
            ("http://api.x.ai/v1/videos/job-1/content", "http://api.x.ai/v1/videos/job-1/content", False),
            ("https://api.x.ai:9443/content", "https://api.x.ai:9443/content", False),
        ]
        for remote, resolved, authenticated in cases:
            with self.subTest(remote=remote):
                self.ready({"status": "done", "video": {"url": remote, "respect_moderation": True}})
                self.assertEqual(self.generate(), resolved)
                call = self.download.get.call_args
                self.assertEqual(call.args[0], resolved)
                expected = {"Authorization": "Bearer fake-private-api-key"} if authenticated else {}
                self.assertEqual(call.kwargs["headers"], expected)
                self.assertFalse(call.kwargs["allow_redirects"])

    def test_redirects_never_forward_bearer_even_back_to_api_or_on_downgrade(self):
        for location in ("https://media.example/clip.mp4", "/v1/files/clip.mp4", "http://api.x.ai/clip.mp4"):
            with self.subTest(location=location):
                self.ready({"status": "done", "video": {"url": "/v1/videos/job-1/content"}})
                self.download.get.reset_mock()
                redirect = media_response(headers={"Location": location})
                redirect.status_code = 302
                self.download.get.side_effect = [redirect, media_response()]
                self.generate()
                calls = self.download.get.call_args_list
                self.assertEqual(calls[0].kwargs["headers"], {"Authorization": "Bearer fake-private-api-key"})
                self.assertEqual(calls[1].kwargs["headers"], {})
                self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in calls))
                redirect.close.assert_called_once()

    def test_external_redirect_to_api_does_not_gain_bearer(self):
        self.ready()
        redirect = media_response(headers={"Location": "https://api.x.ai/v1/videos/job-1/content"})
        redirect.status_code = 307
        self.download.get.side_effect = [redirect, media_response()]
        self.generate()
        self.assertTrue(all(not call.kwargs["headers"] for call in self.download.get.call_args_list))

    def test_unsafe_download_urls_and_redirects_are_rejected_without_following(self):
        unsafe = ("file:///private.mp4", "data:video/mp4;base64,AAAA", "https://user:secret@media.example/v.mp4", "https://@media.example/v.mp4", "https://[invalid-ipv6]/v.mp4", "https://media.example\\evil/v.mp4", "https://media.example/clip\n.mp4")
        for remote in unsafe:
            with self.subTest(remote=remote):
                self.ready({"status": "done", "video": {"url": remote}})
                self.download.get.reset_mock()
                with self.assertRaises(RuntimeError):
                    self.generate()
                self.download.get.assert_not_called()
        self.ready()
        redirect = media_response(headers={"Location": "https://user:secret@media.example/clip.mp4"})
        redirect.status_code = 302
        self.download.get.side_effect = [redirect]
        with self.assertRaises(RuntimeError):
            self.generate()
        self.assertEqual(self.download.get.call_count, 1)

    def test_missing_or_excessive_redirects_fail_without_new_generation(self):
        for count, headers in ((1, {}), (6, {"Location": "/redirect-loop"})):
            with self.subTest(count=count):
                self.ready()
                self.api.request.reset_mock()
                self.download.get.reset_mock()
                redirect = media_response(headers=headers)
                redirect.status_code = 302
                self.download.get.side_effect = [redirect] * count
                with self.assertRaisesRegex(RuntimeError, "重定向"):
                    self.generate()
                self.assertEqual(self.download.get.call_count, count)
                self.assertEqual([call.args[0] for call in self.api.request.call_args_list], ["POST", "GET"])

    def test_resume_only_queries_existing_task_and_downloads(self):
        self.api.request.side_effect = [json_response({"status": "pending"}), json_response({"status": "done", "video": {"url": "/v1/videos/existing-job/content"}})]
        self.download.get.return_value = media_response()
        remote = self.client.resume_video("existing-job", str(self.output))
        self.assertEqual(remote, "https://api.x.ai/v1/videos/existing-job/content")
        self.assertEqual([call.args[0] for call in self.api.request.call_args_list], ["GET", "GET"])
        self.assertTrue(all(call.args[1].endswith("/videos/existing-job") for call in self.api.request.call_args_list))
        self.assertEqual(self.output.read_bytes(), MP4_FIXTURE)

    def test_resume_failure_retains_existing_task_id_and_never_posts(self):
        self.api.request.return_value = json_response({"status": "done", "video": {"url": "/v1/videos/existing-job/content"}})
        failed_download = media_response()
        failed_download.status_code = 401
        self.download.get.return_value = failed_download
        with self.assertRaises(RuntimeError) as error:
            self.client.resume_video("existing-job", str(self.output))
        self.assertIn("HTTP 401", str(error.exception))
        self.assertIn("Grok 任务 ID：existing-job", str(error.exception))
        self.assertEqual([call.args[0] for call in self.api.request.call_args_list], ["GET"])

    def test_http_error_is_redacted_and_post_not_retried(self):
        self.api.request.return_value = json_response({"error": {"code": "unauthorized", "message": "bad fake-private-api-key, Bearer some-other-key"}}, 401)
        with self.assertRaises(RuntimeError) as error:
            self.generate()
        self.assertIn("HTTP 401", str(error.exception))
        self.assertNotIn("fake-private-api-key", str(error.exception))
        self.assertNotIn("some-other-key", str(error.exception))
        self.assertEqual(self.api.request.call_count, 1)

    def test_post_timeout_not_retried_or_exposed(self):
        self.api.request.side_effect = requests.Timeout("secret fake-private-api-key")
        with self.assertRaises(TimeoutError) as error:
            self.generate()
        self.assertNotIn("fake-private-api-key", str(error.exception))
        self.assertIn("避免重复提交", str(error.exception))
        self.assertEqual(self.api.request.call_count, 1)

    def test_poll_timeout_has_deadline_without_resubmit(self):
        self.ready({"status": "pending"})
        with patch.object(grok.time, "monotonic", side_effect=[0, 0, 601, 601]), self.assertRaises(TimeoutError):
            self.generate()
        self.assertEqual([call.args[0] for call in self.api.request.call_args_list], ["POST", "GET"])
        self.download.get.assert_not_called()

    def test_partial_download_keeps_existing_file_and_cleans_temp(self):
        self.ready()
        self.output.write_bytes(b"existing-good-video")

        def interrupted():
            yield b"partial-content"
            raise requests.ConnectionError("fake-private-api-key")

        self.download.get.return_value.iter_content.return_value = interrupted()
        with self.assertRaises(RuntimeError) as error:
            self.generate()
        self.assertNotIn("fake-private-api-key", str(error.exception))
        self.assertEqual(self.output.read_bytes(), b"existing-good-video")
        self.assertEqual(list(self.output.parent.glob("*.part")), [])

    def test_poll_and_download_errors_include_redacted_task_id(self):
        task_id = "job-fake-private-api-key"
        for failure_stage in ("poll", "download"):
            with self.subTest(stage=failure_stage):
                status = {"status": "failed"} if failure_stage == "poll" else self.done
                self.api.request.side_effect = [json_response({"request_id": task_id}), json_response(status)]
                self.download.get.side_effect = requests.ConnectionError("download interrupted")
                with self.assertRaises(RuntimeError) as error:
                    self.generate()
                self.assertIn("Grok 任务 ID：job-[已隐藏密钥]", str(error.exception))
                self.assertNotIn("fake-private-api-key", str(error.exception))

    def test_download_checks_uncompressed_length_and_mp4_header(self):
        cases = [
            media_response(headers={"Content-Length": str(len(MP4_FIXTURE) + 1)}),
            media_response(headers={"Content-Length": "invalid"}),
            media_response(chunks=(b"binary-error-resource",), content_type="application/octet-stream"),
            media_response(chunks=(b"\x00\x00\x00\x40ftypisom",)),
        ]
        for response in cases:
            with self.subTest(response=response):
                self.ready()
                self.output.write_bytes(b"existing-good-video")
                self.download.get.return_value = response
                with self.assertRaises(RuntimeError) as error:
                    self.generate()
                self.assertIn("Grok 任务 ID：job-1", str(error.exception))
                self.assertEqual(self.output.read_bytes(), b"existing-good-video")
                self.assertEqual(list(self.output.parent.glob("*.part")), [])

    def test_compressed_length_is_not_compared_to_decoded_mp4(self):
        self.ready()
        self.download.get.return_value = media_response(headers={"Content-Length": "10", "Content-Encoding": "gzip"})
        self.generate()
        self.assertEqual(self.output.read_bytes(), MP4_FIXTURE)

    def test_empty_and_html_downloads_do_not_create_video(self):
        for response in [media_response(chunks=()), media_response(content_type="text/html")]:
            with self.subTest(response=response):
                self.ready()
                self.download.get.return_value = response
                with self.assertRaises(RuntimeError):
                    self.generate()
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.output.parent.glob("*.part")), [])

    def test_missing_id_and_non_json_fail_without_retry(self):
        response = json_response({})
        invalid_json = json_response(None)
        invalid_json.json.side_effect = ValueError("malformed")
        for item in (response, invalid_json):
            self.api.reset_mock()
            self.api.request.return_value = item
            with self.assertRaises(RuntimeError):
                self.generate()
            self.assertEqual(self.api.request.call_count, 1)


class GrokLocalHttpTest(unittest.TestCase):
    def test_real_http_relative_content_auth_redirect_and_resume_without_new_post(self):
        """用不同端口模拟 API 和媒体源，验证相对地址、首次鉴权及跨源移除密钥。"""
        events = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_body(self, data, mime="application/json", status=200):
                body = json.dumps(data).encode() if mime == "application/json" else data
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                events.append(("POST", self.path, self.headers.get("Authorization"), body))
                self.send_body({"request_id": "local-job"})

            def do_GET(self):
                events.append(("GET", self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer local-fixture-key":
                    self.send_body({"error": "unauthorized"}, status=401)
                elif self.path == "/v1/videos/local-job/content":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{media_server.server_port}/clip.mp4")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self.send_body({"status": "done", "video": {"url": "/v1/videos/local-job/content", "respect_moderation": True}})

        class MediaHandler(Handler):
            def do_GET(self):
                events.append(("GET", self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization"):
                    self.send_body({"error": "credential leaked"}, status=403)
                else:
                    self.send_body(MP4_FIXTURE, "video/mp4")

        media_server = ThreadingHTTPServer(("127.0.0.1", 0), MediaHandler)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        workers = [threading.Thread(target=item.serve_forever, daemon=True) for item in (server, media_server)]
        for worker in workers:
            worker.start()
        client = grok.GrokVideoClient(api_key="local-fixture-key", base_url=f"http://127.0.0.1:{server.server_port}")
        try:
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / "local.mp4"
                # 先覆盖完整生成链路，再证明恢复入口完全不会调用创建任务的 POST。
                for resume in (False, True):
                    with self.subTest(resume=resume):
                        events.clear()
                        if resume:
                            remote = client.resume_video("local-job", str(target))
                        else:
                            remote = client.generate_video("测试", None, str(target))
                        self.assertEqual(remote, f"http://127.0.0.1:{server.server_port}/v1/videos/local-job/content")
                        self.assertEqual(target.read_bytes(), MP4_FIXTURE)
                        expected = [] if resume else [("POST", "/v1/videos/generations")]
                        expected += [("GET", "/v1/videos/local-job"), ("GET", "/v1/videos/local-job/content"), ("GET", "/clip.mp4")]
                        self.assertEqual([(event[0], event[1]) for event in events], expected)
                        self.assertTrue(all(event[2] == "Bearer local-fixture-key" for event in events[:-1]))
                        self.assertIsNone(events[-1][2])
        finally:
            client._session.close()
            client._download_session.close()
            for item in (server, media_server):
                item.shutdown()
                item.server_close()
            for worker in workers:
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
