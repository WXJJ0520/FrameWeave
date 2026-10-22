"""快速创作真实页面的步骤集成测试；真实脚本、音乐和提交守卫，生成服务仅在内存中模拟。"""

import asyncio
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def make_module(name, **attributes):
    """隔离真实配置和服务初始化，避免测试触及现有用户配置或付费接口。"""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class StandardCreationFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / "步骤测试.mp4"
        # 仅提供本地媒体缓存可读取的容器头，不把测试产物当作实际视频生成。
        self.video.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2")
        result = types.SimpleNamespace(
            video_path=str(self.video), file_size=self.video.stat().st_size,
            storyboard=types.SimpleNamespace(
                frames=[object(), object()],
                config=types.SimpleNamespace(frame_template="test-template.html"),
            ),
        )
        self.core = types.SimpleNamespace(generate_video=AsyncMock(return_value=result))
        self.manager = types.SimpleNamespace(validate=Mock(return_value=True))
        self.batch_manager = types.SimpleNamespace(execute_batch=Mock(return_value={
            "total_count": 2, "success_count": 2, "failed_count": 0, "errors": [],
        }))
        self.style_overrides = {}
        i18n = make_module("web.i18n")
        i18n.__dict__.update(runpy.run_path(str(ROOT / "web/i18n/__init__.py")))
        i18n.set_language("zh_CN")
        modules = {
            "web": make_module("web", __path__=[str(ROOT / "web")]),
            "web.i18n": i18n,
            "web.pipelines": make_module("web.pipelines", __path__=[str(ROOT / "web/pipelines")]),
            "web.pipelines.base": make_module(
                "web.pipelines.base", PipelineUI=object, register_pipeline_ui=lambda _: None,
            ),
            "web.components": make_module("web.components", __path__=[str(ROOT / "web/components")]),
            "web.utils": make_module("web.utils", __path__=[]),
            "web.utils.async_helpers": make_module("web.utils.async_helpers", run_async=asyncio.run),
            "web.utils.batch_manager": make_module(
                "web.utils.batch_manager", SimpleBatchManager=lambda: self.batch_manager,
            ),
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.models": make_module("pixelle_video.models", __path__=[]),
            "pixelle_video.models.progress": make_module("pixelle_video.models.progress", ProgressEvent=object),
            "pixelle_video.utils": make_module("pixelle_video.utils", __path__=[]),
            "pixelle_video.utils.template_util": make_module(
                "pixelle_video.utils.template_util", get_template_type=lambda _: "video",
                resolve_template_path=lambda path: path, parse_template_size=lambda _: (1280, 720),
            ),
            "pixelle_video.utils.os_util": make_module(
                "pixelle_video.utils.os_util", list_resource_files=lambda _: ["test-background.mp3"],
            ),
            "standard_flow_test_services": make_module("standard_flow_test_services", core=self.core),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        for name in ("content_input", "output_preview", "creation_flow"):
            loaded = make_module(f"web.components.{name}")
            loaded.__dict__.update(runpy.run_path(str(ROOT / f"web/components/{name}.py")))
            sys.modules[f"web.components.{name}"] = loaded

        # 第二步用真实的稳定键控件模拟选项，独立于模型目录；其他组件全部执行原实现。
        def style_config(_):
            model = st.selectbox(
                "测试 API 模型", ["api/test/first", "api/test/second"], key="flow_test_model",
            )
            voice = st.selectbox("测试音色", ["voice-a", "voice-b"], key="flow_test_voice")
            speed = st.slider("测试语速", 0.5, 2.0, 1.0, step=0.1, key="flow_test_speed")
            prefix = st.text_input("测试画面提示词", key="flow_test_prompt")
            st.session_state["template_media_width"] = 1280
            st.session_state["template_media_height"] = 720
            return {
                "frame_template": "test-template.html", "media_workflow": model,
                "requires_api_media": True, "tts_inference_mode": "local", "tts_voice": voice,
                "tts_speed": speed, "prompt_prefix": prefix,
                "api_video_params": {"video_duration": 6, "video_ratio": "16:9"},
                "template_params": {"subtitle": True}, **self.style_overrides,
            }

        sys.modules["web.components.style_config"] = make_module(
            "web.components.style_config", render_style_config=style_config,
        )
        output = sys.modules["web.components.output_preview"]
        self.output = Mock(wraps=output.render_output_preview)
        output.render_output_preview = self.output
        no_network = patch(
            "requests.sessions.Session.request", side_effect=AssertionError("步骤测试不得联网"),
        )
        no_network.start()
        self.addCleanup(no_network.stop)
        self.tr = i18n.tr

    def make_app(self, batch=False):
        # 标准页 render 完整执行；不是复制步骤代码，也没有替换脚本或输出组件。
        path = str(ROOT / "web/pipelines/standard.py")
        app = AppTest.from_string(
            "import runpy\nfrom standard_flow_test_services import core\n"
            f"runpy.run_path({path!r})['StandardPipelineUI']().render(core)\n",
            default_timeout=10,
        )
        if batch:
            app.session_state["quick_create_batch_mode"] = True
        app.run()
        self.assertFalse(app.exception)
        return app

    def move(self, app, direction):
        app.button(key=f"creation_flow_quick_create_{direction}").click().run()
        self.assertFalse(app.exception)

    def test_single_script_settings_merge_and_submit_only_on_final_step(self):
        app = self.make_app()
        self.assertEqual(len(app.tabs), 0)
        self.output.assert_not_called()
        app.radio(key="quick_create_mode").set_value("fixed").run()
        app.text_area(key="quick_create_text").set_value("发条储存能量\n擒纵控制释放")
        app.text_input(key="quick_create_title").set_value("机械表的心跳")
        app.selectbox(key="quick_create_split_mode").set_value("line").run()
        self.assertNotIn("studio_generate", [button.key for button in app.button])
        self.move(app, "next")
        app.selectbox(key="flow_test_model").set_value("api/test/second")
        app.selectbox(key="flow_test_voice").set_value("voice-b")
        app.slider(key="flow_test_speed").set_value(1.3)
        app.text_input(key="flow_test_prompt").set_value("干净的机械剖面")
        app.selectbox(key="bgm_selector").set_value("test-background.mp3").run()
        app.slider(key="bgm_volume_slider").set_value(0.12).run()
        self.output.assert_not_called()
        self.core.generate_video.assert_not_awaited()
        self.move(app, "next")
        merged = self.output.call_args.args[1]
        self.assertEqual(merged["pipeline"], "quick_create")
        self.assertEqual(merged["split_mode"], "line")
        self.assertEqual(merged["media_workflow"], "api/test/second")
        self.assertEqual(merged["bgm_path"], "test-background.mp3")
        app.button(key="studio_generate").click().run()
        self.assertFalse(app.exception)
        self.core.generate_video.assert_awaited_once()
        submitted = self.core.generate_video.call_args.kwargs
        expected = {
            "text": "发条储存能量\n擒纵控制释放", "title": "机械表的心跳", "mode": "fixed",
            "split_mode": "line", "media_workflow": "api/test/second", "tts_voice": "voice-b",
            "tts_speed": 1.3, "tts_inference_mode": "local", "prompt_prefix": "干净的机械剖面",
            "bgm_path": "test-background.mp3", "bgm_volume": 0.12,
            "api_video_params": {"video_duration": 6, "video_ratio": "16:9"},
            "template_params": {"subtitle": True}, "media_width": 1280, "media_height": 720,
        }
        for key, value in expected.items():
            with self.subTest(parameter=key):
                self.assertEqual(submitted[key], value)
        self.move(app, "previous")
        self.move(app, "previous")
        self.assertEqual(app.text_area(key="quick_create_text").value, expected["text"])
        self.assertEqual(app.selectbox(key="flow_test_model").value, "api/test/second")
        self.move(app, "next")
        self.move(app, "next")
        self.assertEqual(len(app.get("video")), 1)
        self.core.generate_video.assert_awaited_once()

    def test_batch_topics_survive_navigation_and_merge_into_explicit_batch_submission(self):
        app = self.make_app()
        app.checkbox(key="quick_create_batch_mode").set_value(True).run()
        app.text_area(key="quick_create_batch_topics").set_value("  月球便利店\n\n 时间邮局  ")
        app.text_input(key="quick_create_batch_title_prefix").set_value("未来日记")
        app.slider(key="quick_create_batch_n_scenes").set_value(8).run()
        self.move(app, "next")
        app.selectbox(key="flow_test_model").set_value("api/test/second").run()
        self.move(app, "previous")
        self.assertTrue(app.checkbox(key="quick_create_batch_mode").value)
        self.assertEqual(app.text_input(key="quick_create_batch_title_prefix").value, "未来日记")
        self.assertEqual(app.slider(key="quick_create_batch_n_scenes").value, 8)
        self.move(app, "next")
        self.output.assert_not_called()
        self.batch_manager.execute_batch.assert_not_called()
        self.move(app, "next")
        self.assertEqual(self.output.call_args.args[1]["topics"], ["月球便利店", "时间邮局"])
        self.assertNotIn("studio_generate", [button.key for button in app.button])
        batch_button = next(button for button in app.button if button.label == self.tr("batch.generate_button", count=2))
        batch_button.click().run()
        self.assertFalse(app.exception)
        self.batch_manager.execute_batch.assert_called_once()
        submitted = self.batch_manager.execute_batch.call_args.kwargs
        self.assertEqual(submitted["topics"], ["月球便利店", "时间邮局"])
        self.assertEqual(submitted["shared_config"]["title_prefix"], "未来日记")
        self.assertEqual(submitted["shared_config"]["n_scenes"], 8)
        self.assertEqual(submitted["shared_config"]["media_workflow"], "api/test/second")
        self.assertEqual(submitted["shared_config"]["tts_inference_mode"], "local")
        self.move(app, "previous")
        self.move(app, "next")
        self.batch_manager.execute_batch.assert_called_once()
        self.assertEqual([metric.value for metric in app.metric], ["2", "2", "0"])
        self.assertTrue(any("上次批量结果" in item.value for item in app.markdown))
        self.core.generate_video.assert_not_awaited()

    def test_batch_failed_tasks_and_summary_remain_after_return_and_changed_draft(self):
        self.batch_manager.execute_batch.return_value = {
            "total_count": 2, "success_count": 1, "failed_count": 1,
            "errors": [{
                "index": 2, "topic": "失败主题", "error": "Bearer TEST_PRIVATE_TOKEN",
                "traceback": "https://example.invalid/result?key=TEST_PRIVATE_TOKEN",
            }],
        }
        app = self.make_app(batch=True)
        app.text_area(key="quick_create_batch_topics").set_value("成功主题\n失败主题").run()
        self.move(app, "next")
        self.move(app, "next")
        next(button for button in app.button if button.label == self.tr("batch.generate_button", count=2)).click().run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["2", "1", "1"])
        self.assertTrue(any("失败主题" in item.label for item in app.expander))
        cached = app.session_state["studio_last_batch_result"]
        self.assertEqual(cached["errors"], [{"index": 2, "topic": "失败主题"}])
        self.assertNotIn("TEST_PRIVATE_TOKEN", repr(cached))
        self.assertNotIn("TEST_PRIVATE_TOKEN", "\n".join(item.value for item in app.error))
        self.assertEqual(len(app.code), 0)
        self.move(app, "previous")
        self.move(app, "previous")
        # 修改了当前草稿且当前模型无效时，仍然展示明确标记的上次结果，不会重复批次。
        app.text_area(key="quick_create_batch_topics").set_value("新的未提交主题").run()
        self.style_overrides["media_workflow"] = None
        self.move(app, "next")
        self.move(app, "next")
        self.assertEqual([metric.value for metric in app.metric], ["2", "1", "1"])
        self.assertTrue(any("失败主题" in item.label for item in app.expander))
        self.assertTrue(any("上次批量结果" in item.value for item in app.markdown))
        self.batch_manager.execute_batch.assert_called_once()
        self.core.generate_video.assert_not_awaited()

    def test_batch_execution_exception_keeps_navigation_and_previous_results_without_secret(self):
        app = self.make_app(batch=True)
        app.text_area(key="quick_create_batch_topics").set_value("测试主题一\n测试主题二").run()
        self.move(app, "next")
        self.move(app, "next")
        label = self.tr("batch.generate_button", count=2)
        next(button for button in app.button if button.label == label).click().run()
        previous = dict(app.session_state["studio_last_batch_result"])
        self.batch_manager.execute_batch.side_effect = RuntimeError(
            "Authorization: Bearer TEST_PRIVATE_TOKEN https://example.invalid?key=TEST_PRIVATE_TOKEN"
        )
        next(button for button in app.button if button.label == label).click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.button(key="creation_flow_quick_create_previous").disabled)
        self.assertTrue(any("最近一次批量任务未能完成" in item.value for item in app.error))
        self.assertNotIn("TEST_PRIVATE_TOKEN", "\n".join(item.value for item in app.error))
        self.assertEqual(app.session_state["studio_last_batch_failure"], "RuntimeError")
        self.assertEqual(app.session_state["studio_last_batch_result"], previous)
        self.move(app, "previous")
        self.move(app, "next")
        self.assertEqual(self.batch_manager.execute_batch.call_count, 2)
        self.assertTrue(any("最近一次批量任务未能完成" in item.value for item in app.error))
        self.assertEqual([metric.value for metric in app.metric], ["2", "2", "0"])
        self.batch_manager.execute_batch.side_effect = None
        next(button for button in app.button if button.label == label).click().run()
        self.assertEqual(self.batch_manager.execute_batch.call_count, 3)
        self.assertNotIn("studio_last_batch_failure", app.session_state)
        self.assertFalse(app.error)

    def test_real_single_output_keeps_api_only_guard_after_step_navigation(self):
        for workflow in (None, "runninghub/old.json", "selfhost/old.json"):
            with self.subTest(workflow=workflow):
                self.style_overrides["media_workflow"] = workflow
                app = self.make_app()
                app.text_area(key="quick_create_text").set_value("有脚本也不能回退到旧工作流").run()
                self.move(app, "next")
                self.move(app, "next")
                self.assertTrue(app.button(key="studio_generate").disabled)
                self.assertTrue(any("API" in item.value for item in app.warning))
                # 即便测试协议强行提交禁用按钮，真实提交边界也必须拒绝旧来源。
                app.button(key="studio_generate").click().run()
                self.assertFalse(app.exception)
                self.core.generate_video.assert_not_awaited()

    def test_real_batch_output_has_no_submission_button_without_api_model(self):
        for workflow in (None, "runninghub/old.json", "selfhost/old.json"):
            with self.subTest(workflow=workflow):
                self.style_overrides["media_workflow"] = workflow
                app = self.make_app(batch=True)
                app.text_area(key="quick_create_batch_topics").set_value("测试主题一\n测试主题二").run()
                self.move(app, "next")
                self.move(app, "next")
                self.assertTrue(any("API" in item.value for item in app.warning))
                self.assertEqual(
                    [button.key for button in app.button], ["creation_flow_quick_create_previous"],
                )
                self.batch_manager.execute_batch.assert_not_called()
                self.core.generate_video.assert_not_awaited()

    def test_validation_errors_keep_previous_button_available_for_correction(self):
        # 错误提示不能用 st.stop 中断整个页面，否则用户无法回到输入步骤修正。
        for configured, text in ((True, ""), (False, "保留这条待修正配置的脚本")):
            with self.subTest(configured=configured):
                self.manager.validate.return_value = configured
                app = self.make_app()
                app.text_area(key="quick_create_text").set_value(text).run()
                self.move(app, "next")
                self.move(app, "next")
                app.button(key="studio_generate").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertFalse(app.button(key="creation_flow_quick_create_previous").disabled)
                self.move(app, "previous")
                self.move(app, "previous")
                self.assertEqual(app.session_state["creation_flow_quick_create_step"], 0)
                self.assertEqual(app.text_area(key="quick_create_text").value, text)
                self.core.generate_video.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
