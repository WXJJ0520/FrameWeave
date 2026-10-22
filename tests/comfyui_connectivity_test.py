"""ComfyUI 连通诊断回归：完全替换网络与配置，不访问用户服务或真实凭据。"""

import copy
import errno
import runpy
import socket
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import requests
from streamlit.testing.v1 import AppTest
from urllib3.exceptions import ReadTimeoutError

from web.utils.comfyui_connectivity import (
    ConnectionResult,
    check_comfyui_connection,
    validate_base_url,
)

ROOT = Path(__file__).resolve().parents[1]
MemoryConfigManager = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))[
    "MemoryConfigManager"
]


def module(name, **attributes):
    """只提供设置组件需要的依赖，阻止初始化真实配置管理器。"""
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class ComfyUIConnectivityTest(unittest.TestCase):
    def setUp(self):
        self.response = MagicMock(status_code=200)
        self.response.json.return_value = {"system": {"os": "test"}, "devices": []}
        self.session = MagicMock()
        self.session.get.return_value.__enter__.return_value = self.response
        self.session_factory = patch("requests.Session")
        factory = self.session_factory.start()
        factory.return_value.__enter__.return_value = self.session
        self.addCleanup(self.session_factory.stop)

    def test_invalid_addresses_do_not_send_any_request(self):
        """空地址、错误协议、凭据地址和具体查询端点均在联网前阻止。"""
        for address in (
            "",
            "127.0.0.1:8188",
            "ftp://host.invalid",
            "https://host.invalid:wrong",
            "https://host.invalid:99999",
            "https://user:secret@host.invalid",
            "https://host.invalid?key=test",
            "https://host.invalid/#settings",
            "http://host.invalid /comfy",
            "http://host.invalid/\ncomfy",
            "http://host.invalid/system_stats",
            "https://[broken",
        ):
            with self.subTest(address=address):
                self.assertEqual(check_comfyui_connection(address).level, "error")
        self.session.get.assert_not_called()

    def test_proxy_prefix_is_preserved_and_current_key_is_used_once(self):
        """合法反代路径保持原样，使用 ComfyKit 同款 Bearer 鉴权，禁止隐式重定向。"""
        result = check_comfyui_connection(" https://proxy.example.invalid/comfy/v1/ ", "test-key")
        self.assertEqual(result.code, "ok")
        self.session.get.assert_called_once_with(
            "https://proxy.example.invalid/comfy/v1/system_stats",
            headers={"Authorization": "Bearer test-key"},
            timeout=(5, 10),
            allow_redirects=False,
        )
        self.assertFalse(self.session.trust_env)
        self.assertNotIn("test-key", repr(result))

    def test_local_unauthenticated_server_needs_no_key(self):
        """未设置鉴权的本地 ComfyUI 不强制要求密钥。"""
        result = check_comfyui_connection("http://127.0.0.1:8188")
        self.assertEqual(result.code, "ok")
        self.assertEqual(self.session.get.call_args.kwargs["headers"], {})

    def test_control_characters_in_key_do_not_send_a_request(self):
        """无效请求头不能触发网络或把原始异常带回界面。"""
        self.assertEqual(
            check_comfyui_connection("http://localhost:8188", "test\nsecret").code, "key"
        )
        self.session.get.assert_not_called()

    def test_website_html_and_other_json_are_not_false_success(self):
        """返回网站首页/登录页或其他 API JSON 不等于 ComfyUI 查询成功。"""
        for payload in ({"data": []}, [], {"system": "wrong-type"}):
            with self.subTest(payload=payload):
                self.response.json.return_value = payload
                self.assertEqual(
                    check_comfyui_connection("http://localhost:8188").code, "unexpected"
                )
        self.response.json.side_effect = ValueError("<html>test-private-body</html>")
        result = check_comfyui_connection("http://localhost:8188")
        self.assertEqual(result.level, "warning")
        self.assertNotIn("test-private-body", repr(result.text()))

    def test_http_failures_offer_status_specific_next_steps(self):
        """认证、路径和上游错误分开表达，但不把 HTTP 状态当成根因证据。"""
        for status, code in (
            (401, "auth"),
            (403, "auth"),
            (404, "missing"),
            (502, "upstream"),
            (503, "upstream"),
            (504, "upstream"),
            (302, "redirect"),
            (429, "http"),
            (500, "http"),
        ):
            with self.subTest(status=status):
                self.response.status_code = status
                result = check_comfyui_connection("https://proxy.example.invalid")
                self.assertEqual((result.code, result.http_status), (code, status))
                self.assertTrue(all(result.text()))
                self.assertTrue(all(result.text(False)))

    def test_network_exceptions_are_classified_without_raw_error_text(self):
        """保留可证实的网络类别，不从原异常字符串猜测原因或泄漏密钥。"""
        refused = requests.ConnectionError(OSError(errno.ECONNREFUSED, "test-secret"))
        dns = requests.ConnectionError(socket.gaierror(socket.EAI_NONAME, "test-secret"))
        for error, code in (
            (requests.ConnectTimeout("test-secret"), "timeout"),
            (requests.ReadTimeout("test-secret"), "timeout"),
            (requests.exceptions.SSLError("test-secret"), "tls"),
            (refused, "refused"),
            (dns, "dns"),
            (requests.ConnectionError("test-secret"), "connection"),
            (RuntimeError("Authorization: Bearer test-secret"), "unknown"),
        ):
            with self.subTest(code=code):
                self.session.get.reset_mock()
                self.session.get.side_effect = error
                result = check_comfyui_connection("https://proxy.example.invalid")
                self.assertEqual(result.code, code)
                self.session.get.assert_called_once()
                self.assertNotIn("test-secret", repr(result.text()))

    def test_connection_success_explains_workflow_has_not_been_validated(self):
        """成功只表达 API 可访问，不替用户保证工作流、节点、模型完整。"""
        result = check_comfyui_connection("http://localhost:8188")
        self.assertIn("仅确认服务 API 可访问", result.text()[1])
        self.assertIn("工作流", result.text()[1])
        self.assertIn("only checks API access", result.text(False)[1])
        self.assertEqual(
            validate_base_url("https://host.invalid/path/v1/")[0], "https://host.invalid/path/v1"
        )

    def test_response_body_read_timeout_uses_requests_real_exception_wrapping(self):
        """经过 Requests 的真实响应体读取逻辑，覆盖其 ConnectionError 包装路径。"""
        response = requests.Response()
        response.status_code = 200
        response.raw = Mock()
        response.raw.stream.side_effect = ReadTimeoutError(
            None, "/system_stats?key=test-secret", "private response detail"
        )

        def consume_body(*args, **kwargs):
            # stream=False 的 Session.get 返回前会消费响应体；此处只消费内存替身。
            response.content
            return response

        self.session.get.side_effect = consume_body
        result = check_comfyui_connection("https://proxy.example.invalid/comfy")
        self.assertEqual(result.code, "timeout")
        self.session.get.assert_called_once()
        self.assertNotIn("test-secret", repr(result))
        self.assertNotIn("private response detail", repr(result.text()))

    def test_generic_connection_error_text_does_not_imply_timeout(self):
        """异常正文即使写了 timeout，也不能替代可确认的异常类型。"""
        self.session.get.side_effect = requests.ConnectionError("read timeout: test-secret")
        result = check_comfyui_connection("https://proxy.example.invalid")
        self.assertEqual(result.code, "connection")
        self.assertNotIn("test-secret", repr(result.text()))


