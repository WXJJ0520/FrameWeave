"""设置用途和视觉模型列表回归：使用真实控件、虚构凭据与内存配置，禁止联网。"""

import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["ProviderSettingsTest"]


class SettingsUsageVisionTest(unittest.TestCase):
    _set_up = _fixture.setUp
    save = _fixture.save

    def setUp(self):
        # 在渲染组件之前禁用网络；所有凭据都是隔离测试数据。
        network_patch = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实网络"))
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)
        self._set_up()

    def tearDown(self):
        self.network.assert_not_called()

    def test_feature_map_and_provider_usage_are_specific_and_bilingual(self):
        """用途映射不将媒体 API 当成文本模型，也不声称所有服务支持数字人。"""
        self.assertIn("按功能找配置", {item.label for item in self.app.expander})
        captions = "\n".join(item.value for item in self.app.caption)
        markdown = "\n".join(item.value for item in self.app.markdown)
        self.assertIn("这里的密钥与下方 OpenAI 图片/视觉分析配置独立", captions)
        self.assertIn("视频抽帧理解", captions)
        self.assertIn("Seedream 图片生成", captions)
        self.assertIn("无需 API 密钥，仍需联网", markdown)
        self.assertIn("数字人口播、动作迁移 | **图片与视频 → 通义**", markdown)
        sys.modules["web.i18n"].get_language = lambda: "en_US"
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertIn("Find settings by feature", {item.label for item in self.app.expander})
        captions = "\n".join(item.value for item in self.app.caption)
        self.assertIn("Credentials are separate from the Text models tab", captions)
        self.assertEqual(self.app.text_area(key="api_media_openai_vision_models").label, "Legacy vision model IDs")

    def test_custom_models_save_in_order_with_independent_credentials(self):
        """视觉目录按提供商保存，去除空行重复，文本密钥及隐藏配置保持原样。"""
        self.app.text_area(key="api_media_openai_vision_models").set_value(
            "  compatible-vision-v2  \n\ncompatible-vision-v1\ncompatible-vision-v2\n"
        )
        self.app.text_area(key="api_media_dashscope_vision_models").set_value("qwen-test-vl\nqwen-test-vl")
        self.app.text_input(key="api_media_openai_key").set_value("test-openai-vision-key")
        self.app.text_input(key="api_media_dashscope_key").set_value("test-dashscope-vision-key")
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-text-only-key")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://text.example.invalid/v1")
        self.app.text_input(key="llm_custom_model_input_Custom").set_value("test-text-model")
        saved = self.save()
        self.assertEqual(saved["api_providers"]["openai"]["vision_models"], ["compatible-vision-v2", "compatible-vision-v1"])
        self.assertEqual(saved["api_providers"]["dashscope"]["vision_models"], ["qwen-test-vl"])
        self.assertEqual(saved["api_providers"]["openai"]["api_key"], "test-openai-vision-key")
        self.assertEqual(saved["api_providers"]["dashscope"]["api_key"], "test-dashscope-vision-key")
        self.assertEqual(saved["llm"]["api_key"], "test-text-only-key")
        for provider in ("deepseek", "gemini", "ark", "kling"):
            self.assertEqual(saved["api_providers"][provider], {**self.original_providers[provider], "model_catalog": {}})

    def test_existing_custom_models_load_and_empty_lists_restore_builtins(self):
        """保存过的模型名可回读；清空仅重置视觉目录，不清除凭据。"""
        self.manager.set_api_provider_config("openai", {"vision_models": ["saved-vision-model"]})
        self.manager.set_api_provider_config("dashscope", {"vision_models": ["saved-qwen-model"]})
        script = f"import runpy\nrunpy.run_path({str(ROOT / 'web/components/settings.py')!r})['render_advanced_settings']()\n"
        self.app = AppTest.from_string(script).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.text_area(key="api_media_openai_vision_models").value, "saved-vision-model")
        self.assertEqual(self.app.text_area(key="api_media_dashscope_vision_models").value, "saved-qwen-model")
        self.app.text_area(key="api_media_openai_vision_models").set_value(" \n ")
        self.app.text_area(key="api_media_dashscope_vision_models").set_value("")
        saved = self.save()
        for provider in ("openai", "dashscope"):
            self.assertEqual(saved["api_providers"][provider]["vision_models"], [])
            self.assertEqual(saved["api_providers"][provider]["api_key"], self.original_providers[provider]["api_key"])

    def test_legacy_config_without_vision_fields_renders_and_saves(self):
        """兼容未声明视觉目录的旧管理器输出，不要求用户手工改配置文件。"""
        legacy = self.manager.get_api_providers_config()
        for provider in ("openai", "dashscope"):
            legacy[provider].pop("vision_models", None)
        with patch.object(self.manager, "get_api_providers_config", return_value=legacy):
            self.app.run()
            self.assertFalse(self.app.exception)
            self.assertEqual(self.app.text_area(key="api_media_openai_vision_models").value, "")
            self.assertEqual(self.app.text_area(key="api_media_dashscope_vision_models").value, "")
            saved = self.save()
        self.assertEqual(saved["api_providers"]["openai"]["vision_models"], [])
        self.assertEqual(saved["api_providers"]["dashscope"]["vision_models"], [])


# 只复用 fixture 方法，不让 pytest 重复收集源测试类。
del _fixture


if __name__ == "__main__":
    unittest.main()
