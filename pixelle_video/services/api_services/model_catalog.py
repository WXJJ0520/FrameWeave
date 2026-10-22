"""按用户明确操作读取当前服务的模型 ID，不探测生成能力、不保存凭据。

OpenAI：https://developers.openai.com/api/reference/resources/models/methods/list
DashScope：https://help.aliyun.com/zh/model-studio/list-models
xAI：https://docs.x.ai/developers/rest-api-reference/inference/models
Muse：https://github.com/czg86389-hub/muse2api
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit, urlunsplit

import requests

from .connectivity import CONNECTION_TIMEOUT, _base_url, _json_response, _model_ids

MAX_CATALOG_MODELS = 1000
MAX_CATALOG_PAGES = 10
CATALOG_PAGE_SIZE = 100
CATALOG_TIMEOUT_SECONDS = 30
DEFAULT_BASE_URLS = {
    "llm": "",
    "openai": "https://api.openai.com/v1",
    "dashscope": "https://dashscope.aliyuncs.com/api/v1",
    "xai": "https://api.x.ai/v1",
    "muse": "",
}
CATALOG_PROVIDERS = {*DEFAULT_BASE_URLS, "ark", "kling", "deepseek", "gemini"}


def _fingerprint_fields(provider: str, cfg: dict, network: dict | None = None) -> dict:
    """只取影响请求目标/身份/线路的字段，不把选择值或快照本身混入指纹。"""
    if provider not in CATALOG_PROVIDERS or not isinstance(cfg, dict):
        raise ValueError("invalid_provider")
    network = network if isinstance(network, dict) else {}
    # LLM 无隐式地址，媒体提供商的空值与其现有适配器默认地址保持一致。
    # 文本服务保留用户的实际路径；根地址与 /v1 指向不同接口，不能共用目录。
    raw_base = cfg.get("base_url") or DEFAULT_BASE_URLS.get(provider, "")
    base = _base_url(provider, raw_base)
    parts = urlsplit(base)
    host = parts.hostname.lower()
    host = f"[{host}]" if ":" in host else host
    port = parts.port
    netloc = host if port is None or (parts.scheme, port) in {("http", 80), ("https", 443)} else f"{host}:{port}"
    base = urlunsplit((parts.scheme.lower(), netloc, parts.path.rstrip("/"), "", ""))
    names = ("access_key", "secret_key") if provider == "kling" else ("api_key",)
    credentials = {}
    for name in names:
        value = cfg.get(name)
        if not isinstance(value, str) or not value.strip() or "\r" in value or "\n" in value:
            raise ValueError("invalid_credentials")
        credentials[name] = value.strip()
    use_proxy = bool(cfg.get("use_proxy"))
    proxy_value = ""
    if use_proxy:
        proxy_value = network.get("local_proxy", "").strip()
        proxy = urlsplit(proxy_value)
        if (proxy.scheme not in {"http", "https", "socks5", "socks5h"} or not proxy.hostname
                or proxy.fragment or any(char.isspace() for char in proxy_value)):
            raise ValueError("invalid_proxy")
        _ = proxy.port
    return {"provider": provider, "base_url": base, "credentials": credentials,
            "use_proxy": use_proxy, "local_proxy": proxy_value}


def catalog_fingerprint(provider: str, cfg: dict, network: dict | None = None) -> str:
    """未就绪配置返回空串；有效配置只返回 SHA-256，不泄露原始密钥或代理。"""
    try:
        fields = _fingerprint_fields(provider, cfg, network)
    except (ValueError, TypeError, AttributeError):
        return ""
    encoded = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_model_ids(model_ids: list, cfg: dict, network: dict | None = None) -> list[str]:
    if not isinstance(model_ids, list) or len(model_ids) > MAX_CATALOG_MODELS:
        raise ValueError("invalid_catalog_models")
    secrets = [cfg.get(name, "") for name in ("api_key", "access_key", "secret_key")]
    if cfg.get("use_proxy") and isinstance(network, dict):
        proxy = urlsplit(network.get("local_proxy") or "")
        secrets.extend(unquote(item) for item in (proxy.username, proxy.password) if item)
    normalized = {"data": [{"id": value.strip()} for value in model_ids if isinstance(value, str)]}
    return list(_model_ids(normalized, secrets=tuple(value.strip() for value in secrets if isinstance(value, str))) or ())


def make_model_catalog(
    provider: str, cfg: dict, network: dict | None, model_ids: list[str], source: str = "api",
) -> dict:
    """仅由显式加载/手工确认创建快照；不改变调用者配置，不做网络请求。"""
    fingerprint = catalog_fingerprint(provider, cfg, network)
    if not fingerprint:
        raise ValueError("请先填写当前服务的有效地址、凭据与代理配置，再保存模型目录。")
    if source not in {"api", "manual"}:
        raise ValueError("模型目录来源只能为接口加载或明确手工录入。")
    try:
        models = _snapshot_model_ids(model_ids, cfg, network)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("模型目录格式无效或超过 1000 项。") from None
    return {"fingerprint": fingerprint, "models": models, "source": source,
            "loaded_at": datetime.now(timezone.utc).isoformat()}


def get_configured_model_ids(provider: str, cfg: dict, network: dict | None = None) -> list[str]:
    """缺目录、配置变更或旧预设一律返回空列表，不静默回退静态型号。"""
    if not isinstance(cfg, dict):
        return []
    catalog = cfg.get("model_catalog")
    fingerprint = catalog_fingerprint(provider, cfg, network)
    if (not fingerprint or not isinstance(catalog, dict) or catalog.get("fingerprint") != fingerprint
            or catalog.get("source") not in {"api", "manual"}):
        return []
    try:
        return _snapshot_model_ids(catalog.get("models"), cfg, network)
    except (ValueError, TypeError, AttributeError):
        return []


def _catalog_request_config(provider: str, provider_config: dict, network_config: dict):
    """配置仅来自调用者当前输入；不会读取 config_manager 或环境 Key。"""
    if provider not in DEFAULT_BASE_URLS:
        if provider in {"ark", "kling"}:
            raise ValueError("该提供商暂未接入已验证的模型目录接口，请在系统配置明确手工录入可用模型。")
        raise ValueError("模型目录支持 OpenAI/兼容接口、DashScope、xAI 与 Muse。")
    if not isinstance(provider_config, dict) or not isinstance(network_config, dict):
        raise ValueError("模型目录配置格式不正确。")
    key = provider_config.get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("请先填写当前提供商的 API Key。")
    if "\r" in key or "\n" in key:
        raise ValueError("API Key 不能包含换行，请检查复制内容。")
    key = key.strip()
    try:
        base = _base_url(provider, provider_config.get("base_url") or DEFAULT_BASE_URLS[provider])
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Base URL 格式不正确，请填写服务基础地址，不要包含密钥或具体接口路径。") from None
    proxies = {}
    secrets = [key]
    if provider_config.get("use_proxy"):
        try:
            value = network_config.get("local_proxy", "").strip()
            proxy = urlsplit(value)
            if (proxy.scheme not in {"http", "https", "socks5", "socks5h"}
                    or not proxy.hostname or proxy.fragment or any(char.isspace() for char in value)):
                raise ValueError
            _ = proxy.port
        except (ValueError, TypeError, AttributeError):
            raise ValueError("已开启代理，请填写有效的本地代理地址，或关闭该服务的代理开关。") from None
        proxies = {"http": value, "https": value}
        secrets.extend(unquote(item) for item in (proxy.username, proxy.password) if item)
    return base, key, proxies, tuple(secrets)


def _check_status(response: requests.Response) -> None:
    """固定错误提示，禁止展示上游正文、URL、请求头或代理凭据。"""
    status = response.status_code
    if 200 <= status < 300:
        return
    hints = {
        401: "鉴权失败，请检查当前服务的 API Key。",
        403: "服务拒绝访问，请检查密钥权限及访问限制。",
        404: "服务未提供模型列表接口，请检查 Base URL，或手动填写模型名。",
        405: "服务未提供模型列表接口，请手动填写模型名。",
        429: "请求受到限流或额度限制，请稍后重试。",
    }
    hint = "地址发生重定向，未携带密钥继续跳转，请填写最终 API 地址。" if 300 <= status < 400 else hints.get(
        status, "模型目录请求失败，请检查服务状态。"
    )
    raise RuntimeError(f"HTTP {status}：{hint}")


def load_provider_model_ids(
    provider: str, provider_config: dict, network_config: dict | None = None,
) -> list[str]:
    """读取有界模型目录；返回 ID 不表示已验证图像、视频或文案能力。

    当前函数无自动调用/全局缓存。UI 仅由“从接口加载模型”按钮调用，将完整
    结果绑定当前连接；地址、凭据或启用的代理改变后失效，统一保存后生效。
    百炼原生目录有分页；最多 1000 个模型/10 页，超限明确失败而非冒充完整列表。
    """
    base, key, proxies, secrets = _catalog_request_config(provider, provider_config, network_config or {})
    # 使用用户原服务域名与前缀，不将中转密钥转发到猜测的官方地址。
    native_dashscope = provider == "dashscope" and not urlsplit(base).path.endswith("/compatible-mode/v1")
    deadline = time.monotonic() + CATALOG_TIMEOUT_SECONDS
    ids, seen = [], set()
    loaded_records = 0
    endpoint = "/video-generation-models" if provider == "xai" else "/models"
    try:
        with requests.Session() as session:
            session.trust_env = False
            for page in range(1, MAX_CATALOG_PAGES + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise requests.ReadTimeout()
                params = {"page_no": page, "page_size": CATALOG_PAGE_SIZE} if native_dashscope else None
                with session.get(
                    base + endpoint, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                    params=params, proxies=proxies, allow_redirects=False, stream=True,
                    timeout=(min(CONNECTION_TIMEOUT[0], remaining), min(CONNECTION_TIMEOUT[1], remaining)),
                ) as response:
                    # xAI 中转只在同一服务下回退一次，不向其它域名转发原密钥。
                    if provider == "xai" and endpoint == "/video-generation-models" and response.status_code in {404, 405}:
                        endpoint = "/models"
                        continue
                    _check_status(response)
                    data = _json_response(response, deadline=deadline)
                if data.get("error") or data.get("success") is False or data.get("code") not in (None, 0, "0"):
                    raise RuntimeError("模型列表接口返回业务错误，请检查账号权限或中转配置。")
                if provider == "xai" and endpoint == "/video-generation-models":
                    values = _model_ids(data, video_catalog=True, secrets=secrets)
                    if values is None:
                        raise ValueError("invalid_xai_catalog")
                    if len(values) > MAX_CATALOG_MODELS or data.get("has_more") is True:
                        raise RuntimeError("模型目录过大或尚有分页，请在服务后台确认可用目录。")
                    return list(values)
                if isinstance(data.get("data"), list):
                    # OpenAI 目录未提供能力证明；不依据命名模式筛选为“视觉模型”。
                    values = _model_ids(data, secrets=secrets) or ()
                    if len(values) > MAX_CATALOG_MODELS or data.get("has_more") is True:
                        raise RuntimeError("模型目录过大或尚有分页，请在服务后台确认模型名后手动填写。")
                    return list(values)
                output = data.get("output")
                if not native_dashscope or not isinstance(output, dict) or not isinstance(output.get("models"), list):
                    raise ValueError("invalid_catalog")
                items = output["models"]
                total = output.get("total")
                if total is not None and (type(total) is not int or total < 0):
                    raise ValueError("invalid_catalog_total")
                if total is not None and total > MAX_CATALOG_MODELS:
                    raise RuntimeError("模型目录超过 1000 项，请在服务后台确认模型名后手动填写。")
                normalized = {"data": [{"id": item.get("model")} for item in items if isinstance(item, dict)]}
                values = _model_ids(normalized, secrets=secrets) or ()
                added = [value for value in values if value not in seen]
                ids.extend(added)
                seen.update(added)
                loaded_records += len(items)
                if len(ids) > MAX_CATALOG_MODELS:
                    raise RuntimeError("模型目录超过 1000 项，请在服务后台确认模型名后手动填写。")
                if (total is not None and loaded_records >= total) or (total is None and len(items) < CATALOG_PAGE_SIZE):
                    return ids
                if not items or (page > 1 and not added):
                    raise RuntimeError("服务未返回后续模型目录，请在服务后台确认模型名后手动填写。")
        raise RuntimeError("模型目录超过分页上限，请在服务后台确认模型名后手动填写。")
    except requests.exceptions.Timeout:
        raise RuntimeError("读取模型目录超时，请检查服务地址与代理，稍后重试。") from None
    except requests.RequestException:
        raise RuntimeError("无法读取模型目录，请检查服务地址、代理和网络状态。") from None
    except (ValueError, UnicodeError, TypeError, AttributeError):
        raise RuntimeError("模型列表返回格式不兼容或响应过大，请手动填写模型名。") from None
