"""API 入口回归：隔离真实配置和网络，检查模型能力筛选与旧会话迁移。"""

import asyncio
import base64
import io
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def module(name, **attributes):
    """只加载待测模块，不触发项目全局配置读取。"""
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class APIPipelineRoutesTest(unittest.TestCase):
    def setUp(self):
        self.media = AsyncMock()
        self.legacy = AsyncMock(side_effect=AssertionError("不能调用旧工作流"))
        self.core = types.SimpleNamespace(media=self.media, _get_or_create_comfykit=self.legacy)
        self.config = types.SimpleNamespace(validate=Mock(return_value=False))
        modules = {
            "pixelle_video": module("pixelle_video", __path__=[]),
            "pixelle_video.config": module("pixelle_video.config", config_manager=self.config),
            "pixelle_video.models": module("pixelle_video.models", __path__=[]),
            "pixelle_video.models.media": module("pixelle_video.models.media", MediaResult=object),
            "pixelle_video.utils": module("pixelle_video.utils", __path__=[]),
            "pixelle_video.utils.os_util": module(
                "pixelle_video.utils.os_util",
                get_output_path=lambda *args: "unused",
                create_task_output_dir=Mock(side_effect=AssertionError("本组测试不执行生成")),
            ),
            "web": module("web", __path__=[]),
            "web.i18n": module(
                "web.i18n",
                get_language=lambda: getattr(self, "language", "zh_CN"),
                tr=lambda key, **kw: key,
            ),
            "web.pipelines": module("web.pipelines", __path__=[]),
            "web.pipelines.base": module(
                "web.pipelines.base", PipelineUI=object, register_pipeline_ui=lambda cls: None
            ),
            "web.components.digital_tts_config": module(
                "web.components.digital_tts_config",
                render_style_config=Mock(
                    return_value={
                        "tts_inference_mode": "local",
                        "tts_voice": "test-voice",
                        "tts_speed": 1.0,
                    }
                ),
            ),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run),
            "web.utils.history_persistence": module(
                "web.utils.history_persistence", save_web_generation_history=AsyncMock()
            ),
            "moviepy.editor": module("moviepy.editor", VideoFileClip=Mock()),
            "api_pipeline_test_context": module("api_pipeline_test_context", core=self.core),
        }
        # 反馈函数没有配置读取；保留其真实实现以覆盖页面导入关系。
        feedback = runpy.run_path(str(ROOT / "web/utils/generation_feedback.py"))
        modules["web.utils.generation_feedback"] = module(
            "web.utils.generation_feedback",
            **{
                name: feedback[name]
                for name in (
                    "GenerationProgress",
                    "MissingGeneratedVideoError",
                    "build_generation_failure",
                )
            },
        )
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 加载真实公共步骤组件，验证导航回调与页面输入控件的实际生命周期。
        flow = runpy.run_path(str(ROOT / "web/components/creation_flow.py"))
        sys.modules["web.components.creation_flow"] = module(
            "web.components.creation_flow", CreationFlow=flow["CreationFlow"]
        )
        uploads = runpy.run_path(str(ROOT / "web/components/creation_uploads.py"))
        sys.modules["web.components.creation_uploads"] = module(
            "web.components.creation_uploads",
            persist_uploaded_files=uploads["persist_uploaded_files"],
        )
        service = runpy.run_path(str(ROOT / "pixelle_video/services/api_media.py"))[
            "APIProviderMediaService"
        ]
        self.core.api_media = service({})
        # 此组只验证表单的能力路由；模拟已加载全部已适配型号，目录隔离另有专测。
        self.core.api_media.list_available_workflows = Mock(side_effect=self.core.api_media.list_workflows)
        helpers = runpy.run_path(str(ROOT / "web/pipelines/api_workflows.py"))
        sys.modules["web.pipelines.api_workflows"] = module(
            "web.pipelines.api_workflows",
            **{
                name: helpers[name]
                for name in (
                    "is_api_workflow",
                    "list_api_media_workflows",
                    "render_api_video_controls",
                    "workflow_select_help",
                )
            },
        )
        network = patch("httpx.AsyncClient.send", side_effect=AssertionError("禁止真实网络请求"))
        network.start()
        self.addCleanup(network.stop)

    def open_form(self, filename, classname, method, state=None):
        script = (
            "import runpy\nimport streamlit as st\nfrom api_pipeline_test_context import core\n"
            f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
            f"st.session_state['result'] = ui.{method}(core)\n"
        )
        app = AppTest.from_string(script)
        for key, value in (state or {}).items():
            app.session_state[key] = value
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_media_pages_keep_fields_mounted_and_drafts_across_steps(self):
        """三个真实页面来回切步，检查提示词、模型和上传控件身份没有丢失。"""
        cases = (
            (
                "i2v.py",
                "ImageToVideoPipelineUI",
                "image_to_video",
                "audio_box",
                "i2v_workflow_select",
            ),
            (
                "action_transfer.py",
                "ActionTransferPipelineUI",
                "action_transfer",
                "prompt_box",
                "action_transfer_workflow_select",
            ),
            (
                "digital_human.py",
                "DigitalHumanPipelineUI",
                "digital_human",
                "digital_box",
                "digital_human_video_workflow",
            ),
        )
        for filename, classname, flow_key, prompt_key, model_key in cases:
            with self.subTest(page=filename):
                script = (
                    "import runpy\nfrom api_pipeline_test_context import core\n"
                    f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
                    "ui.render(core)\n"
                )
                app = AppTest.from_string(script).run()
                self.assertFalse(app.exception)
                self.assertFalse(app.tabs)
                self.assertTrue(app.button(key=f"creation_flow_{flow_key}_previous").disabled)
                # AppTest 暂无上传操作API；稳定 uploader id 证明控件不会在步骤间卸载。
                upload_ids = [item.proto.id for item in app.get("file_uploader")]
                self.assertTrue(upload_ids)
                app.text_area(key=prompt_key).set_value("保留这段测试文案").run()
                model_name = app.selectbox(key=model_key).options[-1]
                app.selectbox(key=model_key).select(model_name).run()
                app.button(key=f"creation_flow_{flow_key}_next").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state[f"creation_flow_{flow_key}_step"], 1)
                self.assertEqual(app.text_area(key=prompt_key).value, "保留这段测试文案")
                self.assertEqual([item.proto.id for item in app.get("file_uploader")], upload_ids)
                self.assertTrue(all(item.label != "btn.generate" for item in app.button))
                app.button(key=f"creation_flow_{flow_key}_next").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state[f"creation_flow_{flow_key}_step"], 2)
                self.assertEqual(
                    len([item for item in app.button if item.label == "btn.generate"]), 1
                )
                app.button(key=f"creation_flow_{flow_key}_previous").click().run()
                app.button(key=f"creation_flow_{flow_key}_previous").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.text_area(key=prompt_key).value, "保留这段测试文案")
                self.assertEqual(app.selectbox(key=model_key).value, model_name)
                self.assertEqual([item.proto.id for item in app.get("file_uploader")], upload_ids)
                self.media.assert_not_awaited()
                self.legacy.assert_not_awaited()

    def test_uploaded_assets_keep_same_local_paths_through_navigation(self):
        """上传接口使用内存测试文件，执行真实缓存/预览逻辑，不访问用户素材。"""
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
        )

        def upload(label, *, type, key, **kwargs):
            is_video = "mp4" in type
            asset = io.BytesIO(b"fake-video" if is_video else png)
            asset.name = f"{key}.mp4" if is_video else f"{key}.png"
            return [asset]

        class VideoInfo:
            """只替换视频解码器，其余上传与步骤渲染使用真实实现。"""

            duration = 8.0

            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        sys.modules["moviepy.editor"].VideoFileClip = VideoInfo
        with tempfile.TemporaryDirectory() as directory:
            for filename, classname, flow_key, cache_keys, asset_keys in (
                (
                    "i2v.py",
                    "ImageToVideoPipelineUI",
                    "image_to_video",
                    ["i2v_images"],
                    ["audio_assets"],
                ),
                (
                    "action_transfer.py",
                    "ActionTransferPipelineUI",
                    "action_transfer",
                    ["action_transfer_videos", "action_transfer_images"],
                    ["video_assets", "image_assets"],
                ),
                (
                    "digital_human.py",
                    "DigitalHumanPipelineUI",
                    "digital_human",
                    ["digital_human_characters", "digital_human_products"],
                    ["character_assets", "goods_assets"],
                ),
            ):
                with (
                    self.subTest(page=filename),
                    patch("streamlit.file_uploader", side_effect=upload),
                ):
                    script = (
                        "import runpy\nimport streamlit as st\nfrom api_pipeline_test_context import core\n"
                        f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
                        # 只收集最终参数，确保测试不会点击或执行任何生成服务。
                        "ui._render_output_preview = lambda core, params: st.session_state.__setitem__('preview_params', params)\n"
                        "ui.render(core)\n"
                    )
                    app = AppTest.from_string(script)
                    for key in cache_keys:
                        app.session_state[f"creation_upload_{key}"] = {
                            "directory": str(Path(directory) / key),
                            "files": {},
                        }
                    app.run()
                    self.assertFalse(app.exception)
                    initial_paths = [
                        list(app.session_state[f"creation_upload_{key}"]["files"].values())[0]
                        for key in cache_keys
                    ]
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    self.assertFalse(app.exception)
                    params = app.session_state["preview_params"]
                    self.assertEqual([params[key][0] for key in asset_keys], initial_paths)
                    app.button(key=f"creation_flow_{flow_key}_previous").click().run()
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(
                        [app.session_state["preview_params"][key][0] for key in asset_keys],
                        initial_paths,
                    )
                    for key in cache_keys:
                        self.assertEqual(len(list((Path(directory) / key).iterdir())), 1)
                    self.media.assert_not_awaited()

    def test_previous_result_returns_after_navigation_without_api_call(self):
        """只预置测试本地文件，三个页面均保留成品预览而不提交生成任务。"""
        with tempfile.TemporaryDirectory() as directory:
            video_path = Path(directory) / "result.mp4"
            video_path.write_bytes(b"fake-video-preview")
            for filename, classname, flow_key in (
                ("i2v.py", "ImageToVideoPipelineUI", "image_to_video"),
                ("action_transfer.py", "ActionTransferPipelineUI", "action_transfer"),
                ("digital_human.py", "DigitalHumanPipelineUI", "digital_human"),
            ):
                with self.subTest(page=filename):
                    script = (
                        "import runpy\nfrom api_pipeline_test_context import core\n"
                        f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
                        "ui.render(core)\n"
                    )
                    app = AppTest.from_string(script)
                    app.session_state[f"creation_result_{flow_key}"] = {
                        "path": str(video_path),
                        "elapsed": 2.0,
                    }
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.get("video"))
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.get("video")), 1)
                    self.assertEqual(len(app.get("download_button")), 1)
                    app.button(key=f"creation_flow_{flow_key}_previous").click().run()
                    self.assertFalse(app.get("video"))
                    app.button(key=f"creation_flow_{flow_key}_next").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.get("video")), 1)
                    self.assertEqual(
                        app.session_state[f"creation_result_{flow_key}"]["path"], str(video_path)
                    )
                    self.media.assert_not_awaited()

    def test_image_to_video_keeps_grok_muse_and_migrates_old_source(self):
        app = self.open_form(
            "i2v.py",
            "ImageToVideoPipelineUI",
            "render_audio_visual_input",
            {
                "i2v_workflow_source": "runninghub",
                "i2v_workflow_select": "i2v_workflow.json",
            },
        )
        self.assertEqual(app.session_state["i2v_workflow_source"], "api")
        self.assertFalse(app.radio)
        options = app.selectbox(key="i2v_workflow_select").options
        self.assertTrue(any("grok-imagine-video" in name for name in options))
        self.assertTrue(any("muse-video" in name for name in options))
        self.assertTrue(all(" - API " in name for name in options))
        self.assertTrue(app.session_state["result"]["workflow_key"].startswith("api/"))

    def test_action_transfer_filters_out_generic_image_to_video(self):
        app = self.open_form(
            "action_transfer.py",
            "ActionTransferPipelineUI",
            "render_action_transfer_assets_input",
            {
                "action_transfer_workflow_source": "selfhost",
                "action_transfer_workflow_select": "af_workflow.json",
            },
        )
        self.assertFalse(app.radio)
        self.assertEqual(app.session_state["action_transfer_workflow_source"], "api")
        options = app.selectbox(key="action_transfer_workflow_select").options
        self.assertTrue(any("wan2.7-videoedit" in name for name in options))
        self.assertFalse(any("Grok" in name or "Muse" in name for name in options))

    def test_digital_human_requires_reference_audio_instead_of_native_audio(self):
        app = self.open_form(
            "digital_human.py",
            "DigitalHumanPipelineUI",
            "workflow_path_config",
            {
                "digital_human_video_service_source": "runninghub",
                "digital_human_image_workflow": "digital_image.json",
                "digital_human_video_workflow": "digital_combination.json",
            },
        )
        self.assertFalse(app.radio)
        self.assertEqual(app.session_state["digital_human_video_service_source"], "api")
        self.assertEqual(
            app.selectbox(key="digital_human_video_workflow").options,
            ["wan2.7-r2v - API Dashscope"],
        )
        self.assertNotIn("digital_human_image_workflow", app.session_state.filtered_state)
        self.assertTrue(any("不保证" in item.value for item in app.info))
        result = app.session_state["result"]
        self.assertEqual(result["api_video_workflow"], "api/dashscope/wan2.7-r2v")
        self.assertNotIn("second_workflow_path", result)

    def test_missing_api_catalog_disables_model_instead_of_falling_back(self):
        self.core.api_media = types.SimpleNamespace(list_available_workflows=lambda: [])
        cases = (
            (
                "i2v.py",
                "ImageToVideoPipelineUI",
                "render_audio_visual_input",
                "i2v_workflow_select",
                "workflow_key",
            ),
            (
                "action_transfer.py",
                "ActionTransferPipelineUI",
                "render_action_transfer_assets_input",
                "action_transfer_workflow_select",
                "workflow_key",
            ),
            (
                "digital_human.py",
                "DigitalHumanPipelineUI",
                "workflow_path_config",
                "digital_human_video_workflow",
                "api_video_workflow",
            ),
        )
        for filename, classname, method, key, output_key in cases:
            with self.subTest(page=filename):
                app = self.open_form(filename, classname, method)
                self.assertFalse(app.radio)
                self.assertTrue(app.selectbox(key=key).disabled)
                self.assertIsNone(app.session_state["result"][output_key])
                self.assertTrue(app.warning)

    def test_old_or_incompatible_selection_cannot_reach_generation(self):
        """直接调用输出边界，证明隐藏的历史值不能绕过新选择器。"""
        for filename, classname in (
            ("i2v.py", "ImageToVideoPipelineUI"),
            ("action_transfer.py", "ActionTransferPipelineUI"),
        ):
            for key in (
                "runninghub/old.json",
                "selfhost/old.json",
                "api/not-registered",
                "api/dashscope/wan2.7-t2v",
            ):
                with self.subTest(page=filename, key=key):
                    params = {
                        "workflow_key": key,
                        "audio_assets": ["image.png"],
                        "image_assets": ["image.png"],
                        "video_assets": ["video.mp4"],
                        "prompt_text": "test",
                    }
                    script = (
                        "import runpy\nfrom api_pipeline_test_context import core\n"
                        f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
                        f"ui._render_output_preview(core, {params!r})\n"
                    )
                    app = AppTest.from_string(script).run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.button), 1)
                    self.assertTrue(app.button[0].disabled)
                    self.media.assert_not_awaited()
                    self.legacy.assert_not_awaited()
                    self.config.validate.assert_not_called()

    def test_valid_api_generation_preserves_media_parameters_without_llm(self):
        """用本地假结果验证两条 API 路径，不调用模型、不依赖文案模型配置。"""
        with tempfile.TemporaryDirectory() as output_dir:
            sys.modules["pixelle_video.utils.os_util"].create_task_output_dir = lambda: (
                output_dir,
                "test-task",
            )

            async def generate_media(**params):
                Path(params["output_path"]).write_bytes(b"test-video-preview")
                return types.SimpleNamespace(url=params["output_path"])

            self.media.side_effect = generate_media
            cases = (
                (
                    "i2v.py",
                    "ImageToVideoPipelineUI",
                    "i2v_generate",
                    "api/xai/grok-imagine-video",
                    {"image_path": "image.png"},
                ),
                (
                    "action_transfer.py",
                    "ActionTransferPipelineUI",
                    "transfer_generate",
                    "api/dashscope/wan2.7-videoedit",
                    {"reference_image_path": "image.png", "first_clip_path": "video.mp4"},
                ),
            )
            for filename, classname, button_key, workflow_key, media_inputs in cases:
                with self.subTest(page=filename):
                    self.media.reset_mock()
                    params = {
                        "workflow_key": workflow_key,
                        "audio_assets": ["image.png"],
                        "image_assets": ["image.png"],
                        "video_assets": ["video.mp4"],
                        "prompt_text": "test",
                        "duration": 5,
                        "api_video_params": {"duration": 5, "resolution": "720P"},
                    }
                    script = (
                        "import runpy\nfrom api_pipeline_test_context import core\n"
                        f"ui = runpy.run_path({str(ROOT / 'web/pipelines' / filename)!r})[{classname!r}]()\n"
                        f"ui._render_output_preview(core, {params!r})\n"
                    )
                    app = AppTest.from_string(script).run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.button(key=button_key).disabled)
                    app.button(key=button_key).click().run()
                    self.assertFalse(app.exception)
                    self.assertFalse(app.error)
                    self.media.assert_awaited_once()
                    media_params = self.media.call_args.kwargs
                    self.assertEqual(media_params["workflow"], workflow_key)
                    self.assertEqual(media_params["duration"], 5)
                    self.assertEqual(media_params["resolution"], "720P")
                    for key, value in media_inputs.items():
                        self.assertEqual(media_params[key], value)
                    self.legacy.assert_not_awaited()
                    self.config.validate.assert_not_called()
                    self.assertEqual(len(app.get("video")), 1)
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.get("video")), 1)
                    self.assertEqual(len(app.get("download_button")), 1)
                    self.media.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
