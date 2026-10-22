# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
System settings component for web UI
"""

from copy import deepcopy

import streamlit as st

from pixelle_video.config import config_manager
from web.i18n import get_language, tr
from web.utils.streamlit_helpers import safe_rerun


def _render_configuration_usage(zh: bool):
    """按实际页面能力说明配置去向；收起展示，避免设置页再次堆成长列表。"""
    with st.expander("按功能找配置" if zh else "Find settings by feature", expanded=False):
        if zh:
            st.markdown(
                "| 想做什么 | 到哪里配置 |\n"
                "| --- | --- |\n"
                "| 自动写脚本、长视频章节、素材解说、画面提示词 | **文本模型** |\n"
                "| 看懂上传的图片或视频素材 | **图片与视频 → OpenAI / 通义**，配置视觉模型 |\n"
                "| 快速创作生成图片 | **图片与视频 → OpenAI / 通义 / 火山** |\n"
                "| 快速创作生成视频、图生视频 | **图片与视频 → Grok / Muse / 通义 / 火山 / 可灵** |\n"
                "| 数字人口播、动作迁移 | **图片与视频 → 通义**，在创作页选择对应能力的模型 |\n"
                "| 配音 | 创作页选择 **Edge TTS** 音色，无需 API 密钥，仍需联网 |"
            )
            st.caption("只需配置要使用的服务。视觉分析负责理解素材，文本模型负责写解说；两个步骤分别使用各自配置。模型权限与实际可用能力取决于你的服务和账号。")
        else:
            st.markdown(
                "| What you want to do | Where to configure it |\n"
                "| --- | --- |\n"
                "| Scripts, long-video chapters, asset narration, visual prompts | **Text models** |\n"
                "| Understand uploaded images or videos | **Image & video → OpenAI / DashScope**, vision models |\n"
                "| Generate images in Quick Create | **Image & video → OpenAI / DashScope / Volcengine** |\n"
                "| Generate clips in Quick Create or Image to Video | **Image & video → Grok / Muse / DashScope / Volcengine / Kling** |\n"
                "| Digital human or motion transfer | **Image & video → DashScope**, then choose a capable model in the creator |\n"
                "| Narration audio | Choose an **Edge TTS** voice in the creator; no API key, internet required |"
            )
            st.caption("Configure only the services you use. Vision understands assets; the text model writes narration, using separate settings. Model access and capabilities depend on your service and account.")


def _render_model_catalog(provider: str, cfg: dict, *, current: dict, network: dict, zh: bool) -> dict:
    """目录绑定当前输入；加载和手工应用均不保存，统一保存时再次验证快照。"""
    from pixelle_video.services.api_services.model_catalog import (
        catalog_fingerprint,
        get_configured_model_ids,
        load_provider_model_ids,
        make_model_catalog,
    )

    state_key = f"api_media_{provider}_model_catalog_state"
    mode_key = f"api_media_{provider}_catalog_mode"
    manual_key = f"api_media_{provider}_manual_models"
    fingerprint = catalog_fingerprint(provider, current, network)
    saved = cfg.get("model_catalog") or {}
    cached = st.session_state.get(state_key)
    valid_saved = bool(fingerprint and saved.get("fingerprint") == fingerprint)
    if cached is None:
        cached = {
            "fingerprint": fingerprint, "snapshot": deepcopy(saved) if valid_saved else {},
            "status": "loaded" if valid_saved else "unloaded",
            "saved_baseline": deepcopy(saved), "dirty": False,
        }
    elif cached.get("fingerprint") != fingerprint:
        # 不把旧 ID 重新绑定新地址/密钥；手工草稿保留，但必须再次明确应用。
        cached = {
            "fingerprint": fingerprint, "snapshot": {}, "status": "changed",
            "saved_baseline": deepcopy(saved), "dirty": True,
        }
    else:
        # 兼容已有会话：明确加载/失败的草稿优先，未加载状态可接收其他页保存的目录。
        cached.setdefault("dirty", cached.get("status") in {"changed", "failed"} or bool(cached.get("snapshot") and cached["snapshot"] != saved))
        cached.setdefault("saved_baseline", deepcopy(saved) if cached.get("snapshot") == saved else {})
        if cached.get("mode") is not None and mode_key in st.session_state and st.session_state[mode_key] != cached["mode"]:
            cached["dirty"] = True
        if cached["saved_baseline"] != saved and not cached["dirty"]:
            # 素材页可直接加载并保存目录；同连接下也需同步，不能由旧设置页覆盖回去。
            cached.update(
                snapshot=deepcopy(saved) if valid_saved else {},
                status="loaded" if valid_saved else "unloaded",
                saved_baseline=deepcopy(saved),
            )
            cached.pop("diagnostic", None)
            if valid_saved and saved.get("source") in {"api", "manual"}:
                st.session_state[mode_key] = saved["source"]
    st.session_state[state_key] = cached
    supports_api = provider in {"llm", "openai", "dashscope", "xai", "muse"}
    modes = ["api", "manual"] if supports_api else ["manual"]
    labels = {"api": "从接口加载" if zh else "Load from API", "manual": "手动维护（非接口加载）" if zh else "Manual list (not API-loaded)"}
    if st.session_state.get(mode_key) not in modes:
        st.session_state.pop(mode_key, None)
    selected_mode = st.radio(
        "模型目录来源" if zh else "Model catalog source", modes,
        index=modes.index(saved.get("source")) if saved.get("source") in modes else 0,
        format_func=lambda value: labels[value], horizontal=True, key=mode_key,
    )
    cached["mode"] = selected_mode
    snapshot = cached.get("snapshot") or {}
    if snapshot and snapshot.get("source") != selected_mode:
        cached["snapshot"] = {}
        cached["status"] = "changed"
        cached["dirty"] = True
        snapshot = {}
    st.caption(
        "创作页只使用保存后、与当前接口匹配的目录；列表本身不证明视觉或视频生成能力。"
        if zh else "Creators use only a saved catalog matching the current endpoint. A listing alone does not prove vision or video support."
    )
    if selected_mode == "api":
        button_key = "load_models_btn" if provider == "llm" else f"api_media_{provider}_load_models"
        if st.button(
            "从接口加载模型" if zh else "Load models from API", key=button_key,
            use_container_width=True, disabled=not fingerprint,
            help="只读取当前输入对应的目录，不保存、不生成。" if zh else "Queries current inputs without saving or generating.",
        ):
            cached.pop("diagnostic", None)
            try:
                with st.spinner("正在读取模型目录…" if zh else "Loading model catalog…"):
                    model_ids = load_provider_model_ids(provider, current, network)
                snapshot = make_model_catalog(provider, current, network, model_ids, source="api")
                cached.update(snapshot=snapshot, status="loaded", dirty=True)
                if provider == "llm" and model_ids and not cfg.get("model"):
                    custom_key = f"llm_custom_model_input_{st.session_state.get('llm_preset_select', 'Custom')}"
                    if not st.session_state.get(custom_key):
                        st.session_state["llm_model_source"] = "catalog"
            except (ValueError, RuntimeError) as exc:
                # 后端诊断均为固定脱敏文案；额外拒绝含本次凭据的异常，避免未来回归泄漏。
                diagnostic = str(exc)
                secret_values = [current.get(key) for key in ("api_key", "access_key", "secret_key")]
                if any(value and value in diagnostic for value in secret_values):
                    diagnostic = ""
                snapshot = {}
                cached.update(snapshot={}, status="failed", diagnostic=diagnostic[:250], dirty=True)
            except Exception:
                # 查询失败也清旧快照，避免空列表/错误后偷偷回退到预设或旧目录。
                snapshot = {}
                cached.update(snapshot={}, status="failed", dirty=True)
    else:
        if not supports_api:
            st.caption(
                "当前未接入该服务的模型目录查询，请按服务文档手动维护；不会把手填结果标成接口返回。"
                if zh else "Catalog querying is not integrated for this service. Maintain IDs from its documentation; manual entries are never labeled as API results."
            )
        manual_text = st.text_area(
            "手动模型目录（每行一个 ID）" if zh else "Manual model catalog (one ID per line)",
            value="\n".join(snapshot.get("models", [])) if snapshot.get("source") == "manual" else "",
            key=manual_key, height=100,
        )
        if st.button(
            "应用手动目录" if zh else "Apply manual catalog", key=f"api_media_{provider}_apply_manual_models",
            use_container_width=True, disabled=not fingerprint,
        ):
            try:
                model_ids = list(dict.fromkeys(line.strip() for line in manual_text.splitlines() if line.strip()))
                snapshot = make_model_catalog(provider, current, network, model_ids, source="manual")
                cached.update(snapshot=snapshot, status="loaded", dirty=True)
            except Exception:
                snapshot = {}
                cached.update(snapshot={}, status="failed", dirty=True)
    if cached["dirty"] and cached["saved_baseline"] != saved:
        st.caption(
            "其他页面已更新已保存目录；本页有未保存的目录操作，点击保存配置将应用本页结果。"
            if zh else "Another page updated the saved catalog. This page has unsaved catalog changes; saving settings will apply this page's result."
        )
    if cached["status"] == "failed":
        st.warning(
            "模型目录未能更新，请检查地址、密钥和服务支持情况。当前无可保存目录，可重试或明确选择手动维护。"
            if zh else "The catalog could not be updated. Check the endpoint, credentials and service support. No catalog is active; retry or explicitly choose a manual list."
        )
        if zh and cached.get("diagnostic"):
            st.caption(cached["diagnostic"])
    elif cached["status"] == "changed":
        st.info("配置或来源已变化，请重新加载或应用目录后再保存。" if zh else "Settings or source changed. Reload or apply the catalog before saving.")
    elif cached["status"] == "unloaded":
        st.info("尚未加载模型目录，请先填写服务配置，再加载并保存。" if zh else "No model catalog loaded. Configure the service, then load and save its catalog.")
    if snapshot:
        model_ids = get_configured_model_ids(provider, {**current, "model_catalog": snapshot}, network)
        source_label = ("接口加载" if zh else "API-loaded") if snapshot.get("source") == "api" else ("手动维护，未验证" if zh else "Manual, unverified")
        st.caption(f"{source_label} · {len(model_ids)} " + ("个模型" if zh else "models") + f" · {snapshot.get('loaded_at', '')}")
        if model_ids:
            st.caption(", ".join(model_ids[:8]) + (f" … (+{len(model_ids) - 8})" if len(model_ids) > 8 else ""))
            with st.expander("查看完整模型目录" if zh else "View full model catalog", expanded=False):
                st.code("\n".join(model_ids), language="text")
        else:
            st.warning("目录为空，创作页不会使用内置模型兜底。" if zh else "The catalog is empty. Creators will not fall back to built-in models.")
    # 最后一次校验避免回调、草稿恢复或输入改变后将旧目录写回新配置。
    return snapshot if fingerprint and snapshot.get("fingerprint") == fingerprint else {}


def _render_legacy_vision_models(provider: str, cfg: dict, *, zh: bool) -> list[str]:
    """历史手填名单单独保留，不升级为目录，也不冒充接口查询结果。"""
    configured = cfg.get("vision_models") or []
    with st.expander("历史手填视觉模型（兼容配置）" if zh else "Legacy vision IDs (compatibility settings)", expanded=False):
        st.caption(
            "保留已有手填值；它不是模型目录，不会自动出现在创作下拉中。需要使用时，请在上方手动目录中明确应用并保存。"
            if zh else "Existing values are preserved, but they are not a catalog and do not populate creator selectors. Explicitly apply and save a manual catalog above to use these IDs."
        )
        text = st.text_area(
            "历史视觉模型名" if zh else "Legacy vision model IDs", value="\n".join(configured),
            key=f"api_media_{provider}_vision_models", height=100,
        )
    return list(dict.fromkeys(line.strip() for line in text.splitlines() if line.strip()))


def _render_api_provider_connection_test(
    provider: str,
    *,
    base_url: str,
    api_key: str = "",
    access_key: str = "",
    secret_key: str = "",
    use_proxy: bool = False,
    local_proxy: str = "",
    zh: bool = True,
):
    """用当前表单值只读测试，输入变化后自动移除旧结果，不保存任何配置。"""
    import hashlib
    import hmac
    import json
    import secrets
    from datetime import datetime, timedelta, timezone

    values = {
        "base_url": base_url,
        "api_key": api_key,
        "access_key": access_key,
        "secret_key": secret_key,
        "use_proxy": use_proxy,
        "local_proxy": local_proxy,
    }
    # 会话只保留带随机密钥的摘要；诊断记录不复制表单中的明文凭据。
    salt_key = "_api_media_connection_check_salt"
    if salt_key not in st.session_state:
        st.session_state[salt_key] = secrets.token_bytes(32)
    fingerprint = hmac.new(
        st.session_state[salt_key],
        json.dumps({"provider": provider, **values}, sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    result_key = f"api_media_{provider}_connection_result"
    previous = st.session_state.get(result_key)
    if previous and previous.get("fingerprint") != fingerprint:
        del st.session_state[result_key]

    if st.button(
        "测试连接" if zh else "Test connection",
        key=f"api_media_{provider}_test",
        use_container_width=True,
    ):
        try:
            # 延迟导入，只有用户点击时才执行查询；不会调用生成接口。
            from pixelle_video.services.api_services.connectivity import check_provider_connection

            with st.spinner("正在测试连接…" if zh else "Testing connection…"):
                result = check_provider_connection(provider, **values)
            st.session_state[result_key] = {
                "fingerprint": fingerprint,
                "level": result.level,
                "message": result.message,
                "details": tuple(result.details),
                "latency_ms": result.latency_ms,
                "http_status": result.http_status,
                "model_ids": tuple(result.model_ids),
            }
        except Exception:
            # 异常可能包含请求头或带凭据的地址，界面与诊断缓存均不显示原始异常。
            st.session_state[result_key] = {
                "fingerprint": fingerprint,
                "level": "error",
                "message": "连接测试未完成，请检查地址、密钥和代理设置后重试。",
                "details": (),
                "latency_ms": None,
                "http_status": None,
                "model_ids": (),
            }
        # 标注实际测试时间，避免会话保留的成功结果被误认为持续在线监测。
        st.session_state[result_key]["checked_at"] = datetime.now(
            timezone(timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")

    saved_result = st.session_state.get(result_key)
    if not saved_result:
        return
    level = saved_result["level"]
    display = {"success": st.success, "warning": st.warning, "error": st.error}.get(level, st.error)
    display(saved_result["message"])
    if saved_result.get("checked_at"):
        st.caption(
            f"上次测试：{saved_result['checked_at']}（北京时间）"
            if zh
            else f"Last tested: {saved_result['checked_at']} (UTC+08:00)"
        )
    timing = []
    if saved_result["latency_ms"] is not None:
        timing.append(("响应耗时：" if zh else "Response time: ") + f"{saved_result['latency_ms']} ms")
    if saved_result["http_status"] is not None:
        timing.append(f"HTTP {saved_result['http_status']}")
    if timing:
        st.caption(" · ".join(timing))
    for detail in saved_result["details"][:2]:
        st.caption(detail)
    model_ids = saved_result["model_ids"]
    if model_ids:
        # 只展示少量模型，避免第三方模型列表占满整个设置页面。
        model_text = ", ".join(model_ids[:5])
        if len(model_ids) > 5:
            model_text += f" … (+{len(model_ids) - 5})"
        st.caption(("查询到模型：" if zh else "Models returned: ") + model_text)


def render_advanced_settings(*, on_saved=None):
    """渲染可嵌入弹窗的配置正文，保存成功后可交由外层关闭弹窗。"""
    zh = get_language() == "zh_CN"
    api_cfg = config_manager.get_api_providers_config()
    common_cfg = api_cfg.get("common", {})
    openai_cfg = api_cfg.get("openai", {})
    xai_cfg = api_cfg.get("xai", {})
    muse_cfg = api_cfg.get("muse", {})
    dashscope_cfg = api_cfg.get("dashscope", {})
    ark_cfg = api_cfg.get("ark", {})
    kling_cfg = api_cfg.get("kling", {})
    default_api_base_urls = {
        "openai": "https://api.openai.com/v1",
        "xai": "https://api.x.ai/v1",
        "dashscope": "https://dashscope.aliyuncs.com/api/v1",
        "ark": "https://ark.cn-beijing.volces.com/api/v3",
        "kling": "https://api-beijing.klingai.com",
    }

    _render_configuration_usage(zh)

    text_tab, media_tab, network_tab = st.tabs(
        ["文本模型", "图片与视频", "网络与调试"]
        if zh else ["Text models", "Image & video", "Network & debugging"]
    )

    # 网络页视觉上位于最后，但先读取当前输入，供各媒体服务的连接测试使用。
    with network_tab:
        st.caption(
            "媒体服务的代理地址在这里统一填写，再到各服务页启用代理。"
            if zh else "Set the shared media proxy here, then enable it for each provider."
        )
        api_local_proxy = st.text_input(
            "本地代理（可选）" if zh else "Local proxy (optional)",
            value=common_cfg.get("local_proxy", ""),
            placeholder="http://127.0.0.1:9090",
            help=(
                "仅部分提供商会使用，例如 OpenAI 图像模型。留空表示不使用代理。"
                if zh
                else "Only used by some providers, such as OpenAI image models. Leave blank to disable."
            ),
            key="api_media_local_proxy",
        )

        api_print_model_input = st.checkbox(
            "打印模型请求参数" if zh else "Print model request parameters",
            value=bool(common_cfg.get("print_model_input", False)),
            help=(
                "调试用。开启后会在终端打印发送给图像/视频模型的 prompt、模型名和输入文件路径。"
                if zh
                else "For debugging. Prints prompts, model names and input file paths sent to image/video models."
            ),
            key="api_media_print_model_input",
        )

    # 标签页仅改变布局，所有表单每次仍会渲染，保持原控件 key 与草稿值。
    with text_tab:
        st.markdown(f"**{tr('settings.llm.title')}**")
        st.caption(
            "用于：快速创作脚本与长视频章节、自定义素材解说、标题和画面提示词。这里的密钥与下方 OpenAI 图片/视觉分析配置独立。"
            if zh else "Used for Quick Create scripts and chapters, Custom Media narration, titles and visual prompts. These credentials are separate from OpenAI image/vision settings below."
        )
        st.caption(
            "文本模型使用 OpenAI 兼容 API（如 Ollama 的 /v1）。测试当前输入不会保存配置。"
            if zh else "Text models use an OpenAI-compatible API, such as Ollama's /v1. Testing current inputs does not save settings."
        )

        # Quick preset selection
        from pixelle_video.llm_presets import (
            find_preset_by_base_url_and_model,
            get_preset,
            get_preset_names,
        )

        # Custom at the end
        preset_names = get_preset_names() + ["Custom"]

        # Get current config
        current_llm = config_manager.get_llm_config()

        # Auto-detect which preset matches current config
        current_preset = find_preset_by_base_url_and_model(
            current_llm["base_url"],
            current_llm["model"]
        )

        # Determine default index based on current config
        if current_preset:
            # Current config matches a preset
            default_index = preset_names.index(current_preset)
        else:
            # Current config doesn't match any preset -> Custom
            default_index = len(preset_names) - 1

        selected_preset = st.selectbox(
            tr("settings.llm.quick_select"),
            options=preset_names,
            index=default_index,
            # 保留预设业务名称，中文界面仅翻译自定义选项的展示文字。
            format_func=lambda name: ("自定义" if zh else "Custom") if name == "Custom" else name,
            help=tr("settings.llm.quick_select_help"),
            key="llm_preset_select"
        )

        # Auto-fill based on selected preset
        if selected_preset != "Custom":
            # Preset selected
            preset_config = get_preset(selected_preset)

            # If user switched to a different preset (not current one), clear API key
            # If it's the same as current config, keep API key
            if selected_preset == current_preset:
                # Same preset as saved config: keep API key
                default_api_key = current_llm["api_key"]
            else:
                # Different preset: use default_api_key if provided (e.g., Ollama), otherwise clear
                default_api_key = preset_config.get("default_api_key", "")

            default_base_url = preset_config.get("base_url", "")
            # 预设只填服务地址；模型须从当前接口加载或由用户独立手填。
            default_model = current_llm["model"] if selected_preset == current_preset else ""

            # Show API key URL if available
            if preset_config.get("api_key_url"):
                st.markdown(f"🔑 [{tr('settings.llm.get_api_key')}]({preset_config['api_key_url']})")
        else:
            # Custom: show current saved config (if any)
            default_api_key = current_llm["api_key"]
            default_base_url = current_llm["base_url"]
            default_model = current_llm["model"]

        st.markdown("---")

        # API Key (use unique key to force refresh when switching preset)
        llm_api_key = st.text_input(
            f"{tr('settings.llm.api_key')} *",
            value=default_api_key,
            type="password",
            help=tr("settings.llm.api_key_help"),
            key=f"llm_api_key_input_{selected_preset}"
        )

        # Base URL (use unique key based on preset to force refresh)
        llm_base_url = st.text_input(
            f"{tr('settings.llm.base_url')} *",
            value=default_base_url,
            help=tr("settings.llm.base_url_help"),
            key=f"llm_base_url_input_{selected_preset}"
        )

        # 文本下拉只显示当前快照中的目录，不插入预设或手填值冒充接口返回。
        from pixelle_video.utils.llm_util import normalize_openai_base_url
        llm_current = {"api_key": llm_api_key, "base_url": normalize_openai_base_url(llm_base_url)}
        llm_catalog = _render_model_catalog("llm", current_llm, current=llm_current, network={}, zh=zh)
        from pixelle_video.services.api_services.model_catalog import get_configured_model_ids
        llm_model_ids = get_configured_model_ids("llm", {**llm_current, "model_catalog": llm_catalog}, {})
        model_source_labels = {"catalog": "从当前目录选择" if zh else "Choose from current catalog", "custom": "独立自定义模型" if zh else "Independent custom model"}
        model_source = st.radio(
            "文本模型选择方式" if zh else "Text model selection", list(model_source_labels),
            index=0 if default_model in llm_model_ids else 1,
            format_func=lambda value: model_source_labels[value], horizontal=True, key="llm_model_source",
        )
        select_key = f"llm_model_select_{selected_preset}"
        choice_required_key = f"{select_key}_requires_choice"
        previous_choice = st.session_state.get(select_key)
        if previous_choice and previous_choice not in llm_model_ids:
            st.session_state[choice_required_key] = True
        elif previous_choice in llm_model_ids:
            st.session_state.pop(choice_required_key, None)
        if previous_choice not in llm_model_ids:
            st.session_state.pop(select_key, None)
        # 新目录移除了旧选择时保持空值，不能悄悄替换为目录首项。
        choice_required = st.session_state.get(choice_required_key, False)
        model_index = None
        if not choice_required:
            if default_model in llm_model_ids:
                model_index = llm_model_ids.index(default_model)
            elif not default_model and llm_model_ids:
                model_index = 0
        selected_model = st.selectbox(
            f"{tr('settings.llm.model')} *", llm_model_ids,
            index=model_index,
            key=select_key, disabled=model_source != "catalog" or not llm_model_ids,
            placeholder="请先加载模型目录" if zh else "Load a catalog first",
        )
        if choice_required and llm_model_ids and model_source == "catalog":
            st.info("原选模型不在当前目录，请明确选择型号；不会自动换成第一项。" if zh else "The previous model is absent from this catalog. Select a model explicitly; it will not switch to the first entry automatically.")
        # 两种模式始终渲染，切换目录/手填时不丢失原模型或未保存别名。
        custom_model = st.text_input(
            tr("settings.llm.custom_model_input"), value=default_model,
            help="手工模型名与接口目录独立，不作为已查询的可用模型。" if zh else "Manual IDs are independent from the API catalog and are not presented as discovered models.",
            key=f"llm_custom_model_input_{selected_preset}", disabled=model_source != "custom",
        )
        llm_model = selected_model if model_source == "catalog" else custom_model
        if st.button(f"🔌 {tr('settings.llm.test_connection')}", key="test_llm_connection_btn", use_container_width=True):
            if llm_api_key and llm_base_url:
                try:
                    from pixelle_video.utils.llm_util import test_llm_connection
                    with st.spinner(tr("settings.llm.loading_models")):
                        success, message, model_count = test_llm_connection(llm_api_key, llm_base_url)
                    if success:
                        st.success(tr("settings.llm.connection_success").replace("{count}", str(model_count)))
                    else:
                        st.warning("连接检查未通过，请检查地址、密钥和服务状态。" if zh else "Connection check failed. Check the endpoint, credentials and service.")
                except Exception:
                    st.warning("连接检查未完成，请检查地址、密钥和服务状态。" if zh else "Connection check could not complete. Check the endpoint, credentials and service.")
            else:
                st.warning(tr("status.llm_config_incomplete"))

    provider_catalogs = {}
    # 工作台仅配置直连模型 API；历史工作流凭据不展示，也不在保存时修改。
    with media_tab:
        st.caption(
            "分别填写所使用的图片、视频或视觉分析服务，密钥仅用于对应的平台。"
            if zh
            else "Configure image, video and visual analysis services independently. Credentials are only used for their own provider."
        )
        st.caption(
            "测试连接使用当前输入值，无需先保存；仅检查查询接口，不会生成内容，也不保证实际生成可用。兼容服务仍需支持对应图像或视频协议。"
            if zh
            else "Tests use the current form values without saving and only query the service. They do not generate content or guarantee generation; compatible services must support the relevant image or video API."
        )

        grok_tab, muse_tab, openai_tab, dashscope_tab, ark_tab, kling_tab = st.tabs(
            ["Grok", "Muse", "OpenAI", "通义", "火山", "可灵"]
            if zh else ["Grok", "Muse", "OpenAI", "DashScope", "Volcengine", "Kling"]
        )
        with grok_tab:
            # Grok 视频接口单独配置，不会自动使用 OpenAI 的密钥。
            st.markdown("**xAI / Grok Imagine Video**")
            st.caption(
                "用于：快速创作的视频镜头、图生视频。使用 Grok 视频模型，不负责素材视觉分析。"
                if zh else "Used for video clips in Quick Create and Image to Video, through Grok video models. This does not analyze uploaded assets."
            )
            api_xai_use_proxy = st.checkbox(
                "xAI 启用代理" if zh else "Use proxy for xAI",
                value=bool(xai_cfg.get("use_proxy", False)),
                key="api_media_xai_use_proxy",
            )
            api_xai_key = st.text_input(
                "xAI API 密钥" if zh else "xAI API Key",
                value=xai_cfg.get("api_key", ""),
                type="password",
                key="api_media_xai_key",
            )
            api_xai_base_url = st.text_input(
                "xAI 服务地址" if zh else "xAI Base URL",
                value=xai_cfg.get("base_url") or default_api_base_urls["xai"],
                placeholder="https://api.x.ai/v1",
                key="api_media_xai_base_url",
            )
            _render_api_provider_connection_test(
                "xai", base_url=api_xai_base_url, api_key=api_xai_key,
                use_proxy=api_xai_use_proxy, local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["xai"] = _render_model_catalog(
                "xai", xai_cfg, zh=zh,
                current={"api_key": api_xai_key, "base_url": api_xai_base_url, "use_proxy": bool(api_xai_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )

        with muse_tab:
            # muse2api 是用户自建服务，地址与密钥必须独立填写。
            st.markdown("**Meta Muse / muse2api**")
            st.caption(
                "用于：快速创作的视频镜头、图生视频，通过你自建的 muse2api 服务调用。"
                if zh else "Used for video clips in Quick Create and Image to Video through your own muse2api service."
            )
            st.caption(
                "填写你自建的 muse2api 地址和该服务密钥，不会复用 OpenAI 密钥。"
                if zh
                else "Enter your self-hosted muse2api URL and its own API key. The OpenAI key is not reused."
            )
            api_muse_use_proxy = st.checkbox(
                "Muse 启用代理" if zh else "Use proxy for Muse",
                value=bool(muse_cfg.get("use_proxy", False)),
                key="api_media_muse_use_proxy",
            )
            api_muse_key = st.text_input(
                "Muse API 密钥" if zh else "Muse API Key",
                value=muse_cfg.get("api_key", ""),
                type="password",
                key="api_media_muse_key",
            )
            api_muse_base_url = st.text_input(
                "Muse 服务地址" if zh else "Muse Base URL",
                value=muse_cfg.get("base_url") or "",
                placeholder="https://your-muse-server/v1",
                key="api_media_muse_base_url",
            )
            _render_api_provider_connection_test(
                "muse", base_url=api_muse_base_url, api_key=api_muse_key,
                use_proxy=api_muse_use_proxy, local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["muse"] = _render_model_catalog(
                "muse", muse_cfg, zh=zh,
                current={"api_key": api_muse_key, "base_url": api_muse_base_url, "use_proxy": bool(api_muse_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )

        with openai_tab:
            st.markdown("**OpenAI / GPT Image / Vision**")
            st.caption(
                "用于：GPT 图片生成；自定义素材的图片理解、视频抽帧理解。视觉模型需要支持图片输入，与文本模型页的密钥独立。"
                if zh else "Used for GPT image generation and Custom Media image/video-frame understanding. Vision models must accept images. Credentials are separate from the Text models tab."
            )
            api_openai_use_proxy = st.checkbox(
                "OpenAI 启用代理" if zh else "Use proxy for OpenAI",
                value=bool(openai_cfg.get("use_proxy", False)),
                key="api_media_openai_use_proxy",
            )
            api_openai_key = st.text_input(
                "OpenAI API 密钥" if zh else "OpenAI API Key",
                value=openai_cfg.get("api_key", ""),
                type="password",
                key="api_media_openai_key",
            )
            api_openai_base_url = st.text_input(
                "OpenAI 服务地址" if zh else "OpenAI Base URL",
                value=openai_cfg.get("base_url") or default_api_base_urls["openai"],
                placeholder="https://api.openai.com/v1",
                key="api_media_openai_base_url",
            )
            _render_api_provider_connection_test(
                "openai", base_url=api_openai_base_url, api_key=api_openai_key,
                use_proxy=api_openai_use_proxy, local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["openai"] = _render_model_catalog(
                "openai", openai_cfg, zh=zh,
                current={"api_key": api_openai_key, "base_url": api_openai_base_url, "use_proxy": bool(api_openai_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )
            api_openai_vision_models = _render_legacy_vision_models("openai", openai_cfg, zh=zh)

        with dashscope_tab:
            st.markdown("**DashScope / Wan / HappyHorse**")
            st.caption(
                "用于：图片生成、Wan / HappyHorse 视频；自定义素材的图片理解、视频抽帧理解；已接入的数字人口播和动作迁移模型。各功能需选择对应能力的模型。"
                if zh else "Used for images, Wan/HappyHorse video; Custom Media image/video-frame understanding; and integrated digital-human and motion-transfer models. Choose a model that supports the required task."
            )
            api_dashscope_use_proxy = st.checkbox(
                "DashScope 启用代理" if zh else "Use proxy for DashScope",
                value=bool(dashscope_cfg.get("use_proxy", False)),
                key="api_media_dashscope_use_proxy",
            )
            api_dashscope_key = st.text_input(
                "DashScope API 密钥" if zh else "DashScope API Key",
                value=dashscope_cfg.get("api_key", ""),
                type="password",
                key="api_media_dashscope_key",
            )
            api_dashscope_base_url = st.text_input(
                "DashScope 服务地址" if zh else "DashScope Base URL",
                value=dashscope_cfg.get("base_url") or default_api_base_urls["dashscope"],
                placeholder="https://dashscope.aliyuncs.com/api/v1",
                key="api_media_dashscope_base_url",
            )
            _render_api_provider_connection_test(
                "dashscope", base_url=api_dashscope_base_url, api_key=api_dashscope_key,
                use_proxy=api_dashscope_use_proxy, local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["dashscope"] = _render_model_catalog(
                "dashscope", dashscope_cfg, zh=zh,
                current={"api_key": api_dashscope_key, "base_url": api_dashscope_base_url, "use_proxy": bool(api_dashscope_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )
            api_dashscope_vision_models = _render_legacy_vision_models("dashscope", dashscope_cfg, zh=zh)

        with ark_tab:
            st.markdown("**Volcengine ARK / Seedream / Seedance**")
            st.caption(
                "用于：Seedream 图片生成、Seedance 视频镜头及图生视频。"
                if zh else "Used for Seedream image generation, Seedance video clips and Image to Video."
            )
            api_ark_use_proxy = st.checkbox(
                "ARK 启用代理" if zh else "Use proxy for ARK",
                value=bool(ark_cfg.get("use_proxy", False)),
                key="api_media_ark_use_proxy",
            )
            api_ark_key = st.text_input(
                "ARK API 密钥" if zh else "ARK API Key",
                value=ark_cfg.get("api_key", ""),
                type="password",
                key="api_media_ark_key",
            )
            api_ark_base_url = st.text_input(
                "ARK 服务地址" if zh else "ARK Base URL",
                value=ark_cfg.get("base_url") or default_api_base_urls["ark"],
                placeholder="https://ark.cn-beijing.volces.com/api/v3",
                key="api_media_ark_base_url",
            )
            _render_api_provider_connection_test(
                "ark", base_url=api_ark_base_url, api_key=api_ark_key,
                use_proxy=api_ark_use_proxy, local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["ark"] = _render_model_catalog(
                "ark", ark_cfg, zh=zh,
                current={"api_key": api_ark_key, "base_url": api_ark_base_url, "use_proxy": bool(api_ark_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )

        with kling_tab:
            st.markdown("**Kling AI / 可灵**")
            st.caption(
                "用于：快速创作的视频镜头、图生视频。使用可灵 Access Key 与 Secret Key。"
                if zh else "Used for video clips in Quick Create and Image to Video. Requires Kling Access Key and Secret Key."
            )
            api_kling_use_proxy = st.checkbox(
                "Kling 启用代理" if zh else "Use proxy for Kling",
                value=bool(kling_cfg.get("use_proxy", False)),
                key="api_media_kling_use_proxy",
            )
            api_kling_base_url = st.text_input(
                "Kling 服务地址" if zh else "Kling Base URL",
                value=kling_cfg.get("base_url") or default_api_base_urls["kling"],
                placeholder="https://api-beijing.klingai.com",
                key="api_media_kling_base_url",
            )
            api_kling_access_key = st.text_input(
                "Kling Access Key",
                value=kling_cfg.get("access_key", ""),
                type="password",
                key="api_media_kling_access_key",
            )
            api_kling_secret_key = st.text_input(
                "Kling Secret Key",
                value=kling_cfg.get("secret_key", ""),
                type="password",
                key="api_media_kling_secret_key",
            )
            _render_api_provider_connection_test(
                "kling", base_url=api_kling_base_url, access_key=api_kling_access_key,
                secret_key=api_kling_secret_key, use_proxy=api_kling_use_proxy,
                local_proxy=api_local_proxy, zh=zh,
            )
            provider_catalogs["kling"] = _render_model_catalog(
                "kling", kling_cfg, zh=zh,
                current={"access_key": api_kling_access_key, "secret_key": api_kling_secret_key, "base_url": api_kling_base_url, "use_proxy": bool(api_kling_use_proxy)},
                network={"local_proxy": api_local_proxy},
            )

    # 保存操作保留在统一页脚，恢复默认配置收起到更多操作中。
    st.divider()
    if st.button(tr("btn.save_config"), use_container_width=True, key="save_config_btn"):
        try:
            # 已填写连接时目录必须同步保存，空/失败目录不能因未选模型而留下旧快照。
            # 地址或密钥仍缺失时保留原文本配置，继续允许独立保存媒体 API。
            llm_connection_complete = bool(llm_api_key.strip() and llm_base_url.strip())
            llm_config_complete = bool(llm_connection_complete and llm_model)
            if llm_connection_complete:
                config_manager.set_llm_config(llm_api_key, llm_base_url, llm_model or "", model_catalog=llm_catalog)

            # Save direct image/video API provider configuration.
            config_manager.set_api_provider_config("common", {
                "print_model_input": bool(api_print_model_input),
                "local_proxy": api_local_proxy or "",
            })
            config_manager.set_api_provider_config("openai", {
                "api_key": api_openai_key or "",
                "base_url": api_openai_base_url or "",
                "use_proxy": bool(api_openai_use_proxy),
                "model_catalog": provider_catalogs["openai"],
                "vision_models": api_openai_vision_models,
            })
            # xAI 与其他媒体提供商一起保存，不依赖 LLM 是否已配置。
            config_manager.set_api_provider_config("xai", {
                "api_key": api_xai_key or "",
                "base_url": api_xai_base_url or "",
                "use_proxy": bool(api_xai_use_proxy),
                "model_catalog": provider_catalogs["xai"],
            })
            config_manager.set_api_provider_config("muse", {
                "api_key": api_muse_key or "",
                "base_url": api_muse_base_url or "",
                "use_proxy": bool(api_muse_use_proxy),
                "model_catalog": provider_catalogs["muse"],
            })
            config_manager.set_api_provider_config("dashscope", {
                "api_key": api_dashscope_key or "",
                "base_url": api_dashscope_base_url or "",
                "use_proxy": bool(api_dashscope_use_proxy),
                "model_catalog": provider_catalogs["dashscope"],
                "vision_models": api_dashscope_vision_models,
            })
            config_manager.set_api_provider_config("ark", {
                "api_key": api_ark_key or "",
                "base_url": api_ark_base_url or "",
                "use_proxy": bool(api_ark_use_proxy),
                "model_catalog": provider_catalogs["ark"],
            })
            config_manager.set_api_provider_config("kling", {
                "base_url": api_kling_base_url or "",
                "access_key": api_kling_access_key or "",
                "secret_key": api_kling_secret_key or "",
                "use_proxy": bool(api_kling_use_proxy),
                "model_catalog": provider_catalogs["kling"],
            })

            # 只更新当前可编辑的 API 配置；历史工作流凭据由管理器原样保留。
            config_manager.save()
            # 成功保存才结束本页目录草稿；失败/空列表也须保留清空意图直到此次保存。
            saved_catalogs = dict(provider_catalogs)
            if llm_connection_complete:
                saved_catalogs["llm"] = llm_catalog
            for provider, snapshot in saved_catalogs.items():
                cached = st.session_state.get(f"api_media_{provider}_model_catalog_state")
                if cached is not None:
                    cached.update(saved_baseline=deepcopy(snapshot), dirty=False)
            st.success(tr("status.config_saved"))
            if not llm_config_complete:
                if llm_connection_complete:
                    st.warning(
                        "服务配置和模型目录已保存，当前未选文本模型；请加载目录后选择模型，或使用独立自定义模型，再生成文案。"
                        if zh else "Service settings and catalogs were saved, but no text model is selected. Load and select a model or use an independent custom ID before generating scripts."
                    )
                else:
                    st.warning(
                        "媒体 API 配置已保存。文本服务地址或密钥不完整，已保留原文本设置；使用自动文案前请补全。"
                        if zh else "Media API settings were saved. The text URL or key is incomplete, so previous text settings were kept; complete them before generating scripts."
                    )
            # 弹窗负责草稿清理与关闭；独立渲染时保留原来的刷新行为。
            if on_saved is not None:
                on_saved()
            elif llm_config_complete:
                safe_rerun()
        except Exception as e:
            st.error(f"{tr('status.save_failed')}: {str(e)}")

    with st.expander("更多操作" if zh else "More options", expanded=False):
        if st.button(tr("btn.reset_config"), use_container_width=True, key="reset_config_btn"):
            # 仅重置本页可编辑的配置，避免删除不再展示的旧凭据及创作偏好。
            from pixelle_video.config.schema import PixelleVideoConfig
            defaults = PixelleVideoConfig()
            config_manager.config.llm = defaults.llm
            config_manager.config.api_providers = defaults.api_providers
            config_manager.save()
            st.success(tr("status.config_reset"))
            if on_saved is not None:
                on_saved()
            else:
                safe_rerun()
