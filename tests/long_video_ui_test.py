"""长片入口回归：真实三步表单与本地预算，生成服务使用内存替身。"""

import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
_fixture = runpy.run_path(str(ROOT / "tests/standard_creation_flow_test.py"))["StandardCreationFlowTest"]
_set_up = _fixture.setUp


class LongVideoUITest(unittest.TestCase):
    # 复用隔离配置/上传的 fixture，不继承另一组测试以免重复执行无关用例。
    make_app = _fixture.make_app
    move = _fixture.move

    def setUp(self):
        _set_up(self)
        long_backend = types.ModuleType("pixelle_video.utils.long_video")
        long_backend.__dict__.update(runpy.run_path(str(ROOT / "pixelle_video/utils/long_video.py")))
        sys.modules["pixelle_video.utils.long_video"] = long_backend
        # 所有页面测试使用同一份纯计算预算，不伪造镜头数或稿件预计长度。
        long_ui = types.ModuleType("web.components.long_video")
        long_ui.__dict__.update(runpy.run_path(str(ROOT / "web/components/long_video.py")))
        sys.modules["web.components.long_video"] = long_ui
        self.summary = long_ui.prepare_long_video_summary

    def long_app(self, duration=300):
        app = self.make_app()
        app.radio(key="quick_create_length_mode").set_value("long").run()
        app.selectbox(key="quick_create_target_duration").set_value(duration).run()
        self.assertFalse(app.exception)
        return app

    def test_short_default_and_batch_do_not_inherit_long_duration(self):
        app = self.make_app()
        self.assertEqual(app.radio(key="quick_create_length_mode").value, "short")
        app.text_area(key="quick_create_text").set_value("短片主题").run()
        self.move(app, "next")
        self.move(app, "next")
        self.assertNotIn("target_duration_seconds", self.output.call_args.args[1])
        self.move(app, "previous")
        self.move(app, "previous")
        app.radio(key="quick_create_length_mode").set_value("long").run()
        app.selectbox(key="quick_create_target_duration").set_value(600).run()
        app.checkbox(key="quick_create_batch_mode").set_value(True).run()
        app.text_area(key="quick_create_batch_topics").set_value("主题一\n主题二").run()
        self.move(app, "next")
        self.move(app, "next")
        self.assertNotIn("target_duration_seconds", self.output.call_args.args[1])
        self.core.generate_video.assert_not_awaited()

    def test_long_presets_pass_duration_language_and_current_voice_speed(self):
        for duration in (300, 480, 600):
            with self.subTest(duration=duration):
                self.core.generate_video.reset_mock()
                app = self.long_app(duration)
                app.selectbox(key="quick_create_narration_language").set_value("en").run()
                app.text_area(key="quick_create_text").set_value("Explain how a mechanical watch works.").run()
                self.move(app, "next")
                app.slider(key="flow_test_speed").set_value(1.2).run()
                self.move(app, "next")
                merged = self.output.call_args.args[1]
                self.assertEqual(merged["target_duration_seconds"], duration)
                self.assertEqual(merged["narration_language"], "en")
                plan = self.summary(merged)
                self.assertEqual(plan["scene_count"], (duration + 7) // 8)
                self.assertGreater(plan["target_units"], 500)
                self.core.generate_video.assert_not_awaited()
                app.button(key="studio_generate").click().run()
                self.assertFalse(app.exception)
                submitted = self.core.generate_video.call_args.kwargs
                self.assertEqual(submitted["target_duration_seconds"], duration)
                self.assertEqual(submitted["narration_language"], "en")
                self.assertEqual(submitted["tts_speed"], 1.2)
                self.core.generate_video.assert_awaited_once()
                self.move(app, "previous")
                self.move(app, "previous")
                self.assertEqual(app.selectbox(key="quick_create_target_duration").value, duration)

    def test_fixed_script_is_not_padded_and_warns_about_duration_gap(self):
        app = self.long_app(600)
        app.radio(key="quick_create_mode").set_value("fixed").run()
        script = "发条储存能量。擒纵机构控制能量的释放。"
        app.text_area(key="quick_create_text").set_value(script).run()
        self.move(app, "next")
        self.move(app, "next")
        merged = self.output.call_args.args[1]
        self.assertLess(self.summary(merged)["estimated_duration_seconds"], 20)
        self.assertTrue(any("差距较大" in item.value for item in app.warning))
        app.button(key="studio_generate").click().run()
        self.assertEqual(self.core.generate_video.call_args.kwargs["text"], script)

    def test_actual_duration_is_preserved_and_unmeasured_result_is_not_claimed_as_measured(self):
        for status in ("measured", "unavailable"):
            with self.subTest(status=status):
                result = self.core.generate_video.return_value
                result.duration = 287.5
                result.duration_report = {"measurement_status": status}
                app = self.long_app()
                app.text_area(key="quick_create_text").set_value("旁白测试主题").run()
                self.move(app, "next")
                self.move(app, "next")
                app.button(key="studio_generate").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["studio_last_video_result"]["duration"], 287.5)
                captions = " ".join(item.value for item in app.caption)
                if status == "measured":
                    self.assertIn("实际成片时长 4:48", captions)
                else:
                    self.assertNotIn("实际成片时长", captions)
                    self.assertTrue(any("暂未检测到实际时长" in item.value for item in app.warning))

    def test_long_video_keeps_api_only_submission_guard(self):
        self.style_overrides["media_workflow"] = "runninghub/old.json"
        app = self.long_app()
        app.text_area(key="quick_create_text").set_value("长片不能回退旧工作流").run()
        self.move(app, "next")
        self.move(app, "next")
        self.assertTrue(app.button(key="studio_generate").disabled)
        self.core.generate_video.assert_not_awaited()

    def test_budget_defaults_match_backend_and_reject_invalid_speech_rate(self):
        # 预算可缺省语速，但不能将非法零值展示成可提交的正常计划。
        params = {"target_duration_seconds": 300, "mode": "generate"}
        self.assertEqual(self.summary(params)["tts_speed"], 1.0)
        self.assertEqual(self.summary({**params, "tts_speed": None})["tts_speed"], 1.0)
        with self.assertRaises(ValueError):
            self.summary({**params, "tts_speed": 0})
        # 静态模板即使带着历史模型选择，也不能展示成收费的媒体生成任务。
        with patch("pixelle_video.utils.template_util.get_template_type", return_value="static"):
            static_plan = self.summary({**params, "media_workflow": "api/test/model"})
        self.assertEqual(static_plan["media_tasks"], 0)
        self.assertEqual(static_plan["expected_media_calls"], 0)


# pytest 会收集模块中引用的 unittest 类，即使变量带下划线；只保留本组新用例。
del _fixture


if __name__ == "__main__":
    unittest.main()
