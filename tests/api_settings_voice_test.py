"""API 设置与在线配音回归：隔离真实配置、请求和用户素材。"""

import asyncio
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
fixtures = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))
MemoryConfigManager = fixtures["MemoryConfigManager"]
PixelleVideoConfig = fixtures["PixelleVideoConfig"]


def module(name, **values):
    """替换带初始化副作用的导入，避免读取用户配置。"""
    result = types.ModuleType(name)
    result.__dict__.update(values)
    return result


class APISettingsVoiceTest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({
            "comfyui": {
                "comfyui_api_key": "test-old-comfy-key",
                "runninghub_api_key": "test-old-cloud-key",
                "tts": {
                    "inference_mode": "comfyui",
                    "local": {"voice": "test-voice-2", "speed": 1.4},
                },
            },
            "api_providers": {
                "xai": {"api_key": "test-xai-key", "base_url": "https://xai.example.invalid/v1"},
                "muse": {"api_key": "test-muse-key", "base_url": "https://muse.example.invalid/v1"},
            },
        })
        self.original_legacy = self.manager.config.comfyui.model_dump()
        self.core = types.SimpleNamespace(tts=AsyncMock(return_value=None))
        catalog_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]()
        modules = {
            "pixelle_video.services.api_services.model_catalog": catalog_fixture,
            "pixelle_video.utils.llm_util": runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["llm_util_test_module"](),
            "pixelle_video": module("pixelle_video", __path__=[]),
            "pixelle_video.config": module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.config.schema": module("pixelle_video.config.schema", PixelleVideoConfig=PixelleVideoConfig),
            "pixelle_video.llm_presets": module(
                "pixelle_video.llm_presets", get_preset_names=lambda: [],
                get_preset=lambda name: {}, find_preset_by_base_url_and_model=lambda *_: None,
            ),
            "pixelle_video.tts_voices": module(
                "pixelle_video.tts_voices", EDGE_TTS_VOICES=[{"id": "test-voice-1"}, {"id": "test-voice-2"}],
                get_voice_display_name=lambda voice_id, *_: voice_id,
            ),
            "web": module("web", __path__=[]),
            "web.i18n": module("web.i18n", tr=lambda key, **_: key, get_language=lambda: "zh_CN"),
            "web.utils": module("web.utils", __path__=[]),
            "web.utils.streamlit_helpers": module("web.utils.streamlit_helpers", safe_rerun=lambda: None),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run),
            "api_test_core": module("api_test_core", core=self.core),
        }
        imports = patch.dict(sys.modules, modules)
        imports.start()
        self.addCleanup(imports.stop)
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实联网"))
        network.start()
        self.addCleanup(network.stop)

    def settings(self):
        """运行真实组件，仅保存到内存管理器。"""
        path = str(ROOT / "web/components/settings.py")
        app = AppTest.from_string(
            f"import runpy\nrunpy.run_path({path!r})['render_advanced_settings']()\n"
        ).run()
        self.assertFalse(app.exception)
        return app

    def test_only_api_settings_visible_and_save_preserves_legacy_credentials(self):
        app = self.settings()
        labels = {tab.label for tab in app.tabs}
        self.assertTrue({"文本模型", "图片与视频", "网络与调试"}.issubset(labels))
        self.assertTrue({"工作流", "ComfyUI", "RunningHub"}.isdisjoint(labels))
        keys = {item.key for item in app.text_input}
        self.assertTrue({"comfyui_url_input", "comfyui_api_key_input", "runninghub_api_key_input"}.isdisjoint(keys))
        app.text_input(key="api_media_xai_base_url").set_value("https://changed.example.invalid/v1").run()
        # 不同平台草稿独立，修改其中一个字段后重渲染不会覆盖另一个。
        self.assertEqual(app.text_input(key="api_media_muse_key").value, "test-muse-key")
        app.button(key="save_config_btn").click().run()
        self.assertFalse(app.exception)
        saved = self.manager.saved[-1]
        self.assertEqual(saved["comfyui"], self.original_legacy)
        self.assertEqual(saved["api_providers"]["xai"]["base_url"], "https://changed.example.invalid/v1")
        self.assertEqual(saved["api_providers"]["muse"]["api_key"], "test-muse-key")

    def test_reset_only_changes_editable_api_settings(self):
        app = self.settings()
        app.button(key="reset_config_btn").click().run()
        self.assertFalse(app.exception)
        saved = self.manager.saved[-1]
        self.assertEqual(saved["comfyui"], self.original_legacy)
        self.assertEqual(saved["api_providers"]["xai"]["api_key"], "")
        self.assertEqual(saved["api_providers"]["muse"]["api_key"], "")

    def voice(self):
        path = str(ROOT / "web/components/digital_tts_config.py")
        app = AppTest.from_string(
            "import runpy\nimport streamlit as st\nfrom api_test_core import core\n"
            f"result = runpy.run_path({path!r})['render_style_config'](core)\n"
            "st.session_state['_voice_result'] = result\n"
        )
        # 模拟升级前留在旧工作流模式的页面会话。
        app.session_state["digital_tts_inference_mode"] = "comfyui"
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_old_session_normalized_to_online_voice_without_automatic_request(self):
        app = self.voice()
        self.assertEqual(app.session_state["digital_tts_inference_mode"], "local")
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(len(app.get("file_uploader")), 0)
        self.assertTrue(any("在线语音接口" in item.value for item in app.caption))
        self.assertEqual(app.session_state["_voice_result"], {
            "tts_inference_mode": "local", "tts_voice": "test-voice-2", "tts_speed": 1.4,
            "tts_workflow": None, "ref_audio": None,
        })
        self.core.tts.assert_not_awaited()
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.config.comfyui.model_dump(), self.original_legacy)

    def test_voice_preview_uses_only_online_adapter_and_current_inputs(self):
        app = self.voice()
        app.selectbox(key="digital_tts_local_voice").set_value("test-voice-1")
        app.slider(key="digital_tts_local_speed").set_value(1.1)
        app.text_input(key="digital_tts_preview_text").set_value("这是一段离线测试输入。")
        app.button(key="gidital_preview_tts").click().run()
        self.assertFalse(app.exception)
        self.core.tts.assert_awaited_once_with(
            text="这是一段离线测试输入。", inference_mode="local", voice="test-voice-1", speed=1.1,
        )

    def test_preview_error_does_not_reveal_signed_service_url(self):
        app = self.voice()
        self.core.tts.side_effect = RuntimeError("https://service.invalid/?token=test-sensitive-value")
        app.button(key="gidital_preview_tts").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.error), 1)
        self.assertNotIn("test-sensitive-value", app.error[0].value)
        self.assertIn("在线语音试听失败", app.error[0].value)


if __name__ == "__main__":
    unittest.main()
