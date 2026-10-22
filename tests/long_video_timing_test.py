"""长片时长回归：短视频素材不缩短旁白，时间轴使用合成文件的真实长度。"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import ffmpeg
from PIL import Image

from pixelle_video.models.storyboard import StoryboardConfig, StoryboardFrame
from pixelle_video.services.frame_processor import FrameProcessor
from pixelle_video.services.video import VideoService


class LongVideoTimingTests(unittest.TestCase):
    def setUp(self):
        self.frame = StoryboardFrame(
            index=0,
            narration="这一段旁白比模型返回的视频素材更长。",
            image_prompt="offline test",
            audio_path="narration.wav",
            duration=12.75,
        )
        self.config = StoryboardConfig(
            media_width=160,
            media_height=90,
            task_id="offline-timing",
            media_workflow="api/xai/grok-imagine-video",
            frame_template="160x90/video_default.html",
            video_fps=24,
        )
        self.core = SimpleNamespace(media=AsyncMock())
        self.processor = FrameProcessor(self.core)

    def test_short_api_clip_preserves_narration_duration(self):
        """五秒素材不能把十二秒旁白的分镜时长改成五秒。"""
        self.core.media.return_value = SimpleNamespace(
            media_type="video", is_image=False, is_video=True,
            url="source.mp4", duration=5.0,
        )
        self.processor._download_media = AsyncMock(return_value="source.mp4")
        asyncio.run(self.processor._step_generate_media(self.frame, self.config))
        self.assertEqual(self.frame.duration, 12.75)
        self.assertEqual(self.frame.video_path, "source.mp4")
        self.assertEqual(self.core.media.await_args.kwargs["duration"], 12.75)

    def test_segment_duration_is_measured_after_composition(self):
        """图片和视频路径都使用最终片段的实测长度，而非生成模型元数据。"""
        for media_type in ("video", "image", None):
            with self.subTest(media_type=media_type):
                self.frame.media_type = media_type
                self.frame.video_path = "source.mp4"
                self.frame.composed_image_path = "overlay.png"
                self.processor._get_video_duration = AsyncMock(return_value=12.792)
                service = Mock()
                service.merge_audio_video.return_value = "segment.mp4"
                service.create_video_from_image.return_value = "segment.mp4"
                with patch("pixelle_video.services.video.VideoService", return_value=service):
                    asyncio.run(self.processor._step_create_video_segment(self.frame, self.config))
                self.assertEqual(self.frame.duration, 12.792)
                self.processor._get_video_duration.assert_awaited_once_with("segment.mp4")
                if media_type == "video":
                    self.assertEqual(service.merge_audio_video.call_args.kwargs["fps"], 24)

    def test_unreadable_segment_is_not_reported_as_one_second(self):
        """探测失败时停止任务，不用假定一秒钟写入完成结果。"""
        for value in ("nan", "0", "-1", None):
            with self.subTest(value=value), patch(
                "ffmpeg.probe", return_value={"format": {"duration": value}}
            ):
                with self.assertRaisesRegex(RuntimeError, "实际时长"):
                    asyncio.run(self.processor._get_video_duration("broken.mp4"))

    def test_merge_bounds_output_by_full_narration_and_normalizes_streams(self):
        """明确输出时长和统一编码，不依赖关键帧裁切或云端帧率。"""
        for source_duration in (5.0, 22.0):
            with self.subTest(source_duration=source_duration):
                service = VideoService()
                service._ensure_ffmpeg = Mock()
                service._get_video_duration = Mock(return_value=source_duration)
                service._get_audio_duration = Mock(return_value=12.75)
                service._pad_video_to_duration = Mock(return_value="padded.mp4")
                service._trim_video_to_duration = Mock(return_value="trimmed.mp4")
                service.has_audio_stream = Mock(return_value=False)
                # 只编排 FFmpeg 图，不启动进程或读取真实用户素材。
                with patch("ffmpeg.output", wraps=ffmpeg.output) as output, patch(
                    "ffmpeg.nodes.OutputStream.run", return_value=(b"", b"")
                ):
                    service.merge_audio_video("source.mp4", "narration.wav", "output.mp4", fps=24)
                options = output.call_args.kwargs
                self.assertEqual(options["t"], 12.75)
                self.assertEqual(options["r"], 24)
                self.assertEqual(options["ar"], 48000)
                self.assertEqual(options["ac"], 2)
                self.assertEqual(options["pix_fmt"], "yuv420p")


@unittest.skipUnless(
    os.environ.get("FRAMEWEAVE_MEDIA_SMOKE") == "1" and shutil.which("ffmpeg"),
    "仅在显式开启 FRAMEWEAVE_MEDIA_SMOKE=1 时执行本地占位素材验收",
)
class LongVideoLocalCompositionTests(unittest.TestCase):
    def test_five_and_ten_minute_concatenation(self):
        """用测试色块和静音验证长片封装，绝不调用云端生成或读取用户素材。"""
        with tempfile.TemporaryDirectory(prefix="frameweave-timing-") as directory:
            root = Path(directory)
            image = str(root / "placeholder.png")
            audio = str(root / "silence.wav")
            Image.new("RGB", (160, 90), "#c4c4c4").save(image)
            # 五秒占位音轨重复拼成 60/120 段，检查多段封装时是否累积音画漂移。
            # 测试目录退出后自动清理，素材不进入作品记录。
            with wave.open(audio, "wb") as stream:
                stream.setnchannels(2)
                stream.setsampwidth(2)
                stream.setframerate(48000)
                stream.writeframes(b"\0" * 48000 * 4 * 5)
            source = str(root / "short-source.mp4")
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=7:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", source,
                ],
                check=True, capture_output=True,
            )
            service = VideoService()
            # 两类分镜原帧率不同，统一项目 FPS 后交替拼接。
            image_segment = service.create_video_from_image(
                image, audio, str(root / "image-segment.mp4"), fps=2
            )
            # 把合成器中间文件也隔离到测试目录，避免污染应用 temp。
            with patch.object(
                service, "_get_unique_temp_path",
                side_effect=lambda prefix, name: str(root / f"{prefix}_{name}"),
            ):
                video_segment = service.merge_audio_video(
                    source, audio, str(root / "video-segment.mp4"), fps=2
                )
            for minutes in (5, 10):
                with self.subTest(minutes=minutes):
                    segments = [image_segment, video_segment] * (minutes * 6)
                    output = service.concat_videos(segments, str(root / f"{minutes}-minutes.mp4"))
                    probe = ffmpeg.probe(output)
                    measured = float(probe["format"]["duration"])
                    self.assertAlmostEqual(measured, minutes * 60, delta=0.25)
                    streams = {item["codec_type"]: item for item in probe["streams"]}
                    self.assertGreaterEqual(float(streams["audio"]["duration"]), minutes * 60 - 0.1)
                    self.assertGreaterEqual(float(streams["video"]["duration"]), minutes * 60 - 0.1)
                    self.assertEqual(streams["audio"]["sample_rate"], "48000")
                    print(f"本地占位素材验收：目标 {minutes} 分钟，FFprobe 实测 {measured:.3f} 秒")


if __name__ == "__main__":
    unittest.main()
