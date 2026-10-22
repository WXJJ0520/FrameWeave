"""长视频生成前的时长和素材预算，只做本地估算，不触发模型或配音。"""

import streamlit as st

from web.i18n import get_language


def format_duration(seconds: float) -> str:
    """统一用分秒呈现目标与实际时长，避免把生成耗时误当成片时长。"""
    minutes, remainder = divmod(max(0, round(seconds)), 60)
    return f"{minutes}:{remainder:02d}"


def prepare_long_video_summary(params: dict) -> dict:
    """复用后端同一规划器，参数修改后预算与提交使用相同语速、语言和稿件。"""
    from pixelle_video.utils.long_video import (
        build_long_video_plan,
        estimate_narration_seconds,
        split_long_script,
    )
    from pixelle_video.utils.template_util import get_template_type

    language = params.get("narration_language", "zh")
    # 仅缺省值使用正常语速；零或非法输入应与后端一致地交给规划器拒绝。
    speed = params.get("tts_speed")
    if speed is None:
        speed = 1.0
    plan = build_long_video_plan(params["target_duration_seconds"], language, speed)
    plan = dict(plan)
    if params.get("mode") == "fixed":
        text = params.get("text") or ""
        plan["scene_count"] = len(split_long_script(
            text, language, speed, split_mode=params.get("split_mode", "paragraph")
        )) if text.strip() else 0
        plan["estimated_duration_seconds"] = estimate_narration_seconds(text, language, speed)
    # 静态文字模板无需媒体生成，图片/视频只估算镜头数，不冒充精确计费次数。
    template = params.get("frame_template") or "1080x1920/default.html"
    needs_media = get_template_type(template) != "static" and params.get("media_workflow")
    plan["media_tasks"] = plan["scene_count"] if needs_media else 0
    plan["expected_media_calls"] = plan["media_tasks"]
    return plan


def render_long_video_summary(params: dict) -> bool:
    """末步显示有用的生成预算；非法目标在提交前阻断，原短片入口不受影响。"""
    if params.get("target_duration_seconds") is None:
        return True
    zh = get_language() == "zh_CN"
    try:
        plan = prepare_long_video_summary(params)
    except (ValueError, TypeError):
        st.error(
            "长视频参数无效，请检查目标时长、稿件长度、旁白语言和语速。"
            if zh else "Invalid long-video settings. Check the target duration, script length, narration language and speech rate."
        )
        return False
    with st.container(border=True):
        st.markdown("**长视频生成计划**" if zh else "**Long-video production plan**")
        target, scenes, media = st.columns(3)
        target.metric("目标成片" if zh else "Target duration", format_duration(plan["target_duration_seconds"]))
        scenes.metric("预计镜头" if zh else "Planned scenes", plan["scene_count"])
        media.metric("画面任务" if zh else "Visual tasks", plan["media_tasks"])
        if params.get("mode") == "fixed":
            estimate = format_duration(plan["estimated_duration_seconds"])
            st.caption(
                f"按当前原稿和语速估计约 {estimate}；保留原稿，不自动补字或重复内容。"
                if zh else f"Your current script and speech rate suggest about {estimate}. The original text is preserved without adding or repeating content."
            )
            if abs(plan["estimated_duration_seconds"] - plan["target_duration_seconds"]) > plan["duration_tolerance_seconds"]:
                st.warning(
                    "原稿预计长度与目标时长差距较大。可以返回补充或精简文案，或按原稿继续生成。"
                    if zh else "The estimated script duration differs substantially from the target. Edit your script or continue with its original length."
                )
        else:
            units = "中文字" if params.get("narration_language", "zh") == "zh" else "英文单词"
            st.caption(
                f"按当前语速规划 {plan['chapter_count']} 个章节、约 {plan['target_units']} 个{units}，逐章生成以减少长稿截断。"
                if zh else f"At the current speech rate: {plan['chapter_count']} chapters and about {plan['target_units']} {'Chinese characters' if params.get('narration_language', 'zh') == 'zh' else 'English words'}, generated chapter by chapter."
            )
        st.caption(
            "先完成旁白与画面，再拼接和混入背景音乐。实际时长以成片检测为准。"
            if zh else "Narration and visuals are produced first, then assembled with background music. The final file is measured for its actual duration."
        )
        if plan["media_tasks"]:
            st.info(
                "每个画面任务会调用所选模型，可能包含额外参考图请求。图片模式可做图文讲解；视频模式会逐镜头生成短片。"
                if zh else "Each visual task calls the selected model and may require additional reference images. Image mode produces illustrated narration; video mode generates short clips for each scene."
            )
    return True
