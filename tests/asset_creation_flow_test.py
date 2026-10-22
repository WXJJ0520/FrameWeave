"""自定义素材步骤往返、素材落盘与结果保留的离线回归。"""

import io
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


class AssetCreationFlowTest(unittest.TestCase):
    def setUp(self):
        # 复用内存配置和 API 目录替身，不将原测试类重新暴露给 pytest 重复收集。
        fixture = runpy.run_path(str(ROOT / "tests/api_shared_ui_test.py"))["APISharedUITest"]
        fixture.setUp(self)
        # 背景音乐也使用真实控件，仅资源目录用固定清单替代，保证重排后参数没有遗漏。
        sys.modules["web.components.content_input"].render_bgm_section = runpy.run_path(
            str(ROOT / "web/components/content_input.py")
        )["render_bgm_section"]
        resources = types.ModuleType("pixelle_video.utils.os_util")
        resources.list_resource_files = lambda _: ["default.mp3"]
        sys.modules["pixelle_video.utils.os_util"] = resources

    def app(self):
        sys.modules.pop("web.components.creation_flow", None)
        script = (
            "import runpy\nimport streamlit as st\nfrom api_shared_core import core\n"
            f"ui = runpy.run_path({str(ROOT / 'web/pipelines/asset_based.py')!r})['AssetBasedPipelineUI']()\n"
            "original_preview = ui._render_output_preview\n"
            "def capture_preview(core, params):\n"
            "    if st.session_state.get('_test_ready_assets'):\n"
            "        params = dict(params, assets=['test-only.png'])\n"
            "    st.session_state['_asset_flow_params'] = params\n"
            "    original_preview(core, params)\n"
            "ui._render_output_preview = capture_preview\n"
            "ui.render(core)\n"
        )
        app = AppTest.from_string(script, default_timeout=10)
        # 往返测试模拟已有明确选择；首次加载不选首项另由目录专项测试覆盖。
        if self.vlm_models:
            app.session_state["asset_analysis_workflow"] = self.vlm_models[0]["display_name"]
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_navigation_preserves_all_input_widgets_and_selected_api_parameters(self):
        app = self.app()
        self.assertTrue(app.button(key="creation_flow_custom_media_previous").disabled)
        self.assertFalse(any(button.key == "asset_generate_disabled" for button in app.button))
        app.text_input(key="asset_video_title").set_value("我的素材片")
        app.text_area(key="asset_intent").set_value("讲清机械表的动力来源")
        app.slider(key="asset_duration").set_value(45)
        app.slider(key="asset_tts_speed").set_value(1.5)
        app.slider(key="asset_bgm_volume_slider").set_value(0.31)
        app.radio(key="asset_animation_source").set_value("api")
        app.button(key="creation_flow_custom_media_next").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["creation_flow_custom_media_step"], 1)
        app.button(key="creation_flow_custom_media_next").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["creation_flow_custom_media_step"], 2)
        params = app.session_state["_asset_flow_params"]
        self.assertEqual(params["video_title"], "我的素材片")
        self.assertEqual(params["intent"], "讲清机械表的动力来源")
        self.assertEqual(params["duration"], 45)
        self.assertEqual(params["tts_speed"], 1.5)
        self.assertEqual(params["bgm_path"], "default.mp3")
        self.assertEqual(params["bgm_volume"], 0.31)
        self.assertEqual(params["source"], "api")
        self.assertEqual(params["analysis_vlm_model"], "test-vlm")
        self.assertEqual(params["api_video_workflow"], "api/test/video")
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        # 上传组件和参数控件在末步仍挂载；CSS 隐藏，不触发 Streamlit 状态清理。
        self.assertEqual(len(app.get("file_uploader")), 1)
        app.button(key="creation_flow_custom_media_previous").click().run()
        app.button(key="creation_flow_custom_media_previous").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.text_input(key="asset_video_title").value, "我的素材片")
        self.assertEqual(app.slider(key="asset_duration").value, 45)
        self.assertEqual(app.slider(key="asset_bgm_volume_slider").value, 0.31)
        self.assertEqual(app.radio(key="asset_animation_source").value, "api")
        self.core.tts.assert_not_awaited()
        self.media.assert_not_awaited()

    def test_last_result_returns_after_leaving_preview_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as folder, patch("streamlit.video") as video:
            output = Path(folder) / "完成视频.mp4"
            output.write_bytes(b"offline-result-placeholder")
            app = self.app()
            app.session_state["asset_generated_result"] = {
                "path": str(output), "generation_time": 1.25, "scene_count": 2,
            }
            app.button(key="creation_flow_custom_media_next").click().run()
            app.button(key="creation_flow_custom_media_next").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any(item.value == "上次生成结果" for item in app.caption))
            self.assertEqual(len(app.get("download_button")), 1)
            app.button(key="creation_flow_custom_media_previous").click().run()
            self.assertFalse(any(item.value == "上次生成结果" for item in app.caption))
            app.button(key="creation_flow_custom_media_next").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get("download_button")), 1)
            video.assert_called_with(str(output))
            self.core.tts.assert_not_awaited()
            self.media.assert_not_awaited()

    def test_invalid_config_keeps_previous_navigation_available(self):
        app = self.app()
        app.session_state["_test_ready_assets"] = True
        app.button(key="creation_flow_custom_media_next").click().run()
        app.button(key="creation_flow_custom_media_next").click().run()
        self.manager.validate.return_value = False
        app.button(key="asset_generate").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "settings.not_configured" for item in app.error))
        # 生成校验失败只返回输出区域，导航仍在，用户能回去修正而无需刷新。
        app.button(key="creation_flow_custom_media_previous").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["creation_flow_custom_media_step"], 1)
        self.core.tts.assert_not_awaited()
        self.media.assert_not_awaited()

    def test_upload_cache_reuses_content_and_tracks_replacement_and_removal(self):
        ui = runpy.run_path(str(ROOT / "web/pipelines/asset_based.py"))["AssetBasedPipelineUI"]

        def upload(name, data):
            uploaded = io.BytesIO(data)
            uploaded.name = name
            return uploaded

        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_custom_media": {"directory": folder, "files": {}}}
            with patch("streamlit.session_state", state):
                first = ui._persist_uploaded_assets([upload("素材.png", b"original")])
                again = ui._persist_uploaded_assets([upload("素材.png", b"original")])
                self.assertEqual(first, again)
                self.assertEqual(len(list(Path(folder).iterdir())), 1)
                changed = ui._persist_uploaded_assets([upload("素材.png", b"replacement")])
                self.assertNotEqual(first, changed)
                self.assertEqual(Path(changed[0]).read_bytes(), b"replacement")
                self.assertEqual(ui._persist_uploaded_assets([]), [])
                # 删除当前上传项不误删之前任务可能仍引用的文件。
                self.assertEqual(Path(first[0]).read_bytes(), b"original")
                self.assertEqual(len(list(Path(folder).iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
