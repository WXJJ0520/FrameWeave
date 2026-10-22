"""只读连接诊断测试：模拟供应商协议与本机 HTTP 服务，不使用用户配置。"""

import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
import requests
from urllib3.exceptions import ReadTimeoutError


# 单独加载无副作用模块，禁止测试期间初始化真实 config_manager。
spec = importlib.util.spec_from_file_location(
    "provider_connectivity_under_test",
    Path(__file__).resolve().parents[1] / "pixelle_video/services/api_services/connectivity.py",
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
check = module.check_provider_connection


def response(payload=None, status=200, raw=None):
    reply = requests.Response()
    reply.status_code = status
    reply._content = raw if raw is not None else json.dumps(payload).encode("utf-8")
    reply._content_consumed = True
    return reply


class ProviderConnectivityTest(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.session.__enter__ = Mock(return_value=self.session)
        self.session.__exit__ = Mock(return_value=False)
        session_patch = patch.object(module.requests, "Session", return_value=self.session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

    def run_check(self, provider="xai", replies=None, **kwargs):
        defaults = {"base_url": "https://example.invalid/v1", "api_key": "test-key"}
        defaults.update(kwargs)
        self.session.get.side_effect = replies or [response({"models": [{"id": "grok-imagine-video"}]})]
        return check(provider, **defaults)

    def test_xai_video_models_and_explicit_proxy_only(self):
        result = self.run_check(use_proxy=True, local_proxy="http://127.0.0.1:19090")
        self.assertEqual(result.level, "success")
        self.assertEqual(result.model_ids, ("grok-imagine-video",))
        args, kwargs = self.session.get.call_args
        self.assertEqual(args[0], "https://example.invalid/v1/video-generation-models")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["proxies"], {"http": "http://127.0.0.1:19090", "https": "http://127.0.0.1:19090"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        self.assertFalse(self.session.trust_env)
        self.assertEqual(kwargs["timeout"], (10, 20))
        self.assertIn("显式代理", result.details[0])
        self.assertIn("GET /v1/video-generation-models", result.details[0])
        self.assertIn("未提交生成任务", result.details[1])
        self.assertEqual(len(result.details), 2)

    def test_xai_fallback_stays_same_service_and_reports_limit(self):
        result = self.run_check(replies=[response({}, 404), response({"data": [{"id": "grok-imagine-video"}]})])
        self.assertEqual(result.level, "success")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(self.session.get.call_args.args[0], "https://example.invalid/v1/models")
        self.assertTrue(any("通用模型列表" in detail for detail in result.details))

    def test_generic_chat_models_do_not_claim_video_support(self):
        result = self.run_check(replies=[response({}, 405), response({"data": [{"id": "grok-4"}]})])
        self.assertEqual(result.level, "warning")
        self.assertIn("未返回", result.message)

    def test_muse_and_openai_bearer_model_catalogs(self):
        for provider, model in (("muse", "muse-video"), ("openai", "gpt-image-2")):
            with self.subTest(provider=provider):
                result = self.run_check(provider, [response({"object": "list", "data": [{"id": model}]})], base_url="https://example.invalid")
                self.assertEqual(result.level, "success")
                self.assertEqual(self.session.get.call_args.args[0], "https://example.invalid/v1/models")

    def test_dashscope_native_schema_and_single_catalog_sample(self):
        result = self.run_check("dashscope", [response({"success": True, "output": {"models": [{"model": "qwen-plus"}], "total": 20}})], base_url="https://example.invalid/api/v1")
        self.assertEqual(result.level, "success")
        self.assertEqual(result.model_ids, ("qwen-plus",))
        self.assertEqual(self.session.get.call_args.kwargs["params"], {"page_no": 1, "page_size": 1})
        result = self.run_check("dashscope", [response({"success": False, "output": {"models": []}})])
        self.assertEqual(result.level, "error")

    def test_ark_empty_task_list_is_success_without_returning_history(self):
        result = self.run_check("ark", [response({"items": [], "total": 0})], base_url="https://example.invalid/api/v3")
        self.assertEqual(result.level, "success")
        self.assertEqual(result.model_ids, ())
        self.assertEqual(self.session.get.call_args.args[0], "https://example.invalid/api/v3/contents/generations/tasks")
        self.assertEqual(self.session.get.call_args.kwargs["params"], {"page_num": 1, "page_size": 1})

    def test_kling_uses_jwt_and_checks_business_code(self):
        result = self.run_check("kling", [response({"code": 0, "data": []})], base_url="https://example.invalid", access_key="test-ak", secret_key="test-secret")
        self.assertEqual(result.level, "success")
        token = self.session.get.call_args.kwargs["headers"]["Authorization"].split()[1]
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
        self.assertEqual(payload["iss"], "test-ak")
        self.assertEqual(self.session.get.call_args.args[0], "https://example.invalid/v1/videos/text2video")
        result = self.run_check("kling", [response({"code": 1002, "message": "test-secret", "data": []})], base_url="https://example.invalid", access_key="test-ak", secret_key="test-secret")
        self.assertEqual(result.level, "error")
        self.assertNotIn("test-secret", repr(result))

    def test_http_failure_categories_never_reflect_raw_body_or_credentials(self):
        for status, level in ((401, "error"), (403, "error"), (404, "warning"), (405, "warning"), (429, "warning"), (500, "error"), (302, "warning")):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                result = self.run_check("muse", [response({"error": "test-key"}, status)])
                self.assertEqual(result.level, level)
                self.assertEqual(result.http_status, status)
                self.assertNotIn("test-key", repr(result))
                self.assertEqual(self.session.get.call_count, 1)

    def test_network_errors_are_actionable_and_redacted(self):
        for exc, word in ((requests.exceptions.ProxyError, "代理"), (requests.exceptions.SSLError, "证书"),
                          (requests.exceptions.Timeout, "超时"), (requests.exceptions.ConnectionError, "连接"),
                          (requests.exceptions.InvalidSchema, "协议")):
            with self.subTest(exc=exc):
                result = self.run_check(replies=[exc("secret URL=test-key")])
                self.assertEqual(result.level, "error")
                self.assertIn(word, result.message)
                self.assertNotIn("test-key", repr(result))
                self.assertIsNotNone(result.latency_ms)
                self.assertIn("直连", result.details[0])
                self.assertIn("GET /v1/video-generation-models", result.details[0])

    def test_connection_and_response_timeouts_have_distinct_advice(self):
        for exception, expected in ((requests.exceptions.ConnectTimeout, "建立网络连接超时"),
                                    (requests.exceptions.ReadTimeout, "等待服务响应超时")):
            for proxy_enabled in (False, True):
                with self.subTest(exception=exception, proxy=proxy_enabled):
                    self.session.get.reset_mock()
                    with patch.object(module.time, "perf_counter", side_effect=[10, 10.5]):
                        result = self.run_check(replies=[exception("test-key https://secret.invalid")],
                                                use_proxy=proxy_enabled, local_proxy="http://user:secret@127.0.0.1:7897")
                    self.assertEqual(result.latency_ms, 500)
                    self.assertIsNone(result.http_status)
                    self.assertIn(expected, result.message)
                    self.assertNotIn("已连接", result.message)
                    self.assertNotIn("test-key", repr(result))
                    self.assertNotIn("secret", repr(result))
                    self.assertIn("显式代理" if proxy_enabled else "直连", result.details[0])
                    self.assertIn("代理是否运行" if proxy_enabled else "不会自动应用", result.details[1])
                    self.assertEqual(self.session.get.call_count, 1)

    def test_streaming_read_timeout_wrapper_is_reported_as_body_timeout(self):
        # 使用 requests 自身的 iter_content 包装，覆盖真实的 ConnectionError(ReadTimeoutError)。
        reply = requests.Response()
        reply.status_code = 200
        reply.raw = Mock()
        reply.raw.stream.side_effect = ReadTimeoutError(None, "https://test-key.invalid", "test-key")
        result = self.run_check(replies=[reply])
        self.assertEqual(result.level, "error")
        self.assertEqual(result.http_status, 200)
        self.assertIn("读取响应正文超时", result.message)
        self.assertIn("已收到 HTTP 200", result.message)
        self.assertIsNotNone(result.latency_ms)
        self.assertNotIn("test-key", repr(result))
        self.assertEqual(self.session.get.call_count, 1)

    def test_fallback_timeout_clears_old_status_and_shows_actual_path(self):
        result = self.run_check(replies=[response({}, 404), requests.exceptions.ConnectTimeout("test-key")])
        self.assertEqual(result.level, "error")
        self.assertIsNone(result.http_status)
        self.assertIn("GET /v1/models", result.details[0])
        self.assertNotIn("video-generation-models", result.details[0])
        self.assertIsNotNone(result.latency_ms)
        self.assertEqual(self.session.get.call_count, 2)

    def test_diagnostic_path_omits_host_and_redacts_credentials(self):
        result = self.run_check(base_url="https://private-host.invalid/custom/test-key/v1",
                                use_proxy=True, local_proxy="http://username:proxy-password@127.0.0.1:7897")
        self.assertEqual(result.level, "success")
        self.assertIn("/custom/[已隐藏凭据]/v1/video-generation-models", result.details[0])
        for private in ("private-host", "test-key", "username", "proxy-password", "127.0.0.1"):
            self.assertNotIn(private, repr(result))

    def test_invalid_input_never_uses_network(self):
        for kwargs in ({"api_key": ""}, {"api_key": "test\nkey"}, {"base_url": "invalid"},
                       {"base_url": "https://example.invalid?key=test-key"}, {"base_url": "https://a:b@example.invalid"},
                       {"base_url": "https://example.invalid/v1/videos/generations"},
                       {"use_proxy": True, "local_proxy": ""}, {"use_proxy": True, "local_proxy": "invalid"}):
            with self.subTest(kwargs=kwargs):
                self.session.get.reset_mock()
                result = self.run_check(**kwargs)
                self.assertEqual(result.level, "error")
                self.assertIsNone(result.latency_ms)
                self.session.get.assert_not_called()

    def test_proxy_disabled_does_not_use_stale_address(self):
        self.run_check(use_proxy=False, local_proxy="http://user:password@127.0.0.1:19090")
        self.assertEqual(self.session.get.call_args.kwargs["proxies"], {})

    def test_wrong_or_oversized_response_is_not_green(self):
        for reply in (response(raw=b"<html>Login</html>"), response([]), response({"ok": True}),
                      response(raw=b"x" * (module.MAX_RESPONSE_BYTES + 1))):
            with self.subTest(body_size=len(reply.content)):
                result = self.run_check(replies=[reply])
                self.assertEqual(result.level, "warning")

    def test_model_names_cannot_reflect_key_or_markup(self):
        result = self.run_check(replies=[response({"models": [{"id": value} for value in ("grok-imagine-video", "test-key", "<script>alert(1)</script>")]})])
        self.assertEqual(result.model_ids, ("grok-imagine-video",))


class ConnectivityLocalHttpTest(unittest.TestCase):
    def test_real_http_fallback_does_not_submit_generation(self):
        """在本机模拟中转只提供 /models 的情况，验证真实 requests 的请求方式。"""
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.command, self.path, self.headers.get("Authorization")))
                if self.path == "/v1/video-generation-models":
                    code, data = 404, {"error": "not supported"}
                else:
                    code, data = 200, {"data": [{"id": "grok-imagine-video"}]}
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = check("xai", base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="local-test-key")
            self.assertEqual(result.level, "success")
            self.assertEqual([call[:2] for call in calls], [("GET", "/v1/video-generation-models"), ("GET", "/v1/models")])
            self.assertTrue(all(call[2] == "Bearer local-test-key" for call in calls))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
