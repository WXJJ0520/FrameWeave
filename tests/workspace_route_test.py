"""完整工作台入口回归：使用原表单与路由，隔离真实配置、模型和网络。"""

import ast
import asyncio
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
MemoryConfigManager = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["MemoryConfigManager"]


def module(name, **values):
    """模块替身只提供需要的依赖，避免导入核心时读取真实凭据。"""
    result = types.ModuleType(name)
    result.__dict__.update(values)
    return result


class WorkspaceRouteTest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({"api_providers": {"xai": {
            "api_key": "test-workspace-xai-key", "base_url": "https://xai.example.invalid/v1",
        }}})
        self.core = types.SimpleNamespace(history=types.SimpleNamespace(
            get_statistics=AsyncMock(return_value={"completed": 2, "failed": 1}),
            get_task_list=AsyncMock(return_value={"tasks": [], "total": 0, "total_pages": 1}),
            get_task_detail=AsyncMock(return_value=None),
        ))
        self.get_core = Mock(return_value=self.core)
        self.renderers = {
            name: types.SimpleNamespace(
                name=name, display_name=name, description=f"description:{name}",
                render=Mock(side_effect=lambda _, name=name: st.text(f"renderer:{name}")),
            )
            for name in ("quick_create", "custom_media", "digital_human", "image_to_video", "action_transfer")
        }
        self.get_pipeline = Mock(side_effect=self.renderers.get)
        self.connection = Mock(side_effect=AssertionError("打开配置不能自动发起连接检查"))
        catalog_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]()
        modules = {
            "pixelle_video.services.api_services.model_catalog": catalog_fixture,
            "pixelle_video.utils.llm_util": runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["llm_util_test_module"](),
            "web": module("web", __path__=[str(ROOT / "web")]),
            "web.components": module("web.components", __path__=[str(ROOT / "web/components")]),
            "web.utils": module("web.utils", __path__=[str(ROOT / "web/utils")]),
            "web.state": module("web.state", __path__=[str(ROOT / "web/state")]),
            "web.state.session": module(
                "web.state.session", init_session_state=lambda: st.session_state.setdefault("language", "zh_CN"),
                init_i18n=lambda: None, get_pixelle_video=self.get_core,
            ),
            "web.i18n": module(
                "web.i18n", tr=lambda key, **kwargs: key,
                get_language=lambda: st.session_state.get("language", "zh_CN"), set_language=lambda code: None,
            ),
            "web.pipelines": module(
                "web.pipelines", get_pipeline_ui=self.get_pipeline,
                get_all_pipeline_uis=lambda: list(self.renderers.values()),
            ),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run, get_project_version=lambda: "test"),
            "web.utils.streamlit_helpers": module("web.utils.streamlit_helpers", safe_rerun=st.rerun),
            "pixelle_video": module("pixelle_video", __path__=[]),
            "pixelle_video.config": module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.llm_presets": module(
                "pixelle_video.llm_presets", get_preset_names=lambda: [], get_preset=lambda name: {},
                find_preset_by_base_url_and_model=lambda url, model: None,
            ),
            "pixelle_video.services": module("pixelle_video.services", __path__=[]),
            "pixelle_video.services.api_services": module("pixelle_video.services.api_services", __path__=[]),
            "pixelle_video.services.api_services.connectivity": module(
                "pixelle_video.services.api_services.connectivity", check_provider_connection=self.connection,
            ),
        }
        # 清除本组会替换依赖的实际组件，避免前一测试留下模块全局配置对象。
        for key in list(sys.modules):
            if key.startswith(("web.components.", "web.utils.workspace_route")):
                modules[key] = None
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in [key for key, value in modules.items() if value is None]:
            sys.modules.pop(key, None)
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实网络请求"))
        self.network.start()
        self.addCleanup(self.network.stop)
        page_link_patch = patch("streamlit.page_link")
        page_link_patch.start()
        self.addCleanup(page_link_patch.stop)

    def open_tool(self, tool, language="zh_CN", embedded=True):
        """执行真实 Home 入口，让分派、初始化与设置保存都经过实际代码。"""
        script = f"import runpy\nrunpy.run_path({str(ROOT / 'web/pages/1_🎬_Home.py')!r}, run_name='__main__')\n"
        app = AppTest.from_string(script, default_timeout=10)
        if embedded:
            app.query_params["frameweave"] = "1"
        app.query_params["tool"] = tool
        app.query_params["language"] = language
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_all_tools_use_original_registered_renderers(self):
        """同时核对源文件注册名，避免路由与替身共享同一个错误映射。"""
        expected = {
            "standard": ("standard.py", "quick_create"),
            "asset_based": ("asset_based.py", "custom_media"),
            "digital_human": ("digital_human.py", "digital_human"),
            "i2v": ("i2v.py", "image_to_video"),
            "action_transfer": ("action_transfer.py", "action_transfer"),
        }
        for tool, (filename, registered) in expected.items():
            with self.subTest(tool=tool):
                tree = ast.parse((ROOT / "web/pipelines" / filename).read_text(encoding="utf-8"))
                names = [node.value.value for node in ast.walk(tree)
                         if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                         and any(isinstance(target, ast.Name) and target.id == "name" for target in node.targets)]
                self.assertIn(registered, names)
                for pipeline in self.renderers.values():
                    pipeline.render.reset_mock()
                app = self.open_tool(tool)
                self.get_pipeline.assert_called_with(registered)
                self.renderers[registered].render.assert_called_once_with(self.core)
                self.assertEqual(sum(item.render.call_count for item in self.renderers.values()), 1)
                self.assertNotIn("studio_language", [item.key for item in app.button_group])

    def test_settings_keep_all_providers_and_actual_save_callback(self):
        """工作台设置展示原表单，保存仍走原管理器，未打开创作核心或联网。"""
        app = self.open_tool("settings")
        self.get_core.assert_not_called()
        # API 提供商仍有子标签；顶层移除已撤下的工作流配置。
        self.assertTrue({"文本模型", "图片与视频", "网络与调试"}.issubset(
            {tab.label for tab in app.tabs}
        ))
        for key in ("api_media_openai_key", "api_media_xai_key", "api_media_muse_key",
                    "api_media_ark_key", "api_media_dashscope_key", "api_media_kling_access_key"):
            self.assertIsNotNone(app.text_input(key=key))
        self.assertNotIn("工作流", {tab.label for tab in app.tabs})
        self.assertTrue({"comfyui_url_input", "runninghub_api_key_input"}.isdisjoint({item.key for item in app.text_input}))
        app.text_input(key="api_media_xai_base_url").set_value("https://updated.example.invalid/v1").run()
        app.button(key="save_config_btn").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(self.manager.saved), 1)
        self.assertEqual(self.manager.saved[0]["api_providers"]["xai"]["base_url"], "https://updated.example.invalid/v1")
        self.assertEqual(self.manager.saved[0]["api_providers"]["xai"]["api_key"], "test-workspace-xai-key")
        self.assertTrue(any("配置已保存" in item.value for item in app.success))
        self.connection.assert_not_called()
        self.get_core.assert_not_called()

    def test_history_keeps_real_statistics_and_filters_in_main_area(self):
        app = self.open_tool("history")
        self.core.history.get_statistics.assert_awaited_once()
        self.core.history.get_task_list.assert_awaited_once()
        self.assertEqual(app.selectbox(key="filter_status").value, "all")
        self.assertEqual(len(app.sidebar.selectbox), 0)
        self.assertEqual(len(app.expander), 1)

    def test_language_is_whitelisted_before_render(self):
        app = self.open_tool("standard", "en_US")
        self.assertEqual(app.session_state["language"], "en_US")
        app = self.open_tool("standard", "../../anything")
        self.assertEqual(app.session_state["language"], "zh_CN")

    def test_history_refresh_reads_new_work_without_losing_filters(self):
        """在同一 iframe 会话新增作品，再点刷新，应重读数据并保留排序和筛选。"""
        app = self.open_tool("history")
        app.selectbox(key="filter_status").set_value("completed")
        app.selectbox(key="sort_by").set_value("title")
        app.selectbox(key="page_size").set_value(30).run()
        self.assertFalse(app.exception)
        self.core.history.get_task_list.reset_mock()
        self.core.history.get_task_list.return_value = {
            "tasks": [{"task_id": "offline-new-work", "title": "刷新后新增作品", "status": "completed"}],
            "total": 1, "total_pages": 1,
        }
        app.button(key="history_refresh_list").click().run()
        self.assertFalse(app.exception)
        self.core.history.get_task_list.assert_awaited_once_with(
            page=1, page_size=30, status="completed", sort_by="title", sort_order="desc",
        )
        self.assertEqual(app.selectbox(key="filter_status").value, "completed")
        self.assertEqual(app.selectbox(key="sort_by").value, "title")
        self.assertEqual(app.selectbox(key="page_size").value, 30)
        self.assertTrue(any("刷新后新增作品" in item.value for item in app.markdown))

    def test_standalone_entry_preserves_all_five_tabs(self):
        app = self.open_tool("digital_human", embedded=False)
        self.assertEqual(len(app.tabs), 5)
        for pipeline in self.renderers.values():
            pipeline.render.assert_called_once_with(self.core)
        self.assertIsNotNone(app.button(key="studio_settings_open"))

    def test_unknown_tool_falls_back_without_loading_arbitrary_paths(self):
        self.open_tool("../../private")
        self.get_pipeline.assert_called_once_with("quick_create")

    def test_ready_notification_only_accepts_local_origins(self):
        namespace = runpy.run_path(str(ROOT / "web/utils/workspace_route.py"))
        normalize = namespace["parent_origin"]
        self.assertEqual(normalize("http://127.0.0.1:8765"), "http://127.0.0.1:8765")
        self.assertEqual(normalize("http://localhost:5173/"), "http://localhost:5173")
        for invalid in ("https://example.com", "http://localhost.evil.invalid", "http://user@localhost:8765",
                        "javascript:alert(1)", "http://localhost:bad", "http://localhost:8765/private", "http://localhost/?key=secret"):
            self.assertIsNone(normalize(invalid))


if __name__ == "__main__":
    unittest.main()