class ComfyUIConnectionUITest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({})
        self.original = copy.deepcopy(self.manager.config.model_dump())
        self.check = Mock(return_value=ConnectionResult("ok", 200))
        catalog_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]()
        modules = {
            "pixelle_video.services.api_services.model_catalog": catalog_fixture,
            "pixelle_video.utils.llm_util": runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["llm_util_test_module"](),
            "pixelle_video": module("pixelle_video", __path__=[]),
            "pixelle_video.config": module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.llm_presets": module(
                "pixelle_video.llm_presets",
                get_preset_names=lambda: [],
                get_preset=lambda name: {},
                find_preset_by_base_url_and_model=lambda *args: None,
            ),
            "web": module("web", __path__=[]),
            "web.i18n": module("web.i18n", tr=lambda key: key, get_language=lambda: "zh_CN"),
            "web.utils": module("web.utils", __path__=[]),
            "web.utils.streamlit_helpers": module(
                "web.utils.streamlit_helpers", safe_rerun=lambda: None
            ),
            "web.utils.comfyui_connectivity": module(
                "web.utils.comfyui_connectivity",
                check_comfyui_connection=self.check,
            ),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        settings_path = str(ROOT / "web/components/settings.py")
        self.app = AppTest.from_string(
            f"import runpy\nrunpy.run_path({settings_path!r})['render_advanced_settings']()\n"
        ).run()
        self.assertFalse(self.app.exception)

    def test_removed_workflow_controls_do_not_query_or_mutate_legacy_config(self):
        """旧诊断 helper 保留兼容测试，但 API 工作台不再展示或调用它。"""
        keys = {item.key for item in self.app.text_input}
        self.assertTrue({"comfyui_url_input", "comfyui_api_key_input", "runninghub_api_key_input"}.isdisjoint(keys))
        self.assertNotIn("test_comfyui", {item.key for item in self.app.button})
        self.assertNotIn("工作流", {tab.label for tab in self.app.tabs})
        self.check.assert_not_called()
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.config.model_dump(), self.original)


if __name__ == "__main__":
    unittest.main()
