"""视觉素材预处理：限定图像体积，长视频仅均匀采样关键帧。"""

from __future__ import annotations

import base64
import io
import json
import math
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageOps

MAX_IMAGE_EDGE = 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 64_000_000
MAX_VIDEO_FRAMES = 32


def validate_frame_limit(value: int) -> int:
    """拒绝越界和隐式类型转换，保证一次分析最多发送 32 帧。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_VIDEO_FRAMES:
        raise ValueError("视频分析采样帧数必须是 1–32 的整数。")
    return value


def image_data_url(path: str) -> str:
    """本地图片先校正方向并缩放；避免直接把超大原图放进请求。"""
    try:
        if path.startswith("data:image/"):
            if len(path) > MAX_IMAGE_BYTES * 4 // 3 + 256:
                raise ValueError
            _, encoded = path.split(",", 1)
            source = io.BytesIO(base64.b64decode(encoded, validate=True))
        else:
            file = Path(path)
            if file.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError
            source = file
        with Image.open(source) as original:
            if original.width * original.height > MAX_IMAGE_PIXELS:
                raise ValueError
            # 第一帧用于 GIF 等动态图片；视频请走显式视频分析入口。
            original.seek(0)
            image = ImageOps.exif_transpose(original)
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            image = image.convert("RGB")
            encoded_image = io.BytesIO()
            image.save(encoded_image, format="JPEG", quality=85, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(encoded_image.getvalue()).decode("ascii")
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError("无法读取素材图片，或图片超过 32 MB / 6400 万像素限制。") from None


def _run_media_command(command: list[str], timeout: float):
    """媒体子进程不弹窗，错误不携带本地路径或完整 FFmpeg 输出。"""
    try:
        return subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise RuntimeError("视频视觉分析需要 FFmpeg 和 FFprobe，请先安装并加入 PATH。") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("视频关键帧提取超时，请缩短或转码素材后重试。") from None
    except subprocess.SubprocessError:
        raise RuntimeError("无法读取视频关键帧，请检查素材是否损坏或格式是否受支持。") from None


def video_duration(path: str) -> float:
    result = _run_media_command([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "format=duration:stream=codec_type,duration", "-of", "json", str(Path(path).resolve()),
    ], timeout=30)
    try:
        info = json.loads(result.stdout)
        streams = info.get("streams") or []
        if not streams or streams[0].get("codec_type") != "video":
            raise ValueError
        duration = float(info.get("format", {}).get("duration") or streams[0].get("duration"))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuntimeError("无法确认素材视频时长，请转码为标准 MP4 后重试。") from None


def frame_timestamps(duration: float, max_frames: int) -> list[float]:
    """等分全片后取每段中点；避开容器结尾晚于最后一帧的空时间戳。"""
    validate_frame_limit(max_frames)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("视频时长必须是有限正数。")
    count = min(max_frames, max(1, math.ceil(duration / 2)))
    return [duration * (index + 0.5) / count for index in range(count)]


@contextmanager
def sampled_video_frames(path: str, max_frames: int = 16):
    """返回 (秒数, 图片路径)；API 失败、抽帧失败时仍删除全部临时帧。"""
    validate_frame_limit(max_frames)
    duration = video_duration(path)
    # 对 5–10 分钟素材随机定位抽帧，无需整段视频解码或上传。
    deadline = time.monotonic() + 180
    with tempfile.TemporaryDirectory(prefix="frameweave-vlm-") as directory:
        frames = []
        for index, timestamp in enumerate(frame_timestamps(duration, max_frames)):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("视频关键帧提取超时，请缩短或转码素材后重试。")
            output = Path(directory) / f"frame-{index:02d}.jpg"
            _run_media_command([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp:.6f}", "-i", str(Path(path).resolve()),
                "-map", "0:v:0", "-frames:v", "1", "-an", "-threads", "1",
                "-vf", "scale='min(1024,iw)':'min(1024,ih)':force_original_aspect_ratio=decrease",
                "-pix_fmt", "yuvj420p", "-q:v", "3", str(output),
            ], timeout=min(30, remaining))
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError("视频采样未得到有效画面，请转码素材后重试。")
            frames.append((timestamp, str(output)))
        yield frames
