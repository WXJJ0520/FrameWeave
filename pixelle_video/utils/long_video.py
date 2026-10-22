"""镜织长片规划：用有字数预算的章节组合短镜头，不拉慢或填空白凑时长。"""

import json
import math
import re
from typing import Callable, Optional

# 仅用于创作预算；不同音色、停顿和数字读法会影响实测语速。
_UNITS_PER_SECOND = {"zh": 3.6, "en": 2.35}
_UNIT_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
_MAX_SCENES = 240


def _speech_rate(narration_language: str, tts_speed: float) -> float:
    """验证共享预算参数，避免 NaN 或错误语言静默导致不合理调用数。"""
    if narration_language not in _UNITS_PER_SECOND:
        raise ValueError("长片旁白语言仅支持 zh 或 en。")
    if isinstance(tts_speed, bool) or not isinstance(tts_speed, (int, float)):
        raise ValueError("配音语速必须是 0.5–2.0 的数值。")
    if not math.isfinite(tts_speed) or not 0.5 <= tts_speed <= 2.0:
        raise ValueError("配音语速必须在 0.5–2.0 之间。")
    return _UNITS_PER_SECOND[narration_language] * tts_speed


def count_narration_units(text: str) -> int:
    """中文逐字、英文逐词计数，忽略标点空白；混合文案也保留可读词。"""
    return len(_UNIT_TOKEN.findall(text))


def estimate_narration_seconds(
    text: str, narration_language: str = "zh", tts_speed: float = 1.0
) -> float:
    """本地估算旁白时长，不调用配音服务，也不冒充实际成片时长。"""
    return round(count_narration_units(text) / _speech_rate(narration_language, tts_speed), 1)


def build_long_video_plan(
    target_duration_seconds: int, narration_language: str = "zh", tts_speed: float = 1.0
) -> dict:
    """生成 UI 与后端共享的 JSON 预算；长片只接收 5–10 分钟目标。"""
    if type(target_duration_seconds) is not int or not 300 <= target_duration_seconds <= 600:
        raise ValueError("长片目标时长必须是 300–600 秒的整数。")
    rate = _speech_rate(narration_language, tts_speed)
    chapter_count = math.ceil(target_duration_seconds / 60)
    scene_count = math.ceil(target_duration_seconds / 8)
    target_units = round(target_duration_seconds * rate)
    units_per_scene = target_units / scene_count
    chapters = []
    scene_start = 0
    allocated_units = 0
    # 均匀分配余数，让章节预算的总和始终等于影片预算。
    for index in range(chapter_count):
        scenes = scene_count // chapter_count + int(index < scene_count % chapter_count)
        next_units = round(target_units * (scene_start + scenes) / scene_count)
        chapter_units = next_units - allocated_units
        chapters.append({
            "index": index + 1,
            "scene_start": scene_start,
            "scene_count": scenes,
            "target_units": chapter_units,
            "estimated_duration_seconds": round(chapter_units / rate, 1),
        })
        scene_start += scenes
        allocated_units = next_units
    return {
        "target_duration_seconds": target_duration_seconds,
        "narration_language": narration_language,
        "tts_speed": float(tts_speed),
        "chapter_count": chapter_count,
        "scene_count": scene_count,
        "target_units": target_units,
        "unit_label": "字" if narration_language == "zh" else "words",
        "min_units_per_scene": max(1, math.floor(units_per_scene * 0.65)),
        "max_units_per_scene": math.ceil(units_per_scene * 1.35),
        "estimated_duration_seconds": round(target_units / rate, 1),
        "expected_media_calls": scene_count,
        "duration_tolerance_seconds": round(target_duration_seconds * 0.15, 1),
        "chapters": chapters,
    }


