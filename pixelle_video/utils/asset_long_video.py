"""镜织素材长片规划：章节脚本绑定真实素材，预算与复用情况可复核。"""

import json
import math
import re
from collections import Counter
from collections.abc import Callable

from pixelle_video.prompts.asset_script_generation import (
    build_asset_chapter_prompt,
    build_asset_outline_prompt,
)
from pixelle_video.utils.long_video import (
    build_long_video_plan,
    count_narration_units,
    estimate_narration_seconds,
)


def build_asset_long_video_plan(
    duration: int, narration_language: str = "zh", tts_speed: float = 1.2,
    asset_count: int = 0,
) -> dict:
    """供页面和管线共用；素材数不足时预告重复引用，不冒充新画面生成。"""
    if type(duration) is not int or duration not in (300, 480, 600):
        raise ValueError("素材长片目标时长请选择 5、8 或 10 分钟。")
    if type(asset_count) is not int or asset_count < 0:
        raise ValueError("素材数量必须是非负整数。")
    plan = build_long_video_plan(duration, narration_language, tts_speed)
    plan.update({
        "asset_count": asset_count,
        "minimum_reused_scenes": max(0, plan["scene_count"] - asset_count),
        "expected_media_calls": 0,  # 原素材默认直接配音合成，动效由用户另行开启。
        "video_selection_strategy": "uniform_time_windows",
    })
    return plan


def asset_usage_summary(scenes: list[dict]) -> dict[str, int]:
    """记录实际绑定次数，不能把重复镜头计作更多上传素材。"""
    return dict(Counter(scene["asset_path"] for scene in scenes))


def video_window(source_duration: float, narration_duration: float,
                 occurrence: int, use_count: int) -> dict:
    """在可用时间内均匀取窗；这是时间采样，不声称视觉模型定位到具体事件。"""
    if any(not math.isfinite(value) or value <= 0
           for value in (source_duration, narration_duration)):
        raise ValueError("素材或旁白时长无效，无法安全选择视频片段。")
    if use_count < 1 or not 0 <= occurrence < use_count:
        raise ValueError("素材引用序号无效。")
    available_start = max(0.0, source_duration - narration_duration)
    start = available_start * occurrence / (use_count - 1) if use_count > 1 else 0.0
    return {
        "start_seconds": round(start, 6),
        "duration_seconds": narration_duration,
        "source_duration_seconds": source_duration,
        "loop_source": source_duration < narration_duration,
        "occurrence": occurrence + 1,
        "use_count": use_count,
    }


def _object(response: str) -> dict:
    """只接受完整 JSON；不修补被 token 上限截断的脚本。"""
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("脚本必须是 JSON 对象。")
    return value


def _validate_chapter(response: str, chapter: dict, plan: dict, assets: dict) -> list[dict]:
    """路径与旁白预算一起验证，未知路径不能回退首张图掩盖错误。"""
    scenes = _object(response).get("scenes")
    if not isinstance(scenes, list) or len(scenes) != chapter["scene_count"]:
        raise ValueError("镜头数不符合章节预算")
    cleaned = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict) or scene.get("asset_path") not in assets:
            raise ValueError("素材路径不在已分析的可用素材中")
        narrations = scene.get("narrations")
        if (not isinstance(narrations, list) or not 1 <= len(narrations) <= 3
                or any(not isinstance(text, str) or not text.strip() for text in narrations)):
            raise ValueError("每个镜头必须有 1–3 段非空旁白")
        narration = " ".join(text.strip() for text in narrations)
        size = count_narration_units(narration)
        if not plan["min_units_per_scene"] <= size <= plan["max_units_per_scene"]:
            raise ValueError("单镜头旁白长度不符合预算")
        cleaned.append({
            "scene_number": chapter["scene_start"] + index + 1,
            "chapter_index": chapter["index"],
            "asset_path": scene["asset_path"],
            "narrations": [narration],  # 每镜一次配音避免逐句拼接额外停顿。
            "duration": estimate_narration_seconds(
                narration, plan["narration_language"], plan["tts_speed"]),
        })
    units = sum(count_narration_units(scene["narrations"][0]) for scene in cleaned)
    if not math.ceil(chapter["target_units"] * 0.9) <= units <= math.floor(chapter["target_units"] * 1.1):
        raise ValueError("本章旁白总量未达到目标时长预算")
    return cleaned


async def generate_asset_long_script(
    llm_service, intent: str, title: str, assets: dict, plan: dict,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[list[dict], list[dict]]:
    """全部章节通过后才返回给配音阶段；每次不合格仅修订本章一次。"""
    if not assets:
        raise ValueError("没有成功分析的素材，尚未开始生成文案或配音。")
    assets_text = json.dumps([
        {"asset_path": path, "type": meta["type"], "description": meta["description"]}
        for path, meta in assets.items()
    ], ensure_ascii=False)
    prompt = build_asset_outline_prompt(intent, title, assets_text, plan)
    outline = None
    for attempt in range(2):
        response = await llm_service(prompt=prompt, temperature=0.5, max_tokens=4096)
        try:
            outline = _object(response).get("chapters")
            if not isinstance(outline, list) or len(outline) != plan["chapter_count"]:
                raise ValueError("章节数量不正确")
            if any(not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip()
                for key in ("title", "focus")
            ) for item in outline):
                raise ValueError("章节标题或要点缺失")
            outline = [{key: item[key].strip() for key in ("title", "focus")} for item in outline]
            break
        except (ValueError, TypeError, AttributeError):
            if attempt:
                raise ValueError("素材长片大纲不完整，尚未开始生成配音，请重试。") from None
            prompt += "\n上次格式或章节数错误，请返回完整且符合要求的 JSON。"
    scenes, chapters = [], []
    for chapter, heading in zip(plan["chapters"], outline):
        prompt = build_asset_chapter_prompt(
            intent, title, assets_text, plan, chapter, heading, outline,
            scenes[-1]["narrations"][0] if scenes else "这是开场章节",
        )
        accepted = None
        for attempt in range(2):
            response = await llm_service(
                prompt=prompt, temperature=0.6,
                max_tokens=min(8192, max(4096, chapter["target_units"] * 3 + 2048)),
            )
            try:
                accepted = _validate_chapter(response, chapter, plan, assets)
                break
            except (ValueError, TypeError, AttributeError) as error:
                if attempt:
                    raise ValueError(
                        f"第 {chapter['index']} 章素材脚本未通过路径或旁白预算校验，"
                        "尚未开始生成配音，请重试。"
                    ) from None
                prompt += f"\n上次校验未通过：{error}。请返回本章完整修订稿，不要删减内容凑数。"
        scenes.extend(accepted)
        chapters.append({**chapter, **heading, "actual_units": sum(
            count_narration_units(scene["narrations"][0]) for scene in accepted
        )})
        if progress_callback:
            progress_callback(chapter["index"], plan["chapter_count"])
    return scenes, chapters
