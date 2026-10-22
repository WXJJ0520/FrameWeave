"""长片预算、完整稿拆分与分章生成的离线测试，不访问模型或配音服务。"""

import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pixelle_video.models.storyboard import Storyboard, StoryboardConfig, StoryboardFrame
from pixelle_video.pipelines.linear import PipelineContext
from pixelle_video.pipelines.standard import StandardPipeline
from pixelle_video.utils.long_video import (
    build_duration_report,
    build_long_video_plan,
    count_narration_units,
    estimate_narration_seconds,
    generate_long_narrations,
    split_long_script,
)


def chapter_answers(plan):
    """构造不同章节的预算内脚本，便于断言不把十分钟挤入一次请求。"""
    answers = [json.dumps({"chapters": [
        {"title": f"第 {chapter['index']} 章", "focus": f"说明要点 {chapter['index']}"}
        for chapter in plan["chapters"]
    ]}, ensure_ascii=False)]
    for chapter in plan["chapters"]:
        narrations = []
        for index in range(chapter["scene_count"]):
            size = chapter["target_units"] // chapter["scene_count"]
            size += int(index < chapter["target_units"] % chapter["scene_count"])
            narration = "讲" * size if plan["narration_language"] == "zh" else " ".join(["word"] * size)
            narrations.append(narration + ".")
        answers.append(json.dumps({"narrations": narrations}, ensure_ascii=False))
    return answers


class LongVideoPlanningTests(unittest.TestCase):
    def test_presets_allocate_exact_budget_for_both_languages_and_speeds(self):
        for duration in (300, 480, 600):
            for language in ("zh", "en"):
                for speed in (0.5, 1.0, 1.2, 2.0):
                    with self.subTest(duration=duration, language=language, speed=speed):
                        plan = build_long_video_plan(duration, language, speed)
                        self.assertEqual(sum(c["scene_count"] for c in plan["chapters"]), plan["scene_count"])
                        self.assertEqual(sum(c["target_units"] for c in plan["chapters"]), plan["target_units"])
                        self.assertAlmostEqual(plan["estimated_duration_seconds"], duration, delta=0.5)
                        self.assertLessEqual(plan["scene_count"], 75)
                        json.dumps(plan, ensure_ascii=False)

    def test_invalid_inputs_fail_locally(self):
        for duration in (True, 0, 299, 601, 300.5, "300"):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                build_long_video_plan(duration)
        for speed in (0, 5, None, True, float("nan"), float("inf")):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                build_long_video_plan(300, tts_speed=speed)
        with self.assertRaises(ValueError):
            build_long_video_plan(300, "unknown")

    def test_split_fixed_script_preserves_every_character_except_whitespace(self):
        text = "机械表的动力来自发条。" * 20 + "\n\n下一章保留标点！English longword 123. " * 15
        for split_mode in ("paragraph", "line", "sentence"):
            with self.subTest(split_mode=split_mode):
                segments = split_long_script(text, "zh", 1, split_mode)
                self.assertEqual(re.sub(r"\s", "", "".join(segments)), re.sub(r"\s", "", text))
                self.assertTrue(all(count_narration_units(segment) <= 36 for segment in segments))
        short = split_long_script("这是很短的完整稿件。", "zh", 1)
        self.assertEqual(short, ["这是很短的完整稿件。"])
        self.assertLess(estimate_narration_seconds(short[0]), 10)

    def test_english_boundaries_and_scene_budget_guard(self):
        words = [f"longword{index}" for index in range(80)]
        segments = split_long_script(" ".join(words), "en", 1)
        self.assertEqual(" ".join(segments).split(), words)
        self.assertTrue(all(len(segment.split()) <= 23 for segment in segments))
        with self.assertRaisesRegex(ValueError, "240"):
            split_long_script("一\n" * 241, split_mode="line")
        with self.assertRaises(ValueError):
            split_long_script("。。。")

    def test_separator_only_segments_are_merged_without_losing_original_characters(self):
        texts = (
            "——\n\n这是正常旁白。",
            "——\n\n😊\n\n第一段正常旁白。\n\n……\n\n第二段旁白。\n\n***",
            "。。。\n\n！\n\n这是下一句。\n\n——",
        )
        for text in texts:
            for split_mode in ("paragraph", "line", "sentence"):
                with self.subTest(text=text, split_mode=split_mode):
                    segments = split_long_script(text, split_mode=split_mode)
                    self.assertTrue(all(count_narration_units(segment) > 0 for segment in segments))
                    self.assertEqual(re.sub(r"\s", "", "".join(segments)), re.sub(r"\s", "", text))
        for text in ("——", "……\n\n***\n\n😊"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "可配音"):
                split_long_script(text)

    def test_duration_report_does_not_claim_estimate_is_measured(self):
        self.assertTrue(build_duration_report(300, 310)["within_tolerance"])
        self.assertFalse(build_duration_report(300, 60)["within_tolerance"])
        for actual in (0, float("nan"), float("inf")):
            report = build_duration_report(300, actual)
            self.assertIsNone(report["within_tolerance"])
            self.assertIsNone(report["actual_duration_seconds"])
            self.assertEqual(report["measurement_status"], "unavailable")


class LongVideoGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ten_minute_script_is_generated_by_chapter_with_continuity(self):
        plan = build_long_video_plan(600, "zh", 1.2)
        llm = AsyncMock(side_effect=chapter_answers(plan))
        progress = Mock()
        narrations, chapters = await generate_long_narrations(llm, "机械表", plan, progress)
        self.assertEqual(len(narrations), plan["scene_count"])
        self.assertEqual(llm.await_count, plan["chapter_count"] + 1)
        self.assertEqual(len(chapters), plan["chapter_count"])
        self.assertEqual(sum(c["actual_units"] for c in chapters), plan["target_units"])
        self.assertIn(narrations[plan["chapters"][0]["scene_count"] - 1], llm.await_args_list[2].kwargs["prompt"])
        self.assertTrue(all(call.kwargs["max_tokens"] >= 4096 for call in llm.await_args_list))
        progress.assert_called_with(10, 10)

    async def test_short_chapter_is_repaired_once_without_restarting_outline(self):
        plan = build_long_video_plan(300)
        answers = chapter_answers(plan)
        bad = json.dumps({"narrations": ["短"] * plan["chapters"][0]["scene_count"]})
        llm = AsyncMock(side_effect=[answers[0], bad, *answers[1:]])
        narrations, _ = await generate_long_narrations(llm, "机械表", plan)
        self.assertEqual(len(narrations), plan["scene_count"])
        self.assertEqual(llm.await_count, plan["chapter_count"] + 2)
        self.assertIn("上次校验未通过", llm.await_args_list[2].kwargs["prompt"])

    async def test_repeated_incomplete_script_stops_before_any_assets(self):
        plan = build_long_video_plan(300)
        bad = json.dumps({"narrations": ["短"] * plan["chapters"][0]["scene_count"]})
        llm = AsyncMock(side_effect=[chapter_answers(plan)[0], bad, bad])
        with self.assertRaisesRegex(ValueError, "尚未开始生成配音和画面"):
            await generate_long_narrations(llm, "机械表", plan)
        self.assertEqual(llm.await_count, 3)

    async def test_bad_outline_cannot_fall_back_to_short_video(self):
        llm = AsyncMock(return_value='{"chapters": []}')
        with self.assertRaisesRegex(ValueError, "章节规划"):
            await generate_long_narrations(llm, "机械表", build_long_video_plan(300))
        self.assertEqual(llm.await_count, 2)


class LongVideoPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.core = SimpleNamespace(
            llm=AsyncMock(), tts=AsyncMock(), media=AsyncMock(), video=Mock(),
            config={}, persistence=SimpleNamespace(save_task_metadata=AsyncMock(), save_storyboard=AsyncMock()),
        )
        self.pipeline = StandardPipeline(self.core)

    async def test_fixed_mode_never_expands_text_and_saves_script_before_assets(self):
        source = "逐句保留机械表讲解。" * 30
        ctx = PipelineContext(source, {"target_duration_seconds": 600, "mode": "fixed", "n_scenes": 5,
                                       "tts_speed": 1, "narration_language": "zh"}, task_dir=self.temp.name)
        await self.pipeline.generate_content(ctx)
        self.assertEqual("".join(ctx.narrations), source)
        self.assertEqual(ctx.params["n_scenes"], len(ctx.narrations))
        self.assertEqual(ctx.params["long_video_plan"]["scene_count"], len(ctx.narrations))
        self.assertEqual(ctx.params["long_video_plan"]["planned_scene_count"], 75)
        self.assertEqual(ctx.params["long_video_plan"]["expected_media_calls"], 0)
        self.assertLess(ctx.params["long_video_plan"]["script_estimated_duration_seconds"], 600)
        self.core.llm.assert_not_awaited()
        self.core.tts.assert_not_awaited()
        self.core.media.assert_not_awaited()
        saved = json.loads((Path(self.temp.name) / "long-video-script.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["narrations"], ctx.narrations)

    async def test_default_and_explicit_speed_match_budget_and_actual_tts_arguments(self):
        """覆盖参数缺省、None 与显式语速，沿真实分镜配置检查最终 TTS 入参。"""
        from pixelle_video.services.frame_processor import FrameProcessor

        for speed_params, expected in (({}, 1.0), ({"tts_speed": None}, 1.0), ({"tts_speed": 1.2}, 1.2)):
            with self.subTest(speed_params=speed_params):
                params = {"target_duration_seconds": 300, "mode": "fixed", **speed_params}
                ctx = PipelineContext("完整保留这一段旁白。", params, task_id="offline-speed")
                await self.pipeline.generate_content(ctx)
                ctx.title = "测试"
                ctx.image_prompts = [None] * len(ctx.narrations)
                await self.pipeline.initialize_storyboard(ctx)
                self.assertEqual(ctx.params["long_video_plan"]["tts_speed"], expected)
                self.assertEqual(ctx.config.tts_speed, expected)
                processor = FrameProcessor(self.core)
                self.core.tts.return_value = "offline-audio.mp3"
                with patch("pixelle_video.utils.os_util.get_task_frame_path", return_value="offline-audio.mp3"), \
                        patch.object(processor, "_get_audio_duration", new=AsyncMock(return_value=3.0)):
                    await processor._step_generate_audio(ctx.storyboard.frames[0], ctx.config)
                self.assertEqual(self.core.tts.await_args.kwargs["speed"], expected)

    async def test_generated_mode_ignores_old_five_scene_parameter(self):
        plan = build_long_video_plan(300, "en", 1)
        self.core.llm.side_effect = chapter_answers(plan)
        ctx = PipelineContext("Watches", {"target_duration_seconds": 300, "mode": "generate", "n_scenes": 5,
                                           "tts_speed": 1, "narration_language": "en"})
        await self.pipeline.generate_content(ctx)
        self.assertEqual(len(ctx.narrations), plan["scene_count"])
        self.core.media.assert_not_awaited()

    async def test_actual_media_budget_matches_fixed_script_and_static_templates(self):
        """预算只记录真实拆分镜头；静态模板即使残留模型值也不会生成画面。"""
        cases = (
            ("static_simple.html", None, 0),
            ("image_default.html", "api/openai/gpt-image-2", 1),
            ("video_simple.html", "api/xai/grok-imagine-video", 1),
            ("static_simple.html", "api/openai/gpt-image-2", 0),
        )
        for template, workflow, expected in cases:
            with self.subTest(template=template, workflow=workflow):
                ctx = PipelineContext("这是正常旁白。", {
                    "target_duration_seconds": 600, "mode": "fixed", "frame_template": template,
                    "media_workflow": workflow,
                })
                await self.pipeline.generate_content(ctx)
                plan = ctx.params["long_video_plan"]
                self.assertEqual(plan["scene_count"], 1)
                self.assertEqual(plan["actual_scene_count"], 1)
                self.assertEqual(plan["expected_media_calls"], expected)
        generated_plan = build_long_video_plan(300)
        self.core.llm.side_effect = chapter_answers(generated_plan)
        ctx = PipelineContext("机械表", {
            "target_duration_seconds": 300, "frame_template": "static_simple.html",
        })
        await self.pipeline.generate_content(ctx)
        self.assertEqual(ctx.params["long_video_plan"]["scene_count"], 38)
        self.assertEqual(ctx.params["long_video_plan"]["expected_media_calls"], 0)

    async def test_invalid_long_script_aborts_full_pipeline_before_billable_media(self):
        """沿真实生命周期执行，确保脚本校验失败不会继续触发配音或镜头生产。"""
        self.core.llm.return_value = '{"chapters": []}'
        self.core.frame_processor = AsyncMock()
        with patch.object(self.pipeline, "setup_environment", new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, "章节规划"):
                await self.pipeline("机械表", target_duration_seconds=300, tts_speed=1)
        self.core.tts.assert_not_awaited()
        self.core.media.assert_not_awaited()
        self.core.frame_processor.assert_not_awaited()

    async def test_short_mode_retains_old_single_request_path(self):
        self.core.llm.return_value = '{"narrations": ["一", "二"]}'
        ctx = PipelineContext("机械表", {"n_scenes": 2})
        await self.pipeline.generate_content(ctx)
        self.assertEqual(ctx.narrations, ["一", "二"])
        self.core.llm.assert_awaited_once()
        self.assertEqual(self.core.llm.await_args.kwargs["max_tokens"], 2000)
        self.assertNotIn("long_video_plan", ctx.params)

    async def test_final_file_measurement_replaces_raw_clip_sum_and_is_persisted(self):
        target = Path(self.temp.name) / "long.mp4"
        target.write_bytes(b"offline-video")
        config = StoryboardConfig(media_width=512, media_height=288, task_id="offline-long")
        board = Storyboard("机械表", config, frames=[StoryboardFrame(0, "讲解", "watch", video_segment_path="part.mp4")],
                           total_duration=5)
        ctx = PipelineContext("机械表", {"target_duration_seconds": 300}, storyboard=board,
                              final_video_path=str(target))
        service = Mock()
        service.concat_videos.return_value = str(target)
        service._get_video_duration.return_value = 312.4
        with patch("pixelle_video.pipelines.standard.VideoService", return_value=service):
            await self.pipeline.post_production(ctx)
        result = await self.pipeline.finalize(ctx)
        self.assertEqual(result.duration, 312.4)
        self.assertEqual(result.duration_report["actual_duration_seconds"], 312.4)
        self.assertTrue(result.duration_report["within_tolerance"])
        metadata = self.core.persistence.save_task_metadata.await_args.args[1]
        self.assertEqual(metadata["result"]["duration_report"], result.duration_report)
        self.core.media.assert_not_awaited()

    async def test_failed_final_probe_never_labels_segment_sum_as_verified_duration(self):
        target = Path(self.temp.name) / "unmeasured.mp4"
        target.write_bytes(b"offline-video")
        config = StoryboardConfig(media_width=512, media_height=288, task_id="offline-unmeasured")
        board = Storyboard("机械表", config, total_duration=300)
        ctx = PipelineContext("机械表", {"target_duration_seconds": 300}, storyboard=board,
                              final_video_path=str(target))
        service = Mock()
        service.concat_videos.return_value = str(target)
        service._get_video_duration.return_value = 0
        with patch("pixelle_video.pipelines.standard.VideoService", return_value=service):
            await self.pipeline.post_production(ctx)
        result = await self.pipeline.finalize(ctx)
        self.assertEqual(result.duration, 300)
        self.assertIsNone(result.duration_report["actual_duration_seconds"])
        self.assertIsNone(result.duration_report["within_tolerance"])
        self.assertEqual(result.duration_report["measurement_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
