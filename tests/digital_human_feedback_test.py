"""离线执行数字人口播分支，验证阶段归属、无重试及诊断不泄露第三方凭据。"""

import asyncio
import runpy
import sys
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from web.utils.generation_feedback import build_generation_failure

ROOT = Path(__file__).resolve().parents[1]
SECRET = "test-token-do-not-display"


def module(name, **attributes):
    """只替换界面与外部依赖，执行真实流程分支而不加载真实配置。"""
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class StopRendering(BaseException):
    """模拟 Streamlit 停止脚本，不能被业务的 Exception 分支再次捕获。"""


class DigitalHumanFeedbackTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.api_models = Mock(
            return_value=[
                {
                    "key": "api/test-video",
                    "display_name": "Test API",
                    "api_contract_verified": True,
                    "adapter_ability_types": ["digital_human", "voice_reference"],
                    "capabilities": {"adapter_input_modalities": ["text", "image", "audio"]},
                }
            ]
        )
        self.st = Mock()
        self.st.container.side_effect = lambda **kwargs: nullcontext()
        # 结果占位容器需要模拟上下文；缓存使用独立字典，不读取真实会话。
        self.st.empty.return_value.container.side_effect = lambda **kwargs: nullcontext()
        self.st.session_state = {}
        self.st.expander.side_effect = lambda *args, **kwargs: nullcontext()
        self.st.button.return_value = True
        self.st.stop.side_effect = StopRendering
        self.log = Mock()
        self.history = AsyncMock()
        self.kit = types.SimpleNamespace(execute=AsyncMock())
        self.core = types.SimpleNamespace(
            tts=AsyncMock(),
            media=AsyncMock(),
            llm=AsyncMock(return_value="模拟文案"),
            _get_or_create_comfykit=AsyncMock(return_value=self.kit),
        )
        modules = {
            "streamlit": self.st,
            "loguru": module("loguru", logger=self.log),
            "web.i18n": module(
                "web.i18n", get_language=lambda: "zh_CN", tr=lambda key, **kwargs: key
            ),
            "web.pipelines.base": module(
                "web.pipelines.base", PipelineUI=object, register_pipeline_ui=lambda cls: None
            ),
            "web.pipelines.api_workflows": module(
                "web.pipelines.api_workflows",
                list_api_media_workflows=self.api_models,
                **{
                    name: Mock()
                    for name in (
                        "render_api_video_controls",
                        "workflow_select_help",
                        "workflow_source_help",
                        "workflow_source_label",
                    )
                },
            ),
            "web.components.content_input": module(
                "web.components.content_input", render_version_info=Mock()
            ),
            "web.components.digital_tts_config": module(
                "web.components.digital_tts_config", render_style_config=Mock()
            ),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run),
            "web.utils.history_persistence": module(
                "web.utils.history_persistence", save_web_generation_history=self.history
            ),
            "web.utils.streamlit_helpers": module(
                "web.utils.streamlit_helpers", check_and_warn_selfhost_workflow=Mock()
            ),
            "pixelle_video.config": module(
                "pixelle_video.config", config_manager=types.SimpleNamespace(validate=lambda: True)
            ),
            "pixelle_video.utils.os_util": module(
                "pixelle_video.utils.os_util",
                create_task_output_dir=lambda: (str(self.directory), "test-task"),
            ),
        }
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.ui = runpy.run_path(str(ROOT / "web/pipelines/digital_human.py"))[
            "DigitalHumanPipelineUI"
        ]()
        self.params = {
            "character_assets": ["character.png"],
            "goods_assets": ["product.png"],
            "goods_text": "模拟文案",
            "goods_title": "模拟商品",
            "mode": "customize",
            "tts_inference_mode": "local",
            "tts_voice": "test-voice",
            "tts_speed": 1.0,
            "workflow_path": {
                "api_video_workflow": "api/test-video",
                "api_video_params": {"duration": 5},
            },
        }
        # 任何未替换的网络访问都会使测试立即失败。
        self.network = patch(
            "httpx.AsyncClient.send", side_effect=AssertionError("禁止真实网络请求")
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def render_failure(self, expected_stage):
        self.ui._render_output_preview(self.core, self.params)
        # 失败只退出业务输出区，不能中断外层步骤导航。
        self.st.stop.assert_not_called()
        self.st.error.assert_called_once()
        diagnostic = self.st.code.call_args.args[0]
        self.assertIn(f"stage={expected_stage}\n", diagnostic)
        self.assertNotIn(SECRET, str(self.st.mock_calls))
        self.assertNotIn(SECRET, str(self.log.mock_calls))
        self.log.exception.assert_not_called()
        return diagnostic

    def test_successful_result_survives_rerender_without_regenerating(self):
        """模拟本地成品，确认回到输出步骤只展示结果，不重新请求配音或视频。"""
        final_path = self.directory / "final.mp4"
        final_path.write_bytes(b"fake-video")
        self.core.media.return_value = types.SimpleNamespace(url=str(final_path))
        self.ui._render_output_preview(self.core, self.params)
        self.assertEqual(
            self.st.session_state["creation_result_digital_human"]["path"], str(final_path)
        )
        self.st.button.return_value = False
        self.ui._render_output_preview(self.core, self.params)
        self.core.media.assert_awaited_once()
        self.core.tts.assert_awaited_once()
        self.history.assert_awaited_once()
        self.assertEqual(self.st.video.call_count, 2)
        self.assertEqual(self.st.download_button.call_count, 2)

    def error(self):
        return RuntimeError(f"service failed https://example.invalid/video?api_key={SECRET}")

    def test_tts_failure_does_not_start_video_or_repeat_speech(self):
        self.core.tts.side_effect = self.error()
        self.render_failure("speech")
        self.core.tts.assert_awaited_once()
        self.core.media.assert_not_awaited()
        self.history.assert_not_awaited()

    def test_video_api_failure_is_distinct_from_successful_speech(self):
        self.core.media.side_effect = self.error()
        self.render_failure("video")
        self.core.tts.assert_awaited_once()
        self.core.media.assert_awaited_once()
        self.history.assert_not_awaited()

    def test_old_workflow_selection_is_disabled_without_submitting_any_service(self):
        """已有会话的旧路径不能重新触发云端或本地工作流。"""
        for old_key in (
            None,
            "runninghub/digital_combination.json",
            "selfhost/digital_combination.json",
        ):
            with self.subTest(old_key=old_key):
                self.params["workflow_path"]["api_video_workflow"] = old_key
                self.ui._render_output_preview(self.core, self.params)
                self.assertTrue(self.st.button.call_args.kwargs["disabled"])
                self.core.tts.assert_not_awaited()
                self.core.media.assert_not_awaited()
                self.core._get_or_create_comfykit.assert_not_awaited()

    def test_missing_api_video_result_keeps_video_stage(self):
        self.core.media.return_value = types.SimpleNamespace(url=None)
        diagnostic = self.render_failure("video")
        self.assertIn("MissingGeneratedVideoError", diagnostic)
        self.core.tts.assert_awaited_once()
        self.core.media.assert_awaited_once()
        self.history.assert_not_awaited()

    def test_product_mode_passes_both_images_and_uses_api_reference_speech(self):
        """保留人物与商品参考，不再隐式执行前置图片工作流。"""
        self.params["mode"] = "digital"
        self.params["tts_inference_mode"] = "comfyui"
        self.core.media.side_effect = self.error()
        self.render_failure("video")
        self.core.tts.assert_awaited_once()
        self.assertEqual(self.core.tts.call_args.kwargs["inference_mode"], "local")
        self.assertNotIn("workflow", self.core.tts.call_args.kwargs)
        self.assertEqual(
            self.core.media.call_args.kwargs["reference_image_paths"],
            ["character.png", "product.png"],
        )
        self.assertEqual(
            self.core.media.call_args.kwargs["reference_audio_path"],
            str(self.directory / "narration.mp3"),
        )
        self.core._get_or_create_comfykit.assert_not_awaited()

    def test_capability_disappears_before_submit_stops_at_preparation(self):
        """表单展示后目录变化也不能提交 TTS 或视频任务。"""
        self.api_models.side_effect = [self.api_models.return_value, []]
        self.render_failure("preparation")
        self.core.tts.assert_not_awaited()
        self.core.media.assert_not_awaited()

    def test_script_failure_before_api_video_skips_tts(self):
        self.params["mode"] = "digital"
        self.params["goods_text"] = ""
        self.core.llm.side_effect = self.error()
        self.render_failure("script")
        self.core.llm.assert_awaited_once()
        self.core.tts.assert_not_awaited()

    def test_history_failure_preserves_fact_video_was_generated(self):
        self.core.media.return_value = types.SimpleNamespace(url=str(self.directory / "final.mp4"))
        self.history.side_effect = self.error()
        self.render_failure("history")
        self.assertIn("视频已生成", self.st.error.call_args.args[0])
        self.core.media.assert_awaited_once()
        self.history.assert_awaited_once()

    def test_invalid_video_options_after_speech_are_not_speech_errors(self):
        self.params["workflow_path"]["api_video_params"]["duration"] = "invalid-duration"
        self.render_failure("video")
        self.core.tts.assert_awaited_once()
        self.core.media.assert_not_awaited()


class SafeGenerationFeedbackTest(unittest.TestCase):
    def test_unknown_stage_cannot_inject_context_or_guess_provider(self):
        failure = build_generation_failure(
            f"https://example.invalid?key={SECRET}", RuntimeError(SECRET), "en_US"
        )
        self.assertEqual(failure.stage, "unknown")
        self.assertIn("unknown", failure.message)
        self.assertNotIn(SECRET, repr(failure))

    def test_error_text_is_never_read_and_non_http_status_is_ignored(self):
        class UnprintableError(Exception):
            status = SECRET

            def __str__(self):
                raise AssertionError("不能读取第三方异常原文")

        failure = build_generation_failure("speech", UnprintableError(), "en_US")
        self.assertIsNone(failure.http_status)
        self.assertIn("speech synthesis", failure.message)
        self.assertNotIn(SECRET, failure.diagnostic)


if __name__ == "__main__":
    unittest.main()
