"""素材创作页显式加载视觉目录；只读取型号，不上传素材或执行生成。"""

from copy import deepcopy


def load_and_save_asset_catalog(manager, provider: str) -> dict:
    """只保存当前视觉服务的目录，并拒绝查询期间已经变更的连接。"""
    from pixelle_video.services.api_services.model_catalog import (
        catalog_fingerprint,
        load_provider_model_ids,
        make_model_catalog,
    )

    if provider not in {"openai", "dashscope"}:
        raise ValueError("请选择已接入的视觉分析服务。")
    providers = manager.get_api_providers_config()
    config = deepcopy(providers.get(provider, {}))
    network = deepcopy(providers.get("common", {}))
    fingerprint = catalog_fingerprint(provider, config, network)
    if not fingerprint:
        raise ValueError("当前视觉服务的地址、密钥或代理配置不完整，请到系统设置检查。")
    # 文本 LLM 与其它提供商的凭据均不传递给目录接口。
    model_ids = load_provider_model_ids(provider, config, network)
    latest = manager.get_api_providers_config()
    latest_config = latest.get(provider, {})
    if catalog_fingerprint(provider, latest_config, latest.get("common", {})) != fingerprint:
        raise RuntimeError("查询期间视觉服务配置已变化，请重新加载目录。")
    snapshot = make_model_catalog(provider, config, network, model_ids)
    previous_catalog = deepcopy(latest_config.get("model_catalog", {}))
    # 仅更新目录字段，避免覆盖其它页面在查询期间保存的其它配置。
    manager.set_api_provider_config(provider, {"model_catalog": snapshot})
    try:
        manager.save()
    except Exception:
        # 保存失败时恢复内存目录，不能因为缓存先变更而误放行生成。
        manager.set_api_provider_config(provider, {"model_catalog": previous_catalog})
        raise RuntimeError("模型目录未能保存，请检查配置文件是否可写后重试。") from None
    return snapshot
