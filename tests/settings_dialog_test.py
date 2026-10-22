"""设置弹窗行为回归：真实弹窗与表单，内存配置，无真实凭据、文件保存或网络请求。"""

import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
# 复用已经隔离 schema 初始化的内存配置替身，不导入实际 config_manager。
MemoryConfigManager = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["MemoryConfigManager"]


def make_module(name, **attributes):
    """用模块替身隔离所有可能初始化真实配置或访问服务的依赖。"""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class SettingsDialogTest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({
            "api_providers": {"xai": {
                "api_key": "test-saved-xai-key", "base_url": "https://xai.example.invalid/v1",
            }},
        })
        self.check_connection = Mock(side_effect=AssertionError("本测试不得触发连接检查"))
        catalog_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]()
        modules = {
            "pixelle_video.services.api_services.model_catalog": catalog_fixture,
            "pixelle_video.utils.llm_util": runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["llm_util_test_module"](),
            "web": make_module("web", __path__=[str(ROOT / "web")]),
            "web.components": make_module("web.components", __path__=[str(ROOT / "web/components")]),
            "web.i18n": make_module("web.i18n", tr=lambda key, **kwargs: key, get_language=lambda: "zh_CN"),
            "web.utils": make_module("web.utils", __path__=[]),
            "web.utils.streamlit_helpers": make_module("web.utils.streamlit_helpers", safe_rerun=st.rerun),
            "web.utils.async_helpers": make_module("web.utils.async_helpers", get_project_version=lambda: "test"),
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.llm_presets": make_module(
                "pixelle_video.llm_presets", get_preset_names=lambda: [], get_preset=lambda name: {},
                find_preset_by_base_url_and_model=lambda url, model: None,
            ),
            "pixelle_video.services": make_module("pixelle_video.services", __path__=[]),
            "pixelle_video.services.api_services": make_module("pixelle_video.services.api_services", __path__=[]),
            "pixelle_video.services.api_services.connectivity": make_module(
                "pixelle_video.services.api_services.connectivity", check_provider_connection=self.check_connection,
            ),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        # 即使未来表单误加了自动请求，也不允许测试触达网络，并明确检查调用次数。
        network_patch = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实网络请求"))
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)
        script = (
            "import streamlit as st\n"
            "from web.components.settings_dialog import (render_settings_launcher, "
            "render_pending_settings_dialog, _dismiss_settings)\n"
            "from web.components.content_input import render_content_input\n"
            "render_settings_launcher()\n"
            # 与 web/app.py 保持一致：先登记页面表单，再处理弹窗内可能触发的 rerun。
            "render_content_input()\n"
            "render_pending_settings_dialog()\n"
            # AppTest 1.53.1 没有原生 X/Escape 入口；只以测试按钮触发同一真实回调。
            # 原生按钮与浏览器事件的绑定由实际浏览器检查，不在这里声称覆盖。
            "st.button('模拟原生关闭回调', key='test_native_dismiss', on_click=_dismiss_settings)\n"
        )
        self.app = AppTest.from_string(script, default_timeout=5).run()
        self.assert_clean()

    def assert_clean(self):
        """任何普通交互都不得联网，测试输入全部采用明显的虚构值。"""
        self.assertFalse(self.app.exception)
        self.check_connection.assert_not_called()
        self.network.assert_not_called()

    def open_settings(self):
        self.app.button(key="studio_settings_open").click().run()
        self.assert_clean()
        self.assertTrue(self.app.session_state["_studio_settings_open"])
        self.assertEqual(len(self.app.get("dialog")), 1)

    def enter_main_draft(self):
        """使用真实创作输入，验证弹窗操作不会清除主页面的未提交内容。"""
        self.app.text_area(key="quick_create_text").set_value("未来失物招领处的未提交脚本")
        self.app.text_input(key="quick_create_title").set_value("十分钟")
        self.app.slider(key="quick_create_n_scenes").set_value(7).run()
        self.assert_clean()

    def assert_main_draft(self):
        self.assertEqual(self.app.text_area(key="quick_create_text").value, "未来失物招领处的未提交脚本")
        self.assertEqual(self.app.text_input(key="quick_create_title").value, "十分钟")
        self.assertEqual(self.app.slider(key="quick_create_n_scenes").value, 7)

    def test_open_only_renders_settings_without_saving_or_connecting(self):
        """打开前不加载设置正文，打开后只展示配置，不能隐式保存或发起测试。"""
        self.assertEqual(len(self.app.get("dialog")), 0)
        self.assertNotIn("web.components.settings", sys.modules)
        self.enter_main_draft()
        self.open_settings()
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "test-saved-xai-key")
        self.assertEqual(self.manager.saved, [])
        self.assert_main_draft()

    def test_close_and_reopen_preserves_unsaved_settings_and_main_draft(self):
        """关闭仅保留本会话设置草稿，重开恢复草稿且不覆盖已保存配置。"""
        self.enter_main_draft()
        self.open_settings()
        self.app.text_input(key="api_media_xai_key").set_value("test-unsaved-xai-key")
        self.app.text_input(key="api_media_local_proxy").set_value("http://127.0.0.1:9999").run()
        self.app.button(key="studio_settings_close").click().run()
        self.assert_clean()
        self.assertFalse(self.app.session_state["_studio_settings_open"])
        self.assertEqual(len(self.app.get("dialog")), 0)
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.config.api_providers.xai.api_key, "test-saved-xai-key")
        draft = self.app.session_state["_studio_settings_draft"]
        self.assertEqual(draft["api_media_xai_key"], "test-unsaved-xai-key")
        self.assertNotIn("quick_create_text", draft)
        self.assertNotIn("studio_settings_close", draft)
        self.assert_main_draft()
        self.open_settings()
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "test-unsaved-xai-key")
        self.assertEqual(self.app.text_input(key="api_media_local_proxy").value, "http://127.0.0.1:9999")
        self.assert_main_draft()

    def test_native_dismiss_callback_closes_without_reopening_and_keeps_draft(self):
        """触发真实原生关闭回调后，全页刷新不能再次弹出或保存设置。"""
        self.enter_main_draft()
        self.open_settings()
        self.app.text_input(key="api_media_xai_key").set_value("test-dismissed-draft").run()
        self.app.button(key="test_native_dismiss").click().run()
        self.app.run()
        self.assert_clean()
        self.assertEqual(len(self.app.get("dialog")), 0)
        self.assertFalse(self.app.session_state["_studio_settings_open"])
        self.assertEqual(self.manager.saved, [])
        self.assert_main_draft()
        self.open_settings()
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "test-dismissed-draft")

    def test_vision_model_lists_survive_close_without_implicit_save(self):
        """新视觉模型名字段使用同一草稿流程，关闭、重开不丢失也不写入配置。"""
        self.open_settings()
        self.app.text_area(key="api_media_openai_vision_models").set_value("test-openai-vision\ntest-other-vision")
        self.app.text_area(key="api_media_dashscope_vision_models").set_value("test-qwen-vision").run()
        self.app.button(key="studio_settings_close").click().run()
        self.assert_clean()
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.config.api_providers.openai.vision_models, [])
        self.open_settings()
        self.assertEqual(self.app.text_area(key="api_media_openai_vision_models").value, "test-openai-vision\ntest-other-vision")
        self.assertEqual(self.app.text_area(key="api_media_dashscope_vision_models").value, "test-qwen-vision")

    def test_loaded_catalog_survives_dismiss_as_an_unsaved_draft(self):
        """完整目录与历史手填值一起保留，重开弹窗不重新查询或隐式保存。"""
        load = Mock(return_value=["gpt-6.1-sol", "relay-vision-alias"])
        catalog = sys.modules["pixelle_video.services.api_services.model_catalog"]
        with patch.object(catalog, "load_provider_model_ids", load):
            self.open_settings()
            self.app.text_input(key="api_media_openai_key").set_value("test-vision-catalog-key")
            self.app.text_area(key="api_media_openai_vision_models").set_value("manual-vision-alias")
            self.app.button(key="api_media_openai_load_models").click().run()
            self.app.button(key="studio_settings_close").click().run()
            self.assert_clean()
            self.assertEqual(self.manager.saved, [])
            self.open_settings()
            self.assertEqual(self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"]["models"], ["gpt-6.1-sol", "relay-vision-alias"])
            self.assertEqual(self.app.text_area(key="api_media_openai_vision_models").value, "manual-vision-alias")
            load.assert_called_once()

    def test_save_closes_clears_settings_draft_and_reopens_from_saved_configuration(self):
        """保存成功关闭弹窗；再次打开从当前配置读取，不继续使用上次编辑缓存。"""
        self.enter_main_draft()
        self.open_settings()
        self.app.text_input(key="api_media_xai_key").set_value("test-new-saved-key")
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-new-llm-key")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://llm.example.invalid/v1")
        self.app.text_input(key="llm_custom_model_input_Custom").set_value("test-new-script-model")
        self.app.button(key="save_config_btn").click().run()
        self.assert_clean()
        self.assertFalse(self.app.error)
        self.assertEqual(len(self.manager.saved), 1)
        self.assertEqual(self.manager.saved[-1]["api_providers"]["xai"]["api_key"], "test-new-saved-key")
        # 保存后的消费方从配置管理器读取新模型；不依赖刚才的表单变量或草稿缓存。
        self.assertEqual(self.manager.get_llm_config(), {
            "api_key": "test-new-llm-key", "base_url": "https://llm.example.invalid/v1",
            "model": "test-new-script-model",
            "model_catalog": {},
        })
        self.assertFalse(self.app.session_state["_studio_settings_open"])
        self.assertNotIn("_studio_settings_draft", self.app.session_state)
        self.assertEqual(len(self.app.get("dialog")), 0)
        self.assert_main_draft()
        # 模拟配置管理器被同会话另一入口更新，重开必须读取配置而非旧 widget 缓存。
        self.manager.set_api_provider_config("xai", {"api_key": "test-latest-stored-key"})
        self.open_settings()
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "test-latest-stored-key")
        self.assertEqual(self.app.text_input(key="llm_custom_model_input_Custom").value, "test-new-script-model")
        self.assertEqual(len(self.manager.saved), 1)
        self.assert_main_draft()

    def test_failed_save_keeps_dialog_open_and_retains_editing_state(self):
        """保存失败不能误报成功关闭，也不能丢失正在编辑的设置和主创作稿件。"""
        self.enter_main_draft()
        self.open_settings()
        self.app.text_input(key="api_media_xai_key").set_value("test-retry-key")
        with patch.object(self.manager, "save", side_effect=OSError("模拟保存失败")):
            self.app.button(key="save_config_btn").click().run()
        self.assert_clean()
        self.assertTrue(self.app.error)
        self.assertTrue(self.app.session_state["_studio_settings_open"])
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "test-retry-key")
        self.assertEqual(self.manager.saved, [])
        self.assert_main_draft()


if __name__ == "__main__":
    unittest.main()
