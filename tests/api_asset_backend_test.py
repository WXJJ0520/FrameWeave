"""验证素材 API 路径不被旧工作流配置带偏；所有外部请求与媒体进程均隔离。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pixelle_video.pipelines.asset_based import AssetBasedPipeline
from pixelle_video.services.tts_service import TTSService


class APIAssetBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # 使用真实 TTS 分流逻辑和旧模式配置，只替换网络执行方法。
        self.tts = TTSService({"comfyui": {"tts": {"inference_mode": "comfyui"}}})
        self.tts._call_local_tts = AsyncMock(return_value="offline-narration.mp3")
        self.tts._resolve_workflow = Mock(return_value={"key": "runninghub/tts_legacy.json"})
        self.tts._call_comfyui_workflow = AsyncMock(return_value="offline-legacy.mp3")
        self.frame = SimpleNamespace(
            _scene_data={"narrations": ["这是离线测试旁白。"]},
            index=0,
            narration="这是离线测试旁白。",
            image_path="offline-source.png",
            video_path=None,
            media_type="image",
            duration=None,
            video_segment_path=None,
        )
        self.core = SimpleNamespace(
            llm=AsyncMock(),
            tts=self.tts,
            media=AsyncMock(),
            video=Mock(),
            frame_processor=AsyncMock(return_value=self.frame),
            api_asset_analysis=SimpleNamespace(
                analyze_image=AsyncMock(return_value="图片素材说明"),
                analyze_video=AsyncMock(return_value="视频素材说明"),
            ),
            image_analysis=AsyncMock(),
            video_analysis=AsyncMock(),
        )
        self.pipeline = AssetBasedPipeline(self.core)
        self.pipeline._progress_callback = None

    def context(self, source="api", **request):
        """最小上下文保留真实配音、媒体与合成调用顺序。"""
        return SimpleNamespace(
            request={"source": source, **request},
            storyboard=SimpleNamespace(frames=[self.frame], total_duration=0),
            config=SimpleNamespace(voice_id="zh-CN-YunjianNeural", tts_speed=1.2),
            task_dir=Path(self.temp.name),
            task_id="offline-test",
        )

    def produce(self, context):
        # 只模拟时长探测，不运行 FFprobe 或任何生成服务。
        with patch("subprocess.run", return_value=SimpleNamespace(stdout="3.0")):
            return asyncio.run(self.pipeline.produce_assets(context))

    def test_api_source_overrides_legacy_tts_config(self):
        result = self.produce(self.context())
        self.tts._call_local_tts.assert_awaited_once()
        self.tts._resolve_workflow.assert_not_called()
        self.tts._call_comfyui_workflow.assert_not_awaited()
        self.core.media.assert_not_awaited()
        self.assertEqual(result.storyboard.total_duration, 3)

    def test_edge_failure_does_not_fall_back_to_workflow(self):
        self.tts._call_local_tts.side_effect = RuntimeError("offline speech failure")
        with self.assertRaisesRegex(RuntimeError, "offline speech failure"):
            self.produce(self.context())
        self.tts._resolve_workflow.assert_not_called()
        self.tts._call_comfyui_workflow.assert_not_awaited()
        self.core.frame_processor.assert_not_awaited()

    def test_legacy_cli_source_keeps_existing_tts_config(self):
        self.produce(self.context(source="runninghub"))
        self.tts._call_local_tts.assert_not_awaited()
        self.tts._call_comfyui_workflow.assert_awaited_once()

    def test_api_source_rejects_stale_animation_before_speech(self):
        with self.assertRaisesRegex(ValueError, "直接 API 模型"):
            self.produce(self.context(api_video_workflow="runninghub/video_old.json"))
        self.tts._call_local_tts.assert_not_awaited()
        self.tts._call_comfyui_workflow.assert_not_awaited()
        self.core.media.assert_not_awaited()

    def test_animation_driving_audio_requires_both_opt_in_and_adapter_capability(self):
        """真实媒体调用仅在勾选且支持音频驱动时携带旁白，不能忽略 False。"""
        for enabled in (False, True):
            for supports_audio in (False, True):
                with self.subTest(enabled=enabled, supports_audio=supports_audio):
                    # 同一个测试循环重置被真实素材管线改为 video 的分镜状态。
                    self.frame.media_type = "image"
                    self.frame.image_path = "offline-source.png"
                    self.core.media.reset_mock()
                    self.core.media.return_value = SimpleNamespace(url="offline-generated.mp4")
                    context = self.context(
                        api_video_workflow="api/test/video",
                        api_video_params={"use_narration_audio_as_driving_audio": enabled},
                    )
                    context.config.media_width = 160
                    context.config.media_height = 90
                    abilities = ["first_frame_i2v"] + (["audio_driven_i2v"] if supports_audio else [])
                    with patch.object(self.pipeline, "_get_api_workflow_info", return_value={"adapter_ability_types": abilities}), \
                            patch.object(self.pipeline, "_extract_video_tail_frame", return_value=None), \
                            patch("pixelle_video.pipelines.asset_based.get_task_frame_path", return_value="offline-generated.mp4"):
                        self.produce(context)
                    sent = self.core.media.await_args.kwargs
                    self.assertEqual("audio_path" in sent, enabled and supports_audio)
                    if enabled and supports_audio:
                        self.assertEqual(sent["audio_path"], self.frame.audio_path)
                    self.assertNotIn("use_narration_audio_as_driving_audio", sent)

    def test_api_analysis_never_calls_legacy_workflows(self):
        """两种素材分析均走指定 VLM；视频分析异常也不能回退到云工作流。"""
        image_path = Path(self.temp.name) / "source.png"
        video_path = Path(self.temp.name) / "source.mp4"
        image_path.write_bytes(b"offline-image")
        video_path.write_bytes(b"offline-video")
        self.core.api_asset_analysis.analyze_video.side_effect = RuntimeError("offline VLM failure")
        context = self.context(assets=[str(image_path), str(video_path)], analysis_vlm_model="qwen3.7-plus")
        with patch(
            "pixelle_video.pipelines.asset_based.create_task_output_dir",
            return_value=(self.temp.name, "offline-test"),
        ), patch(
            "pixelle_video.pipelines.asset_based.get_task_final_video_path",
            return_value=str(Path(self.temp.name) / "final.mp4"),
        ):
            result = asyncio.run(self.pipeline.setup_environment(context))
        self.core.api_asset_analysis.analyze_image.assert_awaited_once_with(
            str(image_path), model="qwen3.7-plus",
        )
        self.core.api_asset_analysis.analyze_video.assert_awaited_once_with(
            str(video_path), model="qwen3.7-plus",
        )
        self.core.image_analysis.assert_not_awaited()
        self.core.video_analysis.assert_not_awaited()
        self.assertEqual(result.asset_index[str(video_path)]["description"], "Video asset (analysis failed)")
