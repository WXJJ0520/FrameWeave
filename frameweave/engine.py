"""镜织媒体引擎：离线配方、受控素材检测、真实合成与按需复用上游模型。"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

Progress = Callable[[float, str], Awaitable[None]]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _tool(name: str) -> str:
    """只查找安装好的 FFmpeg 工具，不下载或执行用户提供的命令。"""
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"未找到 {name}，请先安装 FFmpeg 并加入 PATH 后重启服务。")
    return executable


def _probe(path: Path) -> dict:
    """禁用网络协议，避免上传的容器文件把检测变成远程资源请求。"""
    command = [
        _tool("ffprobe"),
        "-v",
        "error",
        "-protocol_whitelist",
        "file,pipe",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=25, check=True)
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as exc:
        raise ValueError("素材无法解码，请上传有效的 PNG/JPEG/WebP、MP4/WebM 或音频文件。") from exc


def inspect_media(path: str | Path) -> dict:
    """按文件真实内容校验素材；不依赖客户端 MIME，也不接受播放列表或 SVG。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        try:
            with Image.open(path) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or image.width * image.height > 40_000_000
                ):
                    raise ValueError("图片尺寸或格式不受支持。")
                width, height = image.size
                image.verify()
            return {"kind": "image", "width": width, "height": height}
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("图片内容损坏或尺寸过大。") from exc
    if suffix not in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
        raise ValueError("不支持此素材格式，请使用 PNG/JPEG/WebP、MP4/MOV/WebM/MKV 或常见音频。")
    probe = _probe(path)
    streams = probe.get("streams", [])
    videos = [
        item
        for item in streams
        if item.get("codec_type") == "video" and not item.get("disposition", {}).get("attached_pic")
    ]
    audios = [item for item in streams if item.get("codec_type") == "audio"]
    duration = float(probe.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0 or duration > 14_400:
        raise ValueError("素材需有有效时长，且不超过四小时。")
    if videos and suffix in VIDEO_EXTENSIONS:
        video = videos[0]
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if min(width, height) < 1 or width * height > 40_000_000:
            raise ValueError("视频分辨率无效或过大。")
        return {
            "kind": "video",
            "duration": duration,
            "width": width,
            "height": height,
            "has_audio": bool(audios),
        }
    if audios and suffix in AUDIO_EXTENSIONS:
        return {"kind": "audio", "duration": duration}
    raise ValueError("文件扩展名与素材内容不匹配。")


def _font(size: int) -> ImageFont.ImageFont:
    """优先使用中英文字体；Linux 发布环境可安装 fonts-noto-cjk。"""
    candidates = [
        os.getenv("FRAMEWEAVE_FONT", ""),
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def _wrap(text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """逐字符测量，兼容没有空格的中文，不依赖终端编码或 FFmpeg drawtext。"""
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            if current and font.getlength(current + char) > max_width:
                lines.append(current)
                current = char
            else:
                current += char
        lines.append(current)
    return lines


def _caption(path: Path, scene: dict, width: int, height: int) -> None:
    """把分镜旁白绘成透明字幕层；字幕是镜头级，不伪装成逐字语音对齐。"""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    text = scene.get("narration", "").strip()
    if text:
        margin = max(12, round(width * 0.06))
        size = max(16, round(min(width, height) * 0.044))
        font = _font(size)
        lines = _wrap(text, font, width - margin * 2)
        while len(lines) > 4 and size > 16:
            size -= 2
            font = _font(size)
            lines = _wrap(text, font, width - margin * 2)
        # 很长的旁白仍保存在项目中；画面字幕最多四行，避免遮挡整幅画面。
        if len(lines) > 4:
            lines = lines[:4]
            lines[-1] = lines[-1][:-1] + "…"
        line_height = round(size * 1.5)
        box_height = line_height * len(lines) + 24
        top = height - box_height - max(18, round(height * 0.05))
        draw.rounded_rectangle(
            (margin // 2, top, width - margin // 2, top + box_height),
            radius=12,
            fill=(10, 20, 22, 205),
        )
        for index, line in enumerate(lines):
            x = (width - font.getlength(line)) / 2
            draw.text((x, top + 10 + index * line_height), line, font=font, fill="white")
    image.save(path)


def create_demo_assets(store: Any, project_id: str, recipe_id: str) -> list[dict]:
    """生成原创几何示意图，演示编辑与合成；不触发模型调用，也不包含私人肖像。"""
    recipes = {
        "tutorial": [
            ("把 AI 用起来", "先提出一个具体问题，再展示实际操作。"),
            ("让过程被看见", "用录屏替换这张示意图，加入自己的讲解。"),
            ("交付可复现的结果", "把关键步骤、提示词和结果一起分享。"),
        ],
        "knight-cat": [
            ("一只猫的冒险", "先确定角色外观，再为故事设计三个镜头。"),
            ("走进新的世界", "保持角色参考图与服装描述一致，再生成场景。"),
            ("让故事发生", "只重做不满意的镜头，保留已经完成的素材。"),
        ],
        "comparison": [
            ("从一个想法开始", "左边是原始素材，下一镜头展示处理过程。"),
            ("把方法讲清楚", "添加自己的屏幕录制，展示关键设置。"),
            ("看见结果的变化", "将结果放在这里，说明哪些地方得到了改善。"),
        ],
    }
    shots = recipes.get(recipe_id, recipes["tutorial"])
    directory = store.work_dir("demo-" + uuid.uuid4().hex)
    colors = [(25, 60, 53), (41, 49, 78), (89, 52, 41)]
    scenes = []
    # 示例采用与项目相同的画幅，避免竖屏新项目一开始出现大面积黑边。
    project = store.get_project(project_id)
    width, height = project["width"], project["height"]
    portrait = height > width
    for index, (title, narration) in enumerate(shots):
        image = Image.new("RGB", (width, height), colors[index])
        draw = ImageDraw.Draw(image)
        unit = min(width, height) / 720
        margin = int(min(width, height) * 0.09)
        draw.ellipse(
            (width * 0.60, -height * 0.18, width * 1.45, height * 0.36), fill=(181, 223, 132)
        )
        card = (
            (width * 0.12, height * 0.48, width * 0.88, height * 0.78)
            if portrait
            else (width * 0.65, height * 0.43, width * 0.90, height * 0.84)
        )
        draw.rounded_rectangle(
            card, radius=int(45 * unit), outline=(229, 239, 220), width=max(2, int(4 * unit))
        )
        left, top, right, bottom = card
        draw.line(
            (
                left + 30 * unit,
                bottom - 40 * unit,
                (left + right) / 2,
                top + 60 * unit,
                right - 30 * unit,
                bottom - 60 * unit,
            ),
            fill=(229, 239, 220),
            width=max(3, int(7 * unit)),
        )
        draw.text(
            (margin, height * 0.07),
            "FRAMEWEAVE / DEMO",
            font=_font(int(23 * unit)),
            fill=(194, 211, 197),
        )
        draw.text(
            (margin, height * 0.18),
            f"0{index + 1}",
            font=_font(int(95 * unit)),
            fill=(181, 223, 132),
        )
        title_font = _font(int(48 * unit))
        for line_index, line in enumerate(_wrap(title, title_font, width - margin * 2)):
            draw.text(
                (margin, height * (0.32 if portrait else 0.47) + line_index * 64 * unit),
                line,
                font=title_font,
                fill=(247, 247, 236),
            )
        caption = "本地示意素材 · 可替换为你的图片或视频"
        label_font = _font(int(21 * unit))
        for line_index, line in enumerate(_wrap(caption, label_font, width - margin * 2)):
            draw.text(
                (margin, height * 0.85 + line_index * 30 * unit),
                line,
                font=label_font,
                fill=(219, 225, 215),
            )
        path = directory / f"demo-{index + 1}.png"
        image.save(path)
        asset = store.register_asset(project_id, path, "image", source="demo")
        scenes.append(
            {
                "id": uuid.uuid4().hex,
                "title": title,
                "narration": narration,
                "prompt": "",
                "duration": 4,
                "media_asset_id": asset["id"],
                "audio_asset_id": None,
                "presenter_asset_id": None,
                "layout": "full",
            }
        )
    return scenes


async def _run_ffmpeg(arguments: list[str]) -> None:
    """使用参数数组执行；取消时终止本地子进程，避免后台继续占用资源。"""
    process = await asyncio.create_subprocess_exec(
        _tool("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        *arguments,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    try:
        _, stderr = await process.communicate()
    except asyncio.CancelledError:
        if process.returncode is None:
            process.terminate()
        await process.communicate()
        raise
    if process.returncode:
        # 不把内部文件路径或供应商输出抛到网页，仅保留可操作的说明。
        raise ValueError("视频合成失败，请确认素材可以播放、磁盘空间充足且 FFmpeg 支持 H.264/AAC。")


def _asset(
    store: Any, project_id: str, asset_id: str | None, kinds: set[str]
) -> tuple[Path, dict] | None:
    if not asset_id:
        return None
    record = store.get_asset(asset_id)
    if not record or record["project_id"] != project_id or record["kind"] not in kinds:
        raise ValueError("镜头引用的素材不存在、类型不符或不属于当前项目。")
    path = store.asset_path(asset_id)
    info = inspect_media(path)
    if info["kind"] not in kinds:
        raise ValueError("素材内容与分镜用途不匹配。")
    return path, info


def _visual_input(path: Path, info: dict) -> list[str]:
    options = ["-loop", "1"] if info["kind"] == "image" else ["-stream_loop", "-1"]
    return [*options, "-protocol_whitelist", "file,pipe", "-i", str(path)]


def _orient_image(visual: tuple[Path, dict], target: Path) -> tuple[Path, dict]:
    """手机照片先按 EXIF 转正，确保导出方向与浏览器预览保持一致。"""
    if visual[1]["kind"] == "image":
        with Image.open(visual[0]) as image:
            ImageOps.exif_transpose(image).convert("RGBA").save(target)
        return target, visual[1]
    return visual


async def _render_scene(
    store: Any, project: dict, scene: dict, directory: Path, index: int
) -> Path:
    width, height, fps = project["width"], project["height"], project["fps"]
    duration = float(scene["duration"])
    visual = _asset(store, project["id"], scene.get("media_asset_id"), {"image", "video"})
    if not visual:
        raise ValueError(f"第 {index + 1} 个镜头缺少画面素材，请先上传或生成。")
    visual = _orient_image(visual, directory / f"visual-{index}.png")
    inputs = _visual_input(*visual)
    filters = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x101b1a,setsar=1,fps={fps}[base]"
    ]
    base, count = "base", 1
    audio_index = 0 if visual[1].get("has_audio") else None
    if scene.get("layout") == "pip":
        presenter = _asset(
            store, project["id"], scene.get("presenter_asset_id"), {"image", "video"}
        )
        if not presenter:
            raise ValueError(f"第 {index + 1} 个镜头选择了画中画，请添加主持人图片或视频。")
        presenter = _orient_image(presenter, directory / f"presenter-{index}.png")
        inputs += _visual_input(*presenter)
        pip_width, pip_height = (
            max(2, round(width * 0.27) // 2 * 2),
            max(2, round(height * 0.42) // 2 * 2),
        )
        margin = max(12, round(width * 0.025))
        filters.append(
            f"[1:v]scale={pip_width}:{pip_height}:force_original_aspect_ratio=decrease,"
            f"pad={pip_width}:{pip_height}:(ow-iw)/2:(oh-ih)/2:color=0x203a33,setsar=1,fps={fps}[pip]"
        )
        filters.append(f"[base][pip]overlay=W-w-{margin}:{margin}:shortest=1[withpip]")
        base, count = "withpip", 2
        if presenter[1].get("has_audio"):
            audio_index = 1
    narration = _asset(store, project["id"], scene.get("audio_asset_id"), {"audio"})
    if narration:
        inputs += ["-protocol_whitelist", "file,pipe", "-i", str(narration[0])]
        audio_index, count = count, count + 1
    if audio_index is None:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio_index, count = count, count + 1
    caption = directory / f"caption-{index}.png"
    _caption(caption, scene, width, height)
    inputs += ["-loop", "1", "-i", str(caption)]
    filters.append(f"[{base}][{count}:v]overlay=0:0:shortest=1,format=yuv420p[outv]")
    filters.append(
        f"[{audio_index}:a]aresample=48000,aformat=channel_layouts=stereo,"
        f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS[outa]"
    )
    output = directory / f"scene-{index:04d}.mp4"
    await _run_ffmpeg(
        [
            *inputs,
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-threads",
            "4",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return output


async def _render(job: dict, project: dict, store: Any, progress: Progress) -> dict:
    scenes = project["scenes"]
    if not scenes:
        raise ValueError("请至少添加一个分镜后再合成。")
    _tool("ffmpeg")
    directory = store.work_dir(job["id"])
    clips = []
    await progress(2, "检查项目素材")
    for index, scene in enumerate(scenes):
        await progress(5 + 85 * index / len(scenes), f"正在合成镜头 {index + 1}/{len(scenes)}")
        clips.append(await _render_scene(store, project, scene, directory, index))
    await progress(92, "正在拼接镜头与封装视频")
    # 清单只写本引擎生成的固定相对文件名，不插入任何用户路径。
    manifest = directory / "concat.txt"
    manifest.write_text("".join(f"file '{clip.name}'\n" for clip in clips), encoding="utf-8")
    output = directory / "frameweave.mp4"
    await _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    info = inspect_media(output)
    await progress(98, "正在保存合成成品")
    asset = store.register_asset(project["id"], output, "video", source="render")
    return {"asset_id": asset["id"], "duration": info["duration"]}


async def _generate(job: dict, project: dict, store: Any, progress: Progress) -> dict:
    scene = next((s for s in project["scenes"] if s["id"] == job.get("scene_id")), None)
    if not scene:
        raise ValueError("要生成的镜头已不存在。")
    operation = job["operation"]
    params = job.get("params") or {}
    directory = store.work_dir(job["id"])
    await progress(5, "加载已配置的模型服务")
    if operation == "generate_media":
        workflow = str(params.get("workflow", "")).strip()
        parts = workflow.split("/")
        if (
            not re.fullmatch(r"[A-Za-z0-9_./-]+", workflow)
            or ".." in parts
            or parts[0] not in {"api", "selfhost", "runninghub"}
        ):
            raise ValueError("请选择有效模型，或填写 api/供应商/模型名 等工作流标识。")
        if not scene.get("prompt", "").strip():
            raise ValueError("请先填写当前镜头的画面提示词。")
    elif not scene.get("narration", "").strip():
        raise ValueError("请先填写当前镜头的旁白。")
    try:
        # 两个工作台是独立进程；每次明确生成前重载已保存配置，避免沿用旧密钥。
        # 供应商只在这里按需加载，离线编辑与合成不依赖其初始化。
        from pixelle_video.config import config_manager
        from pixelle_video.service import PixelleVideoCore

        config_manager.reload()
        async with PixelleVideoCore() as core:
            if operation == "generate_audio":
                target = directory / "narration.mp3"
                await progress(20, "正在请求在线语音服务（等待实际返回）")
                await core.tts(
                    text=scene["narration"],
                    inference_mode="local",
                    voice=params.get("voice") or "zh-CN-YunjianNeural",
                    speed=1.0,
                    output_path=str(target),
                )
            else:
                kind = params.get("media_type", "video")
                if kind not in {"image", "video"}:
                    raise ValueError("生成类型必须是 image 或 video。")
                target = directory / ("generated.png" if kind == "image" else "generated.mp4")
                reference = None
                if params.get("use_reference"):
                    item = _asset(store, project["id"], scene.get("media_asset_id"), {"image"})
                    if not item:
                        raise ValueError("首帧参考模式需要当前镜头已有一张图片。")
                    reference = str(item[0])
                await progress(20, "正在等待模型生成；进度由本地阶段表示")
                result = await core.media(
                    prompt=scene["prompt"],
                    workflow=workflow,
                    media_type=kind,
                    width=project["width"],
                    height=project["height"],
                    duration=params.get("duration") or scene["duration"],
                    image_path=reference,
                    output_path=str(target),
                    # 单镜任务不自动改写提示词并再次提交收费生成。
                    prompt_safety_retries=0,
                    # 上游图片适配器接收 image_paths，视频适配器接收 image_path。
                    **({"image_paths": [reference]} if reference and kind == "image" else {}),
                )
                if not target.is_file() and Path(str(result.url)).is_file():
                    target = Path(str(result.url))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # 不把可能包含 API key、签名 URL 或私有路径的供应商原始错误暴露到网页。
        raise ValueError(
            "模型调用未完成。请在旧版系统配置中检查连接、模型权限与时长参数；"
            "如果服务已受理请求，请先核实上游任务，避免重复扣费。"
        ) from exc
    if not target.is_file():
        raise ValueError("服务未返回可用的本地素材文件，请检查供应商响应。")
    await progress(95, "正在检查并保存生成素材")
    info = inspect_media(target)
    asset = store.register_asset(project["id"], target, info["kind"], source="generated")
    return {"asset_id": asset["id"], "duration": info.get("duration")}


async def run_job(job: dict, project_snapshot: dict, store: Any, progress: Progress) -> dict:
    """在独立作业目录执行；已完成镜头与旧版本素材始终保留。"""
    if job["operation"] == "render":
        return await _render(job, project_snapshot, store, progress)
    if job["operation"] in {"generate_media", "generate_audio"}:
        return await _generate(job, project_snapshot, store, progress)
    raise ValueError("未知任务类型。")
