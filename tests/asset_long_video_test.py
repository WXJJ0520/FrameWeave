"""素材长片离线验证：真实预算和路径约束，模型、配音与上传全部隔离。"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pixelle_video.pipelines.asset_based import AssetBasedPipeline
from pixelle_video.pipelines.linear import PipelineContext
from pixelle_video.utils.asset_long_video import (
    asset_usage_summary,
    build_asset_long_video_plan,
    generate_asset_long_script,
    video_window,
)


def script_answers(plan, assets):
    """生成恰好满足章节预算的隔离回答，不调用任何创作模型。"""
    answers = [json.dumps({"chapters": [
        {"title": f"章节{chapter['index']}", "focus": f"不同的讲解重点{chapter['index']}"}
        for chapter in plan["chapters"]
    ]}, ensure_ascii=False)]
    for chapter in plan["chapters"]:
        scenes = []
        for index in range(chapter["scene_count"]):
            units = chapter["target_units"] // chapter["scene_count"]
            units += int(index < chapter["target_units"] % chapter["scene_count"])
            text = "讲" * units if plan["narration_language"] == "zh" else " ".join(["word"] * units)
            scenes.append({"asset_path": assets[(chapter["scene_start"] + index) % len(assets)],
                           "narrations": [text + "."]})
        answers.append(json.dumps({"scenes": scenes}, ensure_ascii=False))
    return answers


def make_core():
    """所有外部边界均为假实现；现有 API-only 行为仍由真实管线决定。"""
    return SimpleNamespace(
        llm=AsyncMock(), tts=AsyncMock(), media=AsyncMock(), video=Mock(),
        frame_processor=AsyncMock(), config={},
        api_asset_analysis=SimpleNamespace(
            analyze_image=AsyncMock(return_value="可用于讲解的实拍图片"),
            analyze_video=AsyncMock(return_value="可用于讲解的实拍视频"),
        ),
        image_analysis=AsyncMock(), video_analysis=AsyncMock(),
        persistence=SimpleNamespace(save_task_metadata=AsyncMock(), save_storyboard=AsyncMock()),
    )


class AssetLongScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_minutes_produces_75_asset_bound_scenes_in_chapters(self):
        plan = build_asset_long_video_plan(600, "en", 1.5, 2)
        assets = {"F:/素材/表盘.jpg": {"type": "image", "description": "表盘"},
                  "F:/素材/机芯.mp4": {"type": "video", "description": "机芯"}}
        llm = AsyncMock(side_effect=script_answers(plan, list(assets)))
        scenes, chapters = await generate_asset_long_script(llm, "How a watch works", "", assets, plan)
        self.assertEqual(len(scenes), 75)
        self.assertEqual(len(chapters), 10)
        self.assertEqual(llm.await_count, 11)
        self.assertEqual(sum(chapter["actual_units"] for chapter in chapters), plan["target_units"])
        self.assertEqual(asset_usage_summary(scenes), {"F:/素材/表盘.jpg": 38, "F:/素材/机芯.mp4": 37})
        self.assertEqual(plan["minimum_reused_scenes"], 73)
        self.assertTrue(all(scene["asset_path"] in assets for scene in scenes))
        self.assertEqual([scene["scene_number"] for scene in scenes], list(range(1, 76)))
        self.assertIn(scenes[7]["narrations"][0], llm.await_args_list[2].kwargs["prompt"])

    async def test_unknown_asset_path_is_retried_then_rejected_without_fallback(self):
        plan = build_asset_long_video_plan(300)
        assets = {"original.png": {"type": "image", "description": "原素材"}}
        replies = script_answers(plan, ["original.png"])
        bad = json.loads(replies[1])
        bad["scenes"][0]["asset_path"] = "fabricated/original.png"
        llm = AsyncMock(side_effect=[replies[0], json.dumps(bad), json.dumps(bad)])
        with self.assertRaisesRegex(ValueError, "尚未开始生成配音"):
            await generate_asset_long_script(llm, "测试", "", assets, plan)
        self.assertEqual(llm.await_count, 3)

    async def test_short_or_truncated_chapter_never_becomes_a_successful_long_video(self):
        plan = build_asset_long_video_plan(300)
        assets = {"source.png": {"type": "image", "description": "原素材"}}
        replies = script_answers(plan, list(assets))
        short = json.loads(replies[1])
        for scene in short["scenes"]:
            scene["narrations"] = ["短"]
        for bad in (json.dumps(short), replies[1][:-5], '{"scenes": []}'):
            with self.subTest(bad=bad[:30]):
                llm = AsyncMock(side_effect=[replies[0], bad, bad])
                with self.assertRaisesRegex(ValueError, "旁白预算校验"):
                    await generate_asset_long_script(llm, "测试", "", assets, plan)

    async def test_invalid_chapter_can_be_repaired_once(self):
        plan = build_asset_long_video_plan(300)
        assets = {"source.png": {"type": "image", "description": "原素材"}}
        replies = script_answers(plan, list(assets))
        llm = AsyncMock(side_effect=[replies[0], '{"scenes": []}', *replies[1:]])
        scenes, _ = await generate_asset_long_script(llm, "测试", "", assets, plan)
        self.assertEqual(len(scenes), 38)
        self.assertIn("上次校验未通过", llm.await_args_list[2].kwargs["prompt"])

    async def test_invalid_outline_or_empty_assets_stops_before_chapters(self):
        plan = build_asset_long_video_plan(300)
        llm = AsyncMock(return_value='{"chapters": []}')
        with self.assertRaisesRegex(ValueError, "没有成功分析"):
            await generate_asset_long_script(llm, "测试", "", {}, plan)
        llm.assert_not_awaited()
        with self.assertRaisesRegex(ValueError, "大纲不完整"):
            await generate_asset_long_script(llm, "测试", "", {"x.png": {"type": "image", "description": "素材"}}, plan)
        self.assertEqual(llm.await_count, 2)

    def test_budget_and_uniform_windows_are_bounded(self):
        for duration, expected in ((300, 38), (480, 60), (600, 75)):
            plan = build_asset_long_video_plan(duration, "zh", 1.2, 100)
            self.assertEqual(plan["scene_count"], expected)
            self.assertEqual(plan["minimum_reused_scenes"], 0)
        for duration in (True, 120, 301, 900, "300"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                build_asset_long_video_plan(duration)
        starts = [video_window(100, 8, index, 3)["start_seconds"] for index in range(3)]
        self.assertEqual(starts, [0, 46, 92])
        self.assertTrue(video_window(3, 8, 2, 3)["loop_source"])
        self.assertFalse(video_window(8, 8, 0, 1)["loop_source"])
        for source in (0, float("nan"), float("inf")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                video_window(source, 8, 0, 1)


class AssetLongPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.image = str(self.path / "实拍素材.png")
        self.video = str(self.path / "实拍素材.mp4")
        Path(self.image).write_bytes(b"offline-image")
        Path(self.video).write_bytes(b"offline-video")
        self.core = make_core()
        self.pipeline = AssetBasedPipeline(self.core)
        self.pipeline._progress_callback = None
        self.enterContext(patch("pixelle_video.pipelines.asset_based.create_task_output_dir",
                                return_value=(str(self.path), "offline-long-assets")))
        self.enterContext(patch("pixelle_video.pipelines.asset_based.get_task_final_video_path",
                                return_value=str(self.path / "final.mp4")))

    def context(self, **kwargs):
        params = {"assets": [self.image, self.video], "source": "api", "duration": 300, **kwargs}
        ctx = PipelineContext("机械表讲解", params, task_dir=self.path, title="")
        ctx.request = params
        return ctx

    async def test_analysis_passes_provider_and_frame_budget_and_excludes_failed_asset(self):
        ctx = self.context(analysis_vlm_provider="openai", analysis_vlm_model="gpt-4.1",
                           analysis_video_max_frames=32)
        self.core.api_asset_analysis.analyze_video.side_effect = RuntimeError("offline")
        await self.pipeline.setup_environment(ctx)
        self.core.api_asset_analysis.analyze_image.assert_awaited_once_with(
            self.image, model="gpt-4.1", provider="openai")
        self.core.api_asset_analysis.analyze_video.assert_awaited_once_with(
            self.video, model="gpt-4.1", provider="openai", max_video_frames=32)
        self.assertEqual(list(ctx.asset_index), [self.image])
        self.assertEqual(ctx.analysis_warnings[0]["asset_path"], self.video)
        self.core.image_analysis.assert_not_awaited()
        self.core.video_analysis.assert_not_awaited()

    async def test_all_analysis_failures_stop_before_llm_and_speech(self):
        self.core.api_asset_analysis.analyze_image.side_effect = RuntimeError("offline")
        self.core.api_asset_analysis.analyze_video.side_effect = RuntimeError("offline")
        with self.assertRaisesRegex(ValueError, "没有成功分析"):
            await self.pipeline([self.image, self.video], intent="讲解", duration=300, source="api")
        self.core.llm.assert_not_awaited()
        self.core.tts.assert_not_awaited()

    async def test_late_chapter_failure_stops_before_any_speech_or_animation(self):
        plan = build_asset_long_video_plan(300)
        replies = script_answers(plan, [self.image])
        self.core.llm.side_effect = replies[:3] + ['{"scenes": []}', '{"scenes": []}']
        with self.assertRaisesRegex(ValueError, "第 3 章"):
            await self.pipeline([self.image], intent="讲解", duration=300, source="api")
        self.core.tts.assert_not_awaited()
        self.core.media.assert_not_awaited()
        self.assertFalse((self.path / "asset-long-video-script.json").exists())

    async def test_invalid_plan_and_stale_api_workflow_stop_before_analysis(self):
        for kwargs in ({"duration": 301}, {"duration": "300"}, {"duration": True},
                       {"duration": 300, "tts_speed": float("nan")},
                       {"duration": 300, "api_video_workflow": "runninghub/old.json"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.pipeline([self.image], source="api", **kwargs)
        self.core.api_asset_analysis.analyze_image.assert_not_awaited()

    async def test_video_production_uses_distinct_local_windows_and_records_mapping(self):
        """沿真实 produce_assets 验证切片确实传给合成，而非只计算一份无效计划。"""
        from pixelle_video.models.storyboard import Storyboard, StoryboardConfig, StoryboardFrame

        ctx = self.context(assets=[self.video])
        ctx.task_id = "offline-video-windows"
        ctx.long_video_plan = build_asset_long_video_plan(300)
        ctx.asset_usage = {self.video: 3}
        ctx.script = [{"asset_path": self.video, "narrations": ["这是离线测试旁白。"]} for _ in range(3)]
        ctx.matched_scenes = ctx.script
        ctx.config = StoryboardConfig(media_width=160, media_height=90, video_fps=10, tts_speed=1.2)
        ctx.storyboard = Storyboard("", ctx.config)
        for index, scene in enumerate(ctx.script):
            frame = StoryboardFrame(index, scene["narrations"][0], None, media_type="video", video_path=self.video)
            frame._scene_data = scene
            ctx.storyboard.frames.append(frame)

        async def compose(**kwargs):
            frame = kwargs["frame"]
            frame.video_segment_path = f"offline-{frame.index}.mp4"
            return frame

        self.core.frame_processor.side_effect = compose
        with patch("subprocess.run", return_value=SimpleNamespace(stdout="8.0")) as process, \
                patch.object(self.pipeline, "_probe_video_duration", return_value=100):
            await self.pipeline.produce_assets(ctx)
        commands = [call.args[0] for call in process.call_args_list if call.args[0][0] == "ffmpeg"]
        self.assertEqual(len(commands), 3)
        self.assertTrue(all("-an" in command for command in commands))
        self.assertEqual([float(command[command.index("-ss") + 1]) for command in commands], [0, 46, 92])
        self.assertTrue(all(frame.video_path != self.video for frame in ctx.storyboard.frames))
        self.assertTrue(all(Path(frame.video_path).is_relative_to(self.path) for frame in ctx.storyboard.frames))
        self.assertEqual(self.core.frame_processor.await_count, 3)
        saved = json.loads((self.path / "asset-long-video-script.json").read_text(encoding="utf-8"))
        self.assertEqual([scene["video_window"]["start_seconds"] for scene in saved["scenes"]], [0, 46, 92])
        self.assertEqual(Path(self.video).read_bytes(), b"offline-video")

    async def test_full_ten_minute_mock_lifecycle_preserves_speed_and_measured_result(self):
        plan = build_asset_long_video_plan(600, "en", 1.5, 1)
        self.core.llm.side_effect = script_answers(plan, [self.image])

        async def compose(**kwargs):
            frame = kwargs["frame"]
            frame.video_segment_path = f"offline-{frame.index}.mp4"
            return frame

        self.core.frame_processor.side_effect = compose
        with patch("subprocess.run", return_value=SimpleNamespace(stdout="8.0")), \
                patch.object(self.pipeline, "_probe_video_duration", return_value=602.25):
            ctx = await self.pipeline([self.image], intent="Explain watches", duration=600, source="api",
                                      narration_language="en", tts_speed=1.5)
        self.assertEqual(len(ctx.storyboard.frames), 75)
        self.assertEqual(self.core.tts.await_count, 75)
        self.assertTrue(all(call.kwargs["speed"] == 1.5 for call in self.core.tts.await_args_list))
        self.assertTrue(all(call.kwargs["inference_mode"] == "local" for call in self.core.tts.await_args_list))
        self.assertEqual(ctx.storyboard.total_duration, 602.25)
        self.assertEqual(ctx.duration_report["measurement_status"], "measured")
        self.assertTrue(ctx.duration_report["within_tolerance"])
        self.assertEqual(ctx.asset_usage[self.image], 75)
        self.core.media.assert_not_awaited()
        saved = json.loads((self.path / "asset-long-video-script.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["scenes"]), 75)
        self.assertEqual(saved["duration_report"]["actual_duration_seconds"], 602.25)
        metadata = self.core.persistence.save_task_metadata.await_args.args[1]
        self.assertEqual(metadata["result"]["duration_report"], ctx.duration_report)

    async def test_probe_failure_keeps_estimate_but_marks_measurement_unavailable(self):
        ctx = self.context()
        ctx.task_id = "offline"
        ctx.long_video_plan = build_asset_long_video_plan(300)
        ctx.script, ctx.asset_usage = [], {}
        ctx.storyboard = SimpleNamespace(frames=[SimpleNamespace(video_segment_path="frame.mp4")],
                                         total_duration=301)
        with patch.object(self.pipeline, "_probe_video_duration", return_value=0):
            await self.pipeline.post_production(ctx)
        self.assertEqual(ctx.storyboard.total_duration, 301)
        self.assertIsNone(ctx.duration_report["actual_duration_seconds"])
        self.assertEqual(ctx.duration_report["measurement_status"], "unavailable")

    async def test_legacy_short_script_keeps_single_structured_request(self):
        from pixelle_video.pipelines.asset_based import SceneScript, VideoScript

        ctx = self.context(duration=60)
        self.pipeline.asset_index = {self.image: {"description": "实拍图片", "type": "image"}}
        self.core.llm.return_value = VideoScript(scenes=[SceneScript(
            scene_number=1, asset_path=self.image, narrations=["短片旁白"], duration=5)])
        await self.pipeline.generate_content(ctx)
        self.assertEqual(self.core.llm.await_count, 1)
        self.assertEqual(self.core.llm.await_args.kwargs["response_type"], VideoScript)
        self.assertFalse(hasattr(ctx, "long_video_plan"))


@unittest.skipUnless(os.environ.get("FRAMEWEAVE_MEDIA_SMOKE") == "1", "低清 FFmpeg 冒烟由本地显式开启")
class AssetVideoWindowSmokeTests(unittest.TestCase):
    def test_real_windows_select_different_times_loop_short_sources_and_remove_source_audio(self):
        """只渲染色块和正弦波，验证原件未动、取段不同、无源音轨及实际输出时长。"""
        self.assertIsNotNone(shutil.which("ffmpeg"))
        self.assertIsNotNone(shutil.which("ffprobe"))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=red:s=160x90:r=10:d=1", "-f", "lavfi", "-i",
                "color=c=blue:s=160x90:r=10:d=1", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=2", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", "-y", str(source),
            ], check=True, capture_output=True, timeout=30)
            original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            pipeline = AssetBasedPipeline(make_core())
            clips = []
            for occurrence in (0, 1):
                clip, window = pipeline._prepare_long_video_window(
                    str(source), 0.5, occurrence, 2, folder, occurrence, 10)
                clips.append(clip)
                self.assertAlmostEqual(window["start_seconds"], occurrence * 1.5, delta=0.05)
            looped, window = pipeline._prepare_long_video_window(str(source), 3.5, 0, 1, folder, 2, 10)
            self.assertTrue(window["loop_source"])
            for clip, expected in [(clips[0], 0.5), (clips[1], 0.5), (looped, 3.5)]:
                probe = json.loads(subprocess.run([
                    "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", clip,
                ], check=True, capture_output=True, text=True, timeout=30).stdout)
                self.assertEqual([s["codec_type"] for s in probe["streams"]], ["video"])
                self.assertAlmostEqual(float(probe["format"]["duration"]), expected, delta=0.11)
            pixels = []
            for clip in clips:
                frame = subprocess.run([
                    "ffmpeg", "-v", "error", "-i", clip, "-frames:v", "1", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "pipe:1",
                ], check=True, capture_output=True, timeout=30).stdout
                pixels.append(tuple(frame[:3]))
            self.assertGreater(pixels[0][0], pixels[0][2] + 100)
            self.assertGreater(pixels[1][2], pixels[1][0] + 100)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_hash)