def split_long_script(
    text: str, narration_language: str = "zh", tts_speed: float = 1.0,
    split_mode: str = "paragraph",
) -> list[str]:
    """保留手写稿内容，先按用户方式分段，再将长段按句子/词边界拆开。"""
    max_units = max(1, math.floor(_speech_rate(narration_language, tts_speed) * 10))
    if split_mode == "paragraph":
        paragraphs = re.split(r"\n\s*\n", text)
    elif split_mode == "line":
        paragraphs = text.splitlines()
    elif split_mode == "sentence":
        paragraphs = re.split(r"(?<=[。！？.!?])\s*", text)
    else:
        raise ValueError("未知的手写稿分段方式。")
    segments = []
    for paragraph in paragraphs:
        remainder = paragraph.strip()
        while remainder:
            tokens = list(_UNIT_TOKEN.finditer(remainder))
            if len(tokens) <= max_units:
                segments.append(remainder)
                break
            # 优先在预算范围后半段的句末断开；无标点时也不会删字或拆英文单词。
            hard_end = tokens[max_units].start()
            soft_start = tokens[max(0, max_units // 2 - 1)].end()
            boundaries = list(re.finditer(r"[。！？.!?；;，,]\s*", remainder[soft_start:hard_end]))
            end = soft_start + boundaries[-1].end() if boundaries else hard_end
            segments.append(remainder[:end].strip())
            remainder = remainder[end:].strip()
    # 分隔线、表情或单独标点不应作为一次空文本 TTS 请求；按原顺序并到相邻旁白。
    # 开头尚无旁白时暂存，后续无可读文本则仍拒绝，不能静默丢弃原稿字符。
    spoken_segments = []
    prefix = ""
    for segment in segments:
        if count_narration_units(segment):
            spoken_segments.append(prefix + segment)
            prefix = ""
        elif spoken_segments:
            spoken_segments[-1] += "\n" + segment
        else:
            prefix += segment + "\n"
    if not spoken_segments:
        raise ValueError("请填写可配音的手写稿。")
    if len(spoken_segments) > _MAX_SCENES:
        raise ValueError(f"手写稿拆分超过 {_MAX_SCENES} 个镜头，请精简稿件后再生成。")
    return spoken_segments


def _json_object(response: str) -> dict:
    """只解析 JSON 或完整 Markdown JSON 块，不修补截断的模型回答。"""
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("长片脚本格式应为 JSON 对象。")
    return value


async def generate_long_narrations(
    llm_service, topic: str, plan: dict,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> tuple[list[str], list[dict]]:
    """先做全片大纲，再串行生成各章；预算不达标时只修订该章一次。"""
    language = "简体中文" if plan["narration_language"] == "zh" else "English"
    outline_prompt = (
        f"你在为镜织 FrameWeave 创作一条约 {plan['target_duration_seconds']} 秒的完整讲解视频。\n"
        f"主题：{topic}\n语言：{language}\n"
        f"规划恰好 {plan['chapter_count']} 个连续章节，形成开场、递进讲解、例子与总结。"
        "每章 focus 写不同的具体内容，避免重复开场、空话和捏造无法证实的事实。"
        '仅返回 JSON：{"chapters":[{"title":"章节标题","focus":"本章讲什么"}]}。'
    )
    outline = None
    for attempt in range(2):
        response = await llm_service(prompt=outline_prompt, temperature=0.5, max_tokens=4096)
        try:
            entries = _json_object(response).get("chapters")
            if not isinstance(entries, list) or len(entries) != plan["chapter_count"]:
                raise ValueError("章节数量不符")
            if any(not isinstance(item, dict) or any(
                not isinstance(item.get(key), str) or not item[key].strip()
                for key in ("title", "focus")
            ) for item in entries):
                raise ValueError("章节标题或要点缺失")
            outline = [{"title": item["title"].strip(), "focus": item["focus"].strip()}
                       for item in entries]
            break
        except (ValueError, TypeError):
            if attempt == 1:
                raise ValueError("长片章节规划格式不完整，尚未开始生成配音和画面，请重试。") from None
            outline_prompt += "\n上次格式或数量不正确，请严格按要求返回完整 JSON。"

    narrations = []
    chapter_metadata = []
    for chapter, heading in zip(plan["chapters"], outline):
        minimum = math.ceil(chapter["target_units"] * 0.9)
        maximum = math.floor(chapter["target_units"] * 1.1)
        prompt = (
            f"为主题“{topic}”撰写完整视频的第 {chapter['index']}/{plan['chapter_count']} 章。\n"
            f"语言：{language}。全片大纲：{json.dumps(outline, ensure_ascii=False)}\n"
            f"本章：{heading['title']}；要点：{heading['focus']}。\n"
            f"前文结尾：{narrations[-1] if narrations else '这是开场章节'}\n"
            f"返回恰好 {chapter['scene_count']} 段可直接配音的旁白，总计 {minimum}–{maximum} "
            f"{plan['unit_label']}，每段 {plan['min_units_per_scene']}–{plan['max_units_per_scene']} "
            f"{plan['unit_label']}。中文按汉字计、英文按词计，标点不计。"
            "每段对应一个镜头，衔接自然，提供实质细节与具体例子，不重复填充内容；"
            "不要标题、镜头编号、角色标签、画面指令或 Markdown。"
            '仅返回 JSON：{"narrations":["旁白一","旁白二"]}。'
        )
        accepted = None
        for attempt in range(2):
            response = await llm_service(
                prompt=prompt, temperature=0.6,
                max_tokens=min(8192, max(4096, chapter["target_units"] * 3 + 1024)),
            )
            try:
                values = _json_object(response).get("narrations")
                if not isinstance(values, list) or len(values) != chapter["scene_count"]:
                    raise ValueError("镜头数量不符合预算")
                if any(not isinstance(item, str) or not item.strip() for item in values):
                    raise ValueError("旁白有空项或格式错误")
                counts = [count_narration_units(item) for item in values]
                if not minimum <= sum(counts) <= maximum:
                    raise ValueError(f"本章文字总量 {sum(counts)}，需要 {minimum}–{maximum}")
                if any(not plan["min_units_per_scene"] <= value <= plan["max_units_per_scene"]
                       for value in counts):
                    raise ValueError("部分镜头旁白长度超出预算")
                accepted = [item.strip() for item in values]
                break
            except (ValueError, TypeError) as error:
                if attempt == 1:
                    raise ValueError(
                        f"第 {chapter['index']} 章旁白未达到长片预算，尚未开始生成配音和画面，请重试。"
                    ) from None
                prompt += f"\n上次校验未通过：{error}。请重新返回本章完整旁白，按预算补充实质内容。"
        chapter_metadata.append({**chapter, **heading, "actual_units": sum(
            count_narration_units(value) for value in accepted
        )})
        narrations.extend(accepted)
        if progress_callback:
            progress_callback(chapter["index"], plan["chapter_count"])
    return narrations, chapter_metadata


def build_duration_report(target_duration_seconds: int, actual_duration_seconds: float) -> dict:
    """记录 FFprobe 实测与目标的差值；不自动重跑模型或修改正常音频。"""
    tolerance = round(target_duration_seconds * 0.15, 1)
    measured = math.isfinite(actual_duration_seconds) and actual_duration_seconds > 0
    delta = round(actual_duration_seconds - target_duration_seconds, 2) if measured else None
    return {
        "target_duration_seconds": target_duration_seconds,
        "actual_duration_seconds": round(actual_duration_seconds, 2) if measured else None,
        "deviation_seconds": delta,
        "duration_tolerance_seconds": tolerance,
        "within_tolerance": abs(delta) <= tolerance if measured else None,
        "measurement_status": "measured" if measured else "unavailable",
    }
