"""视频参数控件回归：使用真实模型元数据和 AppTest，不读取配置或调用模型。"""

import asyncio
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def make_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class VideoControlsTest(unittest.TestCase):
    def setUp(self):
        # 隔离项目包的初始化，只读取实际服务中的元数据和控件函数。
        modules = {
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=None),
            "pixelle_video.models": make_module("pixelle_video.models", __path__=[]),
            "pixelle_video.models.media": make_module("pixelle_video.models.media", MediaResult=object),
            "pixelle_video.utils": make_module("pixelle_video.utils", __path__=[]),
            "pixelle_video.utils.os_util": make_module(
                "pixelle_video.utils.os_util", get_output_path=lambda *parts: "unused"
            ),
            "web": make_module("web", __path__=[]),
            "web.i18n": make_module("web.i18n", get_language=lambda: "zh_CN"),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        service = runpy.run_path(str(ROOT / "pixelle_video/services/api_media.py"))[
            "APIProviderMediaService"
        ]
        self.service = service({})
        # 本组只验证控件能力，明确模拟用户已加载完整测试目录；真实快照过滤另有测试。
        self.service.list_available_workflows = Mock(side_effect=self.service.list_workflows)
        self.helper_path = str(ROOT / "web/pipelines/api_workflows.py")

    def render(self, provider, model, **options):
        workflow = self.service.resolve_workflow(f"api/{provider}/{model}")
        script = (
            "import runpy\nimport streamlit as st\n"
            f"helpers = runpy.run_path({self.helper_path!r})\n"
            f"st.session_state['params'] = helpers['render_api_video_controls']({workflow!r}, "
            f"key_prefix='test', **{options!r})\n"
        )
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        return app

    def assert_no_unsupported_fields(self, app):
        self.assertFalse(app.text_area)
        self.assertNotIn("test_api_watermark", [item.key for item in app.checkbox])
        params = app.session_state["params"]
        self.assertNotIn("negative_prompt", params)
        self.assertNotIn("watermark", params)

    def test_grok_resolutions_and_audio_match_each_model(self):
        """经典模型最高 720p，两个 1.5 模型另有 1080p，音频开关真实返回。"""
        for model in ("grok-imagine-video", "grok-imagine-video-1.5", "grok-imagine-video-1.5-lite"):
            with self.subTest(model=model):
                app = self.render("xai", model)
                expected = ["720p", "480p"] + ([] if model == "grok-imagine-video" else ["1080p"])
                self.assertEqual(app.selectbox(key="test_api_resolution").options, expected)
                self.assertEqual(app.slider(key="test_api_duration").min, 1)
                self.assertEqual(app.slider(key="test_api_duration").max, 15)
                self.assertEqual(app.session_state["params"]["resolution"], "720p")
                self.assertFalse(app.session_state["params"]["generate_audio"])
                self.assertEqual(app.session_state["params"]["video_ratio"], "9:16")
                self.assert_no_unsupported_fields(app)
                app.checkbox(key="test_api_generate_audio").set_value(True).run()
                self.assertFalse(app.exception)
                self.assertTrue(app.session_state["params"]["generate_audio"])

    def test_muse_discrete_duration_and_supported_fields_only(self):
        """Muse 只可选 5/6/8/10 秒，不显示不存在的分辨率与音频选项。"""
        app = self.render("muse", "muse-video", default_duration=7)
        self.assertEqual(
            [int(value) for value in app.select_slider(key="test_api_duration").options],
            [5, 6, 8, 10],
        )
        self.assertEqual(app.session_state["params"]["duration"], 6)
        self.assertEqual(app.selectbox(key="test_api_ratio").options, ["16:9", "9:16"])
        self.assertFalse(app.slider)
        self.assertFalse(app.checkbox)
        self.assertNotIn("test_api_resolution", [item.key for item in app.selectbox])
        self.assert_no_unsupported_fields(app)
        app.select_slider(key="test_api_duration").set_value(10).run()
        self.assertEqual(app.session_state["params"], {"duration": 10, "video_ratio": "9:16"})

    def test_previous_providers_keep_controls(self):
        """新提供商的参数屏蔽不会影响万相、Seedance 已传递的选项。"""
        for provider, model in (
            ("dashscope", "wan2.7-t2v"),
            ("seedance", "doubao-seedance-2-0-260128"),
        ):
            with self.subTest(provider=provider):
                app = self.render(provider, model)
                self.assertEqual(len(app.text_area), 1)
                self.assertIn("test_api_watermark", [item.key for item in app.checkbox])
                self.assertTrue(app.selectbox(key="test_api_resolution").options)
                if provider == "seedance":
                    self.assertFalse(app.session_state["params"]["generate_audio"])
                else:
                    self.assertEqual(app.slider(key="test_api_duration").min, 2)
                    self.assertEqual(app.slider(key="test_api_duration").max, 15)

    def test_kling_only_exposes_parameters_sent_by_adapter(self):
        """可灵不展示被后端丢弃的分辨率和水印，音频开关按型号能力提供。"""
        for model in ("kling-v3", "kling-v2-6", "kling-v2-5-turbo"):
            with self.subTest(model=model):
                app = self.render("kling", model)
                self.assertNotIn("test_api_resolution", [item.key for item in app.selectbox])
                self.assertNotIn("test_api_watermark", [item.key for item in app.checkbox])
                self.assertNotIn("resolution", app.session_state["params"])
                self.assertNotIn("watermark", app.session_state["params"])
                app.text_area(key="test_api_negative_prompt").set_value("避免模糊").run()
                self.assertEqual(app.session_state["params"]["negative_prompt"], "避免模糊")
                if model == "kling-v2-5-turbo":
                    self.assertNotIn("test_api_kling_sound", [item.key for item in app.checkbox])
                    self.assertNotIn("sound", app.session_state["params"])
                else:
                    self.assertEqual(app.session_state["params"]["sound"], "off")
                    app.checkbox(key="test_api_kling_sound").set_value(True).run()
                    self.assertEqual(app.session_state["params"]["sound"], "on")
                if model != "kling-v3":
                    self.assertEqual([int(value) for value in app.select_slider(key="test_api_duration").options], [5, 10])

    def test_kling_switch_to_non_audio_model_drops_stale_sound(self):
        """用户先开启声音再切到 v2.5 时，旧状态不会作为有效参数返回。"""
        workflows = [self.service.resolve_workflow(f"api/kling/{model}")
                     for model in ("kling-v3", "kling-v2-5-turbo")]
        script = (
            "import runpy\nimport streamlit as st\n"
            f"helpers = runpy.run_path({self.helper_path!r})\n"
            f"workflows = {workflows!r}\n"
            "model = st.selectbox('model', [w['model'] for w in workflows], key='model')\n"
            "workflow = next(w for w in workflows if w['model'] == model)\n"
            "st.session_state['params'] = helpers['render_api_video_controls'](workflow, key_prefix='test')\n"
        )
        app = AppTest.from_string(script).run()
        app.checkbox(key="test_api_kling_sound").set_value(True).run()
        app.selectbox(key="model").set_value("kling-v2-5-turbo").run()
        self.assertFalse(app.exception)
        self.assertNotIn("sound", app.session_state["params"])

    def test_narration_duration_mode_omits_manual_duration(self):
        """快捷创作由旁白决定时长时，不向运行参数重复注入手动时长。"""
        for provider, model in (("xai", "grok-imagine-video"), ("muse", "muse-video")):
            with self.subTest(provider=provider):
                app = self.render(provider, model, show_duration=False)
                self.assertFalse(app.slider)
                self.assertFalse(app.select_slider)
                self.assertNotIn("duration", app.session_state["params"])

    def test_new_models_available_for_quick_create_and_image_to_video(self):
        """两种页面的能力筛选均能列出新接入模型。"""
        helper = runpy.run_path(self.helper_path)["list_api_media_workflows"]
        for ability in ("text_to_video", "first_frame_i2v"):
            workflows = helper(
                types.SimpleNamespace(api_media=self.service), "video", [ability], verified_only=True
            )
            self.assertEqual(
                {item["model"] for item in workflows if item["provider"] in {"xai", "muse"}},
                {"grok-imagine-video", "grok-imagine-video-1.5", "grok-imagine-video-1.5-lite", "muse-video"},
            )

    def test_switching_models_does_not_keep_unsupported_values(self):
        """共用控件 key 切换模型时，不遗留上个模型的 1080p 或音频参数。"""
        workflows = [
            self.service.resolve_workflow(key)
            for key in ("api/xai/grok-imagine-video-1.5", "api/xai/grok-imagine-video", "api/muse/muse-video")
        ]
        script = (
            "import runpy\nimport streamlit as st\n"
            f"helpers = runpy.run_path({self.helper_path!r})\n"
            f"workflows = {workflows!r}\n"
            "model = st.selectbox('model', [w['model'] for w in workflows], key='model')\n"
            "workflow = next(w for w in workflows if w['model'] == model)\n"
            "st.session_state['params'] = helpers['render_api_video_controls'](workflow, key_prefix='test')\n"
        )
        app = AppTest.from_string(script).run()
        app.selectbox(key="test_api_resolution").set_value("1080p").run()
        app.checkbox(key="test_api_generate_audio").set_value(True).run()
        app.selectbox(key="model").set_value("grok-imagine-video").run()
        self.assertFalse(app.exception)
        self.assertIn(app.session_state["params"]["resolution"], ["480p", "720p"])
        app.selectbox(key="model").set_value("muse-video").run()
        self.assertFalse(app.exception)
        self.assertNotIn("resolution", app.session_state["params"])
        self.assertNotIn("generate_audio", app.session_state["params"])
        self.assertIn(app.session_state["params"]["duration"], [5, 6, 8, 10])

    def test_image_to_video_with_manual_prompt_does_not_require_llm(self):
        """未配置 LLM 时，手写提示词的 Grok/Muse 图生视频仍能调用媒体服务。"""
        with tempfile.TemporaryDirectory() as output_dir:
            for workflow in ("api/xai/grok-imagine-video", "api/muse/muse-video"):
                with self.subTest(workflow=workflow):
                    manager = Mock()
                    manager.validate.return_value = False

                    async def generate_media(**params):
                        # 本地假视频仅用于界面结果分支，不执行编码或远程模型调用。
                        Path(params["output_path"]).write_bytes(b"test-video-preview")
                        return types.SimpleNamespace(url=params["output_path"])

                    # 真实提交会复核模型目录，测试替身同步提供已隔离的 API 能力表。
                    core = types.SimpleNamespace(media=AsyncMock(side_effect=generate_media), api_media=self.service)
                    save_history = AsyncMock()
                    params = {
                        "audio_assets": [str(Path(output_dir) / "input.png")],
                        "prompt_text": "镜头缓慢向前推进",
                        "workflow_key": workflow,
                        "api_video_params": {"duration": 5, "video_ratio": "9:16"},
                    }
                    helpers = runpy.run_path(self.helper_path)
                    modules = {
                        "pixelle_video.config": make_module("pixelle_video.config", config_manager=manager),
                        "pixelle_video.utils.os_util": make_module(
                            "pixelle_video.utils.os_util",
                            create_task_output_dir=lambda: (output_dir, "test-task"),
                        ),
                        "web.i18n": make_module(
                            "web.i18n", tr=lambda key, **values: key, get_language=lambda: "zh_CN"
                        ),
                        "web.pipelines": make_module("web.pipelines", __path__=[]),
                        "web.pipelines.api_workflows": make_module("web.pipelines.api_workflows", **{
                            key: value for key, value in helpers.items() if not key.startswith("__")
                        }),
                        "web.pipelines.base": make_module(
                            "web.pipelines.base", PipelineUI=object, register_pipeline_ui=lambda ui: None
                        ),
                        "web.components": make_module("web.components", __path__=[]),
                        "web.components.content_input": make_module(
                            "web.components.content_input", render_version_info=lambda: None
                        ),
                        "web.utils": make_module("web.utils", __path__=[]),
                        "web.utils.async_helpers": make_module("web.utils.async_helpers", run_async=asyncio.run),
                        "web.utils.history_persistence": make_module(
                            "web.utils.history_persistence", save_web_generation_history=save_history
                        ),
                        "web.utils.streamlit_helpers": make_module(
                            "web.utils.streamlit_helpers", check_and_warn_selfhost_workflow=lambda key: None
                        ),
                        "test_i2v_bridge": make_module("test_i2v_bridge", core=core, params=params),
                    }
                    i2v_path = str(ROOT / "web/pipelines/i2v.py")
                    script = (
                        "import runpy\nfrom test_i2v_bridge import core, params\n"
                        f"ui = runpy.run_path({i2v_path!r})['ImageToVideoPipelineUI']()\n"
                        "ui._render_output_preview(core, params)\n"
                    )
                    with patch.dict(sys.modules, modules):
                        app = AppTest.from_string(script).run()
                        self.assertFalse(app.exception)
                        self.assertFalse(app.warning)
                        app.button(key="i2v_generate").click().run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.error)
                    core.media.assert_awaited_once()
                    self.assertEqual(core.media.await_args.kwargs["workflow"], workflow)
                    self.assertEqual(core.media.await_args.kwargs["prompt"], params["prompt_text"])
                    self.assertEqual(core.media.await_args.kwargs["image_path"], params["audio_assets"][0])
                    save_history.assert_awaited_once()
                    manager.validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
