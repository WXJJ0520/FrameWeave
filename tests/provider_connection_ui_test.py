"""连接按钮界面测试：所有查询均被替换，绝不读取真实配置或发出网络请求。"""

import copy
import runpy
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
# 复用纯内存管理器，不导入会初始化真实配置的应用模块。
MemoryConfigManager = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))[
    "MemoryConfigManager"
]


def make_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


def result(level="success", message="查询接口连接成功。"):
    return types.SimpleNamespace(
        level=level,
        message=message,
        details=("仅查询模型接口，尚未进行生成。",),
        latency_ms=125,
        http_status=200 if level == "success" else 403,
        model_ids=("test-model",),
    )


class ProviderConnectionUITest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({})
        self.original_config = copy.deepcopy(self.manager.config.model_dump())
        self.check = Mock(return_value=result())
        catalog_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]()
        modules = {
            "pixelle_video.services.api_services.model_catalog": catalog_fixture,
            "pixelle_video.utils.llm_util": runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["llm_util_test_module"](),
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.llm_presets": make_module(
                "pixelle_video.llm_presets",
                get_preset_names=lambda: [], get_preset=lambda name: {},
                find_preset_by_base_url_and_model=lambda url, model: None,
            ),
            "pixelle_video.services": make_module("pixelle_video.services", __path__=[]),
            "pixelle_video.services.api_services": make_module(
                "pixelle_video.services.api_services", __path__=[]
            ),
            "pixelle_video.services.api_services.connectivity": make_module(
                "pixelle_video.services.api_services.connectivity", check_provider_connection=self.check
            ),
            "web": make_module("web", __path__=[]),
            "web.i18n": make_module("web.i18n", tr=lambda key: key, get_language=lambda: "zh_CN"),
            "web.utils": make_module("web.utils", __path__=[]),
            "web.utils.streamlit_helpers": make_module("web.utils.streamlit_helpers", safe_rerun=lambda: None),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        settings_path = str(ROOT / "web/components/settings.py")
        script = f"import runpy\nrunpy.run_path({settings_path!r})['render_advanced_settings']()\n"
        self.app = AppTest.from_string(script).run()
        self.assertFalse(self.app.exception)

    def click(self, provider="xai"):
        self.app.button(key=f"api_media_{provider}_test").click().run()
        self.assertFalse(self.app.exception)

    def test_six_buttons_do_not_query_until_clicked(self):
        """进入设置页只展示按钮，不自动使用已有凭据进行测试。"""
        for provider in ("openai", "dashscope", "xai", "ark", "kling", "muse"):
            self.assertEqual(self.app.button(key=f"api_media_{provider}_test").label, "测试连接")
        self.check.assert_not_called()
        self.assertEqual(self.manager.saved, [])

    def test_all_buttons_pass_current_unsaved_credentials_and_proxy(self):
        """六家按钮均读取当前表单，而非已保存值，并保持各平台凭据独立。"""
        for provider in ("openai", "dashscope", "xai", "ark", "kling", "muse"):
            with self.subTest(provider=provider):
                self.check.reset_mock()
                self.app.text_input(key=f"api_media_{provider}_base_url").set_value(
                    f"https://unsaved-{provider}.example.invalid/v1"
                )
                self.app.checkbox(key=f"api_media_{provider}_use_proxy").set_value(True)
                self.app.text_input(key="api_media_local_proxy").set_value("http://127.0.0.1:19090")
                expected = {
                    "base_url": f"https://unsaved-{provider}.example.invalid/v1",
                    "api_key": "", "access_key": "", "secret_key": "",
                    "use_proxy": True, "local_proxy": "http://127.0.0.1:19090",
                }
                if provider == "kling":
                    for name in ("access_key", "secret_key"):
                        expected[name] = f"test-unsaved-kling-{name}"
                        self.app.text_input(key=f"api_media_kling_{name}").set_value(expected[name])
                else:
                    expected["api_key"] = f"test-unsaved-{provider}-key"
                    self.app.text_input(key=f"api_media_{provider}_key").set_value(expected["api_key"])
                self.click(provider)
                self.check.assert_called_once_with(provider, **expected)
                self.assertEqual(self.manager.saved, [])
                self.assertEqual(self.manager.config.model_dump(), self.original_config)

    def test_levels_timing_and_short_model_list_render(self):
        """按诊断级别显示结果，并限制页面上的模型列表长度。"""
        for level in ("success", "warning", "error"):
            with self.subTest(level=level):
                response = result(level, f"测试结果-{level}")
                response.model_ids = tuple(f"test-model-{index}" for index in range(7))
                self.check.return_value = response
                self.click()
                self.assertIn(f"测试结果-{level}", [item.value for item in getattr(self.app, level)])
                captions = "\n".join(item.value for item in self.app.caption)
                self.assertIn("125 ms", captions)
                self.assertIn("test-model-4", captions)
                self.assertNotIn("test-model-5", captions)
                self.assertEqual(self.manager.saved, [])

    def test_cached_result_disappears_when_connection_inputs_change(self):
        """同一输入可保留结果，修改地址、凭据或代理后旧状态立即失效。"""
        result_key = "api_media_xai_connection_result"
        self.click()
        checked_at = self.app.session_state[result_key]["checked_at"]
        self.app.run()
        self.check.assert_called_once()
        self.assertIn(result_key, self.app.session_state)
        self.assertEqual(self.app.session_state[result_key]["checked_at"], checked_at)
        changes = (
            ("text_input", "api_media_xai_key", "test-updated-private-key"),
            ("text_input", "api_media_xai_base_url", "https://changed.example.invalid/v1"),
            ("checkbox", "api_media_xai_use_proxy", True),
            ("text_input", "api_media_local_proxy", "http://127.0.0.1:19091"),
        )
        for widget_type, key, value in changes:
            with self.subTest(key=key):
                call_count = self.check.call_count
                getattr(self.app, widget_type)(key=key).set_value(value).run()
                self.assertFalse(self.app.exception)
                self.assertNotIn(result_key, self.app.session_state)
                self.assertEqual(self.check.call_count, call_count)
                self.click()
                # 缓存里仅保存摘要与诊断结果，不重复保存明文密钥。
                self.assertNotIn("test-updated-private-key", repr(self.app.session_state[result_key]))
                self.assertNotIn("api_key", self.app.session_state[result_key])

    def test_last_checked_time_is_displayed_in_beijing_time(self):
        """每次诊断标注北京时间，成功与异常结果都能区分历史状态。"""
        for fails in (False, True):
            with self.subTest(fails=fails):
                self.check.side_effect = RuntimeError("test-only failure") if fails else None
                self.click()
                timestamp = self.app.session_state["api_media_xai_connection_result"]["checked_at"]
                beijing_timezone = timezone(timedelta(hours=8))
                recorded_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=beijing_timezone
                )
                self.assertLess(abs((datetime.now(beijing_timezone) - recorded_time).total_seconds()), 60)
                captions = "\n".join(item.value for item in self.app.caption)
                self.assertIn(f"上次测试：{timestamp}（北京时间）", captions)

    def test_raw_exception_is_not_shown_or_saved(self):
        """底层异常即使含密钥，也只能显示通用错误，不能记录原始异常。"""
        leaked_value = "test-secret-must-not-appear"
        self.check.side_effect = RuntimeError(f"Authorization: Bearer {leaked_value}")
        self.click()
        self.assertEqual(len(self.app.error), 1)
        self.assertIn("连接测试未完成", self.app.error[0].value)
        self.assertNotIn(leaked_value, self.app.error[0].value)
        self.assertNotIn(leaked_value, repr(self.app.session_state["api_media_xai_connection_result"]))
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.config.model_dump(), self.original_config)

    def test_test_button_does_not_change_save_configuration_behavior(self):
        """诊断不保存；之后点保存配置仍按现有规则保存媒体参数。"""
        self.app.text_input(key="api_media_xai_key").set_value("test-xai-save-after-check")
        self.click()
        self.assertEqual(self.manager.saved, [])
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.error)
        self.assertEqual(len(self.manager.saved), 1)
        self.assertEqual(
            self.manager.saved[0]["api_providers"]["xai"]["api_key"], "test-xai-save-after-check"
        )
        self.check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
