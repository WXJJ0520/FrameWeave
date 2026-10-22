"""原有创作页面的 API-only 回归，真实控件渲染且禁止网络与真实生成。"""

import asyncio
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
MemoryConfigManager = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["MemoryConfigManager"]


def module(name, **attributes):
    """有初始化副作用的依赖用内存替身，选择器与 API 能力过滤仍执行真实代码。"""
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class APISharedUITest(unittest.TestCase):
    def setUp(self):
        self.manager = MemoryConfigManager({"comfyui": {
            "tts": {"inference_mode": "comfyui"},
            "image": {"default_workflow": "runninghub/old-image.json"},
            "video": {"default_workflow": "selfhost/old-video.json"},
        }})
        self.manager.validate = Mock(return_value=True)
        self.api_models = [
            {"key": "api/test/image-a", "display_name": "测试图像 A", "media_type": "image"},
            {"key": "api/test/image-b", "display_name": "测试图像 B", "media_type": "image"},
            {"key": "api/test/video", "display_name": "测试视频", "media_type": "video",
             "adapter_ability_types": ["text_to_video", "first_frame_i2v"], "api_contract_verified": True},
            # 故意混入旧来源，验证真实 API 列表函数会过滤它们。
            {"key": "runninghub/old-image.json", "display_name": "RunningHub", "media_type": "image"},
            {"key": "selfhost/old-video.json", "display_name": "ComfyUI", "media_type": "video"},
        ]
        self.vlm_models = [{"display_name": "测试视觉模型", "model": "test-vlm"}]
        self.media = AsyncMock()
        self.media.list_workflows = Mock(side_effect=AssertionError("不得回退到旧工作流列表"))
        self.core = types.SimpleNamespace(
            config={}, media=self.media, tts=AsyncMock(),
            api_media=types.SimpleNamespace(
                list_available_workflows=Mock(side_effect=lambda: self.api_models),
                list_workflows=Mock(side_effect=AssertionError("Web 不得回退到固定协议目录")),
            ),
            api_asset_analysis=types.SimpleNamespace(list_models=Mock(side_effect=lambda **_: self.vlm_models)),
        )

        def grouped_templates(media_type):
            return {"1080x1920": [types.SimpleNamespace(
                template_path=f"1080x1920/{media_type}_default.html",
                display_info=types.SimpleNamespace(
                    name=f"{media_type}_default.html", orientation="portrait", width=1080, height=1920,
                ),
            )]}

        generator = Mock(return_value=types.SimpleNamespace(
            parse_template_parameters=lambda: {}, get_media_size=lambda: (1080, 1920),
        ))
        modules = {
            "web": module("web", __path__=[str(ROOT / "web")]),
            "web.i18n": module("web.i18n", tr=lambda key, **_: key, get_language=lambda: "zh_CN"),
            "web.pipelines": module("web.pipelines", __path__=[str(ROOT / "web/pipelines")]),
            "web.pipelines.base": module("web.pipelines.base", PipelineUI=object, register_pipeline_ui=lambda _: None),
            "web.components": module("web.components", __path__=[str(ROOT / "web/components")]),
            "web.components.content_input": module("web.components.content_input", render_bgm_section=lambda **_: {}),
            "web.utils": module("web.utils", __path__=[]),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run),
            "pixelle_video": module("pixelle_video", __path__=[]),
            "pixelle_video.config": module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.tts_voices": module(
                "pixelle_video.tts_voices", EDGE_TTS_VOICES=[{"id": "zh-CN-YunjianNeural"}],
                get_voice_display_name=lambda voice_id, *_: voice_id,
            ),
            "pixelle_video.models": module("pixelle_video.models", __path__=[]),
            "pixelle_video.models.progress": module("pixelle_video.models.progress", ProgressEvent=object),
            "pixelle_video.utils": module("pixelle_video.utils", __path__=[]),
            "pixelle_video.utils.template_util": module(
                "pixelle_video.utils.template_util", get_templates_grouped_by_size_and_type=grouped_templates,
                get_template_type=lambda path: Path(path).name.split("_")[0],
                parse_template_size=lambda _: (1080, 1920), resolve_template_path=lambda path: path,
            ),
            "pixelle_video.services": module("pixelle_video.services", __path__=[]),
            "pixelle_video.services.frame_html": module("pixelle_video.services.frame_html", HTMLFrameGenerator=generator),
            "api_shared_core": module("api_shared_core", core=self.core),
        }
        # 重新加载真实 API 辅助函数，避免前一组测试缓存带不同依赖的模块。
        modules["web.pipelines.api_workflows"] = None
        imports = patch.dict(sys.modules, modules)
        imports.start()
        self.addCleanup(imports.stop)
        sys.modules.pop("web.pipelines.api_workflows", None)
        network = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实联网"))
        network.start()
        self.addCleanup(network.stop)
        # 模板封面与 API 路由无关；跳过栅格解码，避免隔离模块造成 NumPy 扩展重复加载。
        cover_image = patch("streamlit.image")
        cover_image.start()
        self.addCleanup(cover_image.stop)

    def style(self, media_type="image"):
        path = str(ROOT / "web/components/style_config.py")
        app = AppTest.from_string(
            "import runpy\nimport streamlit as st\nfrom api_shared_core import core\n"
            f"result = runpy.run_path({path!r})['render_style_config'](core)\n"
            "st.session_state['_result'] = result\n", default_timeout=10,
        )
        app.session_state["template_type_selector"] = media_type
        app.session_state["tts_inference_mode"] = "comfyui"
        app.session_state[f"standard_{media_type}_workflow_source"] = "runninghub"
        app.session_state[f"standard_{media_type}_workflow_source_select"] = "旧工作流"
        app.run()
        self.assertFalse(app.exception)
        return app

    def assert_no_legacy_controls(self, app):
        """检查实际控件文字与选项，而不是用源码字符串代替界面行为。"""
        visible = []
        for kind in ("radio", "selectbox", "button", "caption", "markdown", "info", "warning"):
            for item in app.get(kind):
                visible.extend([str(getattr(item, "label", "")), str(getattr(item, "value", ""))])
                visible.extend(getattr(item, "options", []))
        rendered = "\n".join(visible)
        for removed in ("RunningHub", "ComfyUI", "Stars", "版本信息"):
            self.assertNotIn(removed, rendered)
        self.media.list_workflows.assert_not_called()
        self.core.tts.assert_not_awaited()

    def test_quick_create_migrates_old_source_and_uses_selected_api_model(self):
        app = self.style()
        self.assertEqual(app.session_state["standard_image_workflow_source"], "api")
        self.assertEqual(app.session_state["tts_inference_mode"], "local")
        self.assertEqual(app.session_state["_result"]["media_workflow"], "api/test/image-a")
        app.selectbox(key="standard_image_workflow_source_select").set_value("测试图像 B").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["_result"]["media_workflow"], "api/test/image-b")
        self.assertIsNone(app.session_state["_result"]["tts_workflow"])
        self.assert_no_legacy_controls(app)

    def test_quick_video_template_filters_to_compatible_api_model(self):
        app = self.style("video")
        self.assertEqual(app.session_state["standard_video_workflow_source"], "api")
        self.assertEqual(app.session_state["_result"]["media_workflow"], "api/test/video")
        self.assert_no_legacy_controls(app)

    def test_quick_empty_api_list_has_no_fallback_or_preview_request(self):
        self.api_models = []
        app = self.style()
        self.assertIsNone(app.session_state["_result"]["media_workflow"])
        self.assertTrue(app.selectbox(key="standard_image_workflow_source_select").disabled)
        app.button(key="preview_style").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("API" in item.value for item in app.error))
        self.media.assert_not_awaited()
        self.assert_no_legacy_controls(app)

    def asset(self):
        path = str(ROOT / "web/pipelines/asset_based.py")
        app = AppTest.from_string(
            "import runpy\nimport streamlit as st\nfrom api_shared_core import core\n"
            f"ui = runpy.run_path({path!r})['AssetBasedPipelineUI']()\n"
            "result = ui._render_video_config(core)\n"
            "st.session_state['_result'] = result\n"
            # 只传不存在的测试路径用于就绪判断，不点击生成或读取素材。
            "ui._render_output_preview(core, dict(result, assets=['test-only.png']))\n",
        )
        app.session_state["asset_source"] = "runninghub"
        app.session_state["asset_analysis_workflow"] = "旧工作流"
        app.session_state["asset_animation_source"] = "selfhost"
        app.run()
        self.assertFalse(app.exception)
        # 视觉目录不再自动选首项；测试明确选择已有的测试型号后再检查提交流程。
        if self.vlm_models:
            app.selectbox(key="asset_analysis_workflow").set_value(self.vlm_models[0]["display_name"]).run()
            self.assertFalse(app.exception)
        return app

    def test_asset_analysis_migrates_to_api_and_optional_animation_stays_api(self):
        app = self.asset()
        self.assertEqual(app.session_state["asset_source"], "api")
        self.assertEqual(app.session_state["_result"]["analysis_vlm_model"], "test-vlm")
        self.assertEqual(app.radio(key="asset_animation_source").value, "none")
        app.radio(key="asset_animation_source").set_value("api").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["_result"]["api_video_workflow"], "api/test/video")
        self.assertFalse(app.button(key="asset_generate").disabled)
        self.core.api_asset_analysis.list_models.assert_called_with(configured_only=True)
        self.assert_no_legacy_controls(app)

    def test_asset_empty_vlm_disables_generation_without_workflow_fallback(self):
        self.vlm_models = []
        self.api_models = []
        app = self.asset()
        self.assertIsNone(app.session_state["_result"]["analysis_vlm_model"])
        self.assertIsNone(app.session_state["_result"]["analysis_image_workflow"])
        self.assertIsNone(app.session_state["_result"]["analysis_video_workflow"])
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assert_no_legacy_controls(app)

    def test_sidebar_has_no_version_or_stars_card(self):
        path = str(ROOT / "web/components/studio.py")
        with patch("streamlit.page_link"):
            app = AppTest.from_string(
                f"import runpy\nrunpy.run_path({path!r})['render_studio_sidebar']()\n"
            ).run()
        self.assertFalse(app.exception)
        rendered = "\n".join(item.proto.body for item in app.get("html"))
        self.assertIn("创作工作台", rendered)
        for removed in ("Stars", "版本信息", "当前版本", "shields.io"):
            self.assertNotIn(removed, rendered)


if __name__ == "__main__":
    unittest.main()
