"""自定义素材长片表单：预算、视觉服务商、提交参数与真实步骤往返的离线回归。"""

import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
_fixture = runpy.run_path(str(ROOT / "tests/asset_creation_flow_test.py"))["AssetCreationFlowTest"]
_set_up = _fixture.setUp


class AssetLongUITest(unittest.TestCase):
    app = _fixture.app

    def setUp(self):
        _set_up(self)
        # 前后端预算用真实纯函数；生成、文件上传和模型访问都由内存替身隔离。
        planner = types.ModuleType("pixelle_video.utils.long_video")
        planner.__dict__.update(runpy.run_path(str(ROOT / "pixelle_video/utils/long_video.py")))
        sys.modules["pixelle_video.utils.long_video"] = planner
        self.vlm_models = [
            {"provider": "dashscope", "model": "vision-shared", "display_name": "Vision / DashScope"},
            {"provider": "openai", "model": "vision-shared", "display_name": "Vision / OpenAI compatible"},
        ]

    def long_app(self, duration=300):
        app = self.app()
        app.radio(key="asset_length_mode").set_value("long").run()
        app.selectbox(key="asset_long_duration").set_value(duration).run()
        self.assertFalse(app.exception)
        return app

    def move(self, app, direction):
        # 切换视觉服务后显式选择测试型号，不能依赖生产代码自动首选目录条目。
        if self.vlm_models and app.selectbox(key="asset_analysis_workflow").value is None:
            selector = app.selectbox(key="asset_analysis_workflow")
            selector.set_value(selector.options[0]).run()
        app.button(key=f"creation_flow_custom_media_{direction}").click().run()
        self.assertFalse(app.exception)

    def test_long_presets_use_current_speed_and_preserve_draft_on_return(self):
        for seconds, scenes in ((300, 38), (480, 60), (600, 75)):
            with self.subTest(seconds=seconds):
                app = self.long_app(seconds)
                app.text_input(key="asset_video_title").set_value("素材长片回归")
                app.text_area(key="asset_intent").set_value("围绕已提供素材做分章教学")
                app.slider(key="asset_tts_speed").set_value(1.5)
                self.move(app, "next")
                self.move(app, "next")
                params = app.session_state["_asset_flow_params"]
                self.assertEqual(params["duration"], seconds)
                self.assertEqual(params["tts_speed"], 1.5)
                self.assertEqual(params["narration_language"], "zh")
                self.assertEqual(app.metric[1].value, str(scenes))
                captions = " ".join(item.value for item in app.caption)
                self.assertIn(str(round(seconds * 3.6 * 1.5)), captions)
                self.assertTrue(app.button(key="asset_generate_disabled").disabled)
                self.move(app, "previous")
                self.move(app, "previous")
                self.assertEqual(app.text_input(key="asset_video_title").value, "素材长片回归")
                self.assertEqual(app.selectbox(key="asset_long_duration").value, seconds)
                self.core.tts.assert_not_awaited()
                self.media.assert_not_awaited()

    def test_provider_is_explicit_even_with_same_model_name(self):
        app = self.long_app()
        app.selectbox(key="asset_analysis_provider").set_value("openai").run()
        app.select_slider(key="asset_analysis_video_max_frames").set_value(32).run()
        app.selectbox(key="asset_narration_language").set_value("en").run()
        self.move(app, "next")
        self.move(app, "next")
        params = app.session_state["_asset_flow_params"]
        self.assertEqual(params["analysis_vlm_provider"], "openai")
        self.assertEqual(params["analysis_vlm_model"], "vision-shared")
        self.assertEqual(params["analysis_video_max_frames"], 32)
        self.assertEqual(params["narration_language"], "en")
        self.move(app, "previous")
        app.selectbox(key="asset_analysis_provider").set_value("dashscope").run()
        self.move(app, "next")
        params = app.session_state["_asset_flow_params"]
        self.assertEqual(params["analysis_vlm_provider"], "dashscope")
        self.assertEqual(app.selectbox(key="asset_analysis_workflow").value, "Vision / DashScope")

    def test_submission_passes_long_and_vision_parameters_without_animation(self):
        with tempfile.TemporaryDirectory() as folder, patch("streamlit.video"):
            output = Path(folder) / "offline-result.mp4"
            output.write_bytes(b"not-a-real-generated-video")
            report = {
                "measurement_status": "measured", "actual_duration_seconds": 588.2,
                "target_duration_seconds": 600, "within_tolerance": True,
            }
            runner = AsyncMock(return_value=types.SimpleNamespace(
                final_video_path=str(output), storyboard=types.SimpleNamespace(frames=[object()] * 75),
                duration_report=report, analysis_warnings=[{"message": "offline analysis failure"}],
            ))
            package = types.ModuleType("pixelle_video.pipelines")
            package.__path__ = []
            backend = types.ModuleType("pixelle_video.pipelines.asset_based")
            backend.AssetBasedPipeline = Mock(return_value=runner)
            with patch.dict(sys.modules, {package.__name__: package, backend.__name__: backend}):
                app = self.long_app(600)
                app.session_state["_test_ready_assets"] = True
                app.selectbox(key="asset_analysis_provider").set_value("openai").run()
                app.select_slider(key="asset_analysis_video_max_frames").set_value(8).run()
                self.move(app, "next")
                self.move(app, "next")
                self.assertTrue(any("部分素材可能多次使用" in item.value for item in app.warning))
                runner.assert_not_awaited()
                app.button(key="asset_generate").click().run()
                self.assertFalse(app.exception)
                submitted = runner.call_args.kwargs
                self.assertEqual(submitted["duration"], 600)
                self.assertEqual(submitted["source"], "api")
                self.assertEqual(submitted["analysis_vlm_provider"], "openai")
                self.assertEqual(submitted["analysis_video_max_frames"], 8)
                self.assertIsNone(submitted["api_video_workflow"])
                self.assertEqual(app.session_state["asset_generated_result"]["duration_report"], report)
                self.assertTrue(any("实际成片 9:48" in item.value for item in app.caption))
                self.assertTrue(any("已从本次长片排除" in item.value for item in app.warning))
                self.move(app, "previous")
                self.move(app, "next")
                runner.assert_awaited_once()

    def test_no_vision_provider_still_blocks_long_submission(self):
        self.vlm_models = []
        app = self.long_app()
        app.session_state["_test_ready_assets"] = True
        self.move(app, "next")
        self.move(app, "next")
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assertIsNone(app.session_state["_asset_flow_params"]["analysis_vlm_provider"])
        self.core.tts.assert_not_awaited()
        self.media.assert_not_awaited()

    def test_invalid_provider_descriptor_cannot_submit(self):
        # 防御异常服务描述：即使返回未配置项，也不能触发生成。
        self.vlm_models[1]["configured"] = False
        app = self.long_app()
        app.session_state["_test_ready_assets"] = True
        app.selectbox(key="asset_analysis_provider").set_value("openai").run()
        self.move(app, "next")
        self.move(app, "next")
        self.assertEqual(app.session_state["_asset_flow_params"]["analysis_vlm_model"], "vision-shared")
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.core.tts.assert_not_awaited()

    def test_loaded_unknown_model_is_selectable_and_removed_catalog_blocks_submit(self):
        # 模拟接口新增的非预设名称；创作页只使用服务返回目录，不维护固定候选。
        self.vlm_models.append({
            "provider": "openai", "model": "relay-vision-future-2027",
            "display_name": "relay-vision-future-2027 / OpenAI compatible", "configured": True,
        })
        app = self.long_app()
        app.session_state["_test_ready_assets"] = True
        app.selectbox(key="asset_analysis_provider").set_value("openai").run()
        options = app.selectbox(key="asset_analysis_workflow").options
        self.assertEqual(options, ["Vision / OpenAI compatible", "relay-vision-future-2027 / OpenAI compatible"])
        app.selectbox(key="asset_analysis_workflow").set_value(options[-1]).run()
        self.move(app, "next")
        self.move(app, "next")
        params = app.session_state["_asset_flow_params"]
        self.assertEqual(params["analysis_vlm_provider"], "openai")
        self.assertEqual(params["analysis_vlm_model"], "relay-vision-future-2027")
        self.assertFalse(app.button(key="asset_generate").disabled)
        self.move(app, "previous")
        self.move(app, "next")
        self.assertEqual(app.selectbox(key="asset_analysis_workflow").value, options[-1])
        # 地址/密钥变化导致服务返回空目录时，旧型号不得继续留作兜底。
        self.vlm_models = []
        app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state["_asset_flow_params"]["analysis_vlm_model"])
        self.assertIsNone(app.session_state["_asset_flow_params"]["analysis_vlm_provider"])
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assertTrue(any("尚未配置视觉分析服务密钥" in item.value for item in app.warning))
        self.core.tts.assert_not_awaited()


# 不将复用的 unittest 类暴露给 pytest，避免重复收集旧测试。
del _fixture


if __name__ == "__main__":
    unittest.main()
