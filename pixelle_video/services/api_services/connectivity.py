"""媒体服务连通性诊断：只读查询，不创建生成任务，也不读取已保存的凭据。

查询协议依据：
https://docs.x.ai/developers/rest-api-reference/inference/models
https://help.aliyun.com/zh/model-studio/list-models
https://console.volcengine.com/ark/region:cn-beijing/docs/list-video-generation-tasks-api
https://kling.ai/document-api/api/video/3-0-omni/text-to-video/legacy
https://github.com/czg86389-hub/muse2api/blob/main/app.py
"""

import json
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

import jwt
import requests
from urllib3.exceptions import ReadTimeoutError


@dataclass(frozen=True)
class ConnectionCheckResult:
    """仅包含可展示的信息；不保留密钥、原始响应、带凭据的 URL 或异常。"""

    level: Literal["success", "warning", "error"]
    message: str
    details: tuple[str, ...] = ()
    latency_ms: int | None = None
    http_status: int | None = None
    model_ids: tuple[str, ...] = ()


PROVIDERS = {"openai", "xai", "muse", "dashscope", "ark", "kling"}
MAX_RESPONSE_BYTES = 1024 * 1024
CONNECTION_TIMEOUT = (10, 20)
GENERATION_NOTE = "本次仅检查查询接口，未提交生成任务；实际生成能力、额度和上游账号状态仍需另行验证。"


def _base_url(provider: str, value: str) -> str:
    """按适配器规则补全根地址；不猜测替换用户指定的域名或服务前缀。"""
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("请填写有效的 HTTP(S) Base URL。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Base URL 不能包含账号、密钥、查询参数或锚点。")
    if any(c.isspace() for c in value):
        raise ValueError("Base URL 不能包含空格或换行。")
    # 显式读取端口可提前发现 :abc 等拼写错误，而不向网络发送请求。
    _ = parts.port
    path = parts.path.rstrip("/")
    if path.endswith(("/models", "/chat/completions", "/videos", "/videos/generations", "/images/generations")):
        raise ValueError("请填写服务基础地址，不要包含 models、chat/completions 或生成接口路径。")
    if provider == "muse" and not path.endswith("/v1"):
        path += "/v1"
    elif not path:
        path = {"openai": "/v1", "xai": "/v1", "dashscope": "/api/v1", "ark": "/api/v3"}.get(provider, "")
    if provider == "kling" and path.endswith("/v1"):
        raise ValueError("Kling Base URL 请填写服务根地址，不要在末尾添加 /v1。")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _json_response(response: requests.Response, *, deadline: float | None = None) -> dict:
    """限制响应大小，避免反代返回大页面；不将原始响应带到日志或 UI。"""
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=16384):
        # 分页模型目录可设置整体截止时间，避免持续小块响应无限延长读取。
        if deadline is not None and time.monotonic() > deadline:
            raise requests.exceptions.ReadTimeout()
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        chunks.append(chunk)
    data = json.loads(b"".join(chunks))
    if not isinstance(data, dict):
        raise ValueError("unexpected_json")
    return data


def _model_ids(data: dict, *, video_catalog: bool = False, secrets: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    """只提取模型 ID；对可能回显密钥的响应做过滤，绝不展示其它响应字段。"""
    items = data.get("models" if video_catalog else "data")
    if not isinstance(items, list):
        return None
    ids = []
    for item in items:
        value = item.get("id") if isinstance(item, dict) else None
        if not isinstance(value, str) or not value or len(value) > 160:
            continue
        if any(secret and secret in value for secret in secrets):
            continue
        if not all(c.isalnum() or c in "._-:/" for c in value):
            continue
        if value not in ids:
            ids.append(value)
    return tuple(ids)


def _contains_read_timeout(error: BaseException) -> bool:
    """识别流式读取包装后的超时，只检查异常类型，不解析或展示原始异常。"""
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (ReadTimeoutError, requests.exceptions.ReadTimeout)):
            return True
        # requests.iter_content 会把 urllib3.ReadTimeoutError 包在 ConnectionError 中。
        pending.extend(item for item in current.args if isinstance(item, BaseException))
        pending.extend(item for item in (current.__cause__, current.__context__) if isinstance(item, BaseException))
    return False


def check_provider_connection(
    provider: str,
    *,
    base_url: str,
    api_key: str = "",
    access_key: str = "",
    secret_key: str = "",
    use_proxy: bool = False,
    local_proxy: str = "",
) -> ConnectionCheckResult:
    """检查页面当前输入的服务配置，只允许 GET；不保存配置或自动重试生成。"""
    started = time.perf_counter()
    status = None
    request_path = None

    def result(level, message, *details, models=()):
        if request_path is not None:
            # 界面仅显示前两条详情：第一条交代实际路径和线路，第二条保留结论与建议。
            route = "显式代理（仅使用已填写地址）" if use_proxy else "直连（未使用系统代理）"
            context = f"本次查询：GET {request_path}；网络：{route}；超时：连接 10 秒 / 读取 20 秒。"
            details = (context, " ".join(details)) if details else (context,)
        return ConnectionCheckResult(
            level, message, tuple(details),
            latency_ms=round((time.perf_counter() - started) * 1000) if request_path is not None else None,
            http_status=status, model_ids=tuple(models[:20]),
        )

    def network_advice() -> str:
        if use_proxy:
            return "检查所填代理是否运行、端口及线路是否可用；确认服务可直连后，也可关闭该服务的代理开关再测试。"
        return "如当前网络需要代理，请填写上方“本地代理”并勾选该服务的“启用代理”；Windows 或浏览器代理不会自动应用。"

    def read_timeout_result():
        # TLS 握手也可能表现为 ReadTimeout；收到 HTTP 状态前不能声称连接已建立。
        message = f"已收到 HTTP {status}，但读取响应正文超时。" if status is not None else "等待服务响应超时（可能发生在 HTTPS 握手或读取响应阶段）。"
        return result("error", message, "中转线路或服务器响应可能较慢。 " + network_advice())

    if provider not in PROVIDERS:
        return result("error", "不支持的媒体服务类型。")
    try:
        base = _base_url(provider, base_url)
    except (ValueError, TypeError, AttributeError):
        return result("error", "Base URL 格式不正确。", "请填写服务基础地址，例如 https://你的服务地址/v1；不要包含密钥或具体生成路径。")
    credentials = (access_key, secret_key) if provider == "kling" else (api_key,)
    if not all(isinstance(value, str) and value.strip() for value in credentials):
        return result("error", "请先填写 Access Key 和 Secret Key。" if provider == "kling" else "请先填写 API Key。")
    if any("\r" in value or "\n" in value for value in credentials):
        return result("error", "密钥不能包含换行，请检查复制内容。")
    proxies = {}
    if use_proxy:
        try:
            proxy = urlsplit(local_proxy.strip())
            if proxy.scheme not in {"http", "https", "socks5", "socks5h"} or not proxy.hostname or proxy.fragment:
                raise ValueError
            _ = proxy.port
        except (ValueError, TypeError, AttributeError):
            return result("error", "已启用代理，但代理地址为空或格式不正确。", "请填写上方“本地代理”，例如 http://127.0.0.1:9090，或关闭该服务的代理开关。")
        proxies = {"http": local_proxy.strip(), "https": local_proxy.strip()}
    if provider == "kling":
        now = int(time.time())
        token = jwt.encode({"iss": access_key.strip(), "iat": now, "nbf": now - 5, "exp": now + 300}, secret_key.strip(), algorithm="HS256")
    else:
        token = api_key.strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    # 只查询一条任务，且不向用户展示任务内容；这些接口不会提交生成。
    if provider == "ark":
        endpoint, params = "/contents/generations/tasks", {"page_num": 1, "page_size": 1}
    elif provider == "kling":
        endpoint, params = "/v1/videos/text2video", {"pageNum": 1, "pageSize": 1}
    elif provider == "dashscope":
        # 百炼模型目录采用 output.models/model，与 OpenAI 的 data/id 不同。
        endpoint, params = "/models", {"page_no": 1, "page_size": 1}
    else:
        endpoint, params = ("/video-generation-models" if provider == "xai" else "/models"), None

    fallback = False
    try:
        with requests.Session() as session:
            # 与新视频适配器一致：只使用显式代理，不偷偷使用系统代理或 netrc 凭据。
            session.trust_env = False
            while True:
                # 回退后重新记录本次状态，避免新请求超时却显示上一次的 HTTP 404。
                status = None
                request_path = quote(urlsplit(base + endpoint).path, safe="/%:@-._~")
                for secret in (*credentials, token):
                    if secret:
                        for encoded in {quote(secret.strip(), safe=""), quote(secret.strip(), safe="/%:@-._~")}:
                            request_path = request_path.replace(encoded, "[已隐藏凭据]")
                with session.get(base + endpoint, headers=headers, params=params, proxies=proxies,
                                 timeout=CONNECTION_TIMEOUT, allow_redirects=False, stream=True) as response:
                    status = response.status_code
                    # 部分中转只提供 /models；同一服务下回退一次，不能据此宣称视频接口已验证。
                    if provider == "xai" and not fallback and status in {404, 405}:
                        fallback, endpoint = True, "/models"
                        continue
                    if status == 401:
                        return result("error", "鉴权失败（HTTP 401）。", "请确认密钥属于当前 Base URL 对应的服务；中转密钥与官方密钥不可混用。")
                    if status == 403:
                        return result("error", "服务拒绝访问（HTTP 403）。", "检查账号权限、服务端访问限制、IP 白名单或地区限制。")
                    if status in {404, 405}:
                        return result("warning", "服务器已响应，但不支持当前查询接口。", "检查 Base URL 前缀和中转协议。此结果不能证明密钥有效，也不能证明生成接口可用。")
                    if 300 <= status < 400:
                        return result("warning", "地址发生重定向，未携带密钥继续跳转。", "请将 Base URL 改为最终 API 地址，避免填入网页登录地址。")
                    if status == 429:
                        return result("warning", "服务返回限流或额度限制（HTTP 429）。", "稍后重试，并检查服务端额度与并发限制。")
                    if status >= 500:
                        return result("error", f"服务端或网关异常（HTTP {status}）。", "检查中转服务运行状态及上游连接，稍后重试。")
                    if not 200 <= status < 300:
                        return result("error", f"查询请求未成功（HTTP {status}）。", "检查服务地址及接口版本。")
                    try:
                        data = _json_response(response)
                    except (ValueError, UnicodeError):
                        return result("warning", "服务器已响应，但未返回预期的 JSON 数据。", "可能填写了网站页面地址，或反向代理没有转发到 API。")
                    break
    except requests.exceptions.ProxyError:
        return result("error", "无法连接代理服务器。", network_advice())
    except requests.exceptions.SSLError:
        return result("error", "HTTPS 证书验证失败。", "检查域名、系统时间与反向代理证书链；请修复证书配置。")
    except requests.exceptions.ConnectTimeout:
        return result("error", "建立网络连接超时（连接等待 10 秒）。", network_advice())
    except requests.exceptions.ReadTimeout:
        return read_timeout_result()
    except requests.exceptions.Timeout:
        return result("error", "网络请求超时。", network_advice())
    except requests.exceptions.ConnectionError as error:
        if _contains_read_timeout(error):
            return read_timeout_result()
        return result("error", "无法建立连接或解析服务域名。", "检查 Base URL、服务是否启动及防火墙。 " + network_advice())
    except requests.exceptions.InvalidSchema:
        return result("error", "当前环境不支持所选代理协议。", "请改用 HTTP 代理地址。")
    except requests.RequestException:
        # 原始异常可能包含 URL、代理用户名或 Key，因此不能直接 str(exc)。
        return result("error", "网络请求失败。", "检查地址与密钥格式。 " + network_advice())

    if data.get("error") or ("code" in data and data["code"] not in (0, "0", None)):
        return result("error", "服务器已连接，但查询接口返回业务错误。", "请检查账号权限或中转配置；服务端详细原因可在对应后台查看。")
    if provider == "dashscope":
        output = data.get("output")
        if data.get("success") is False:
            return result("error", "百炼已响应，但模型查询未成功。", "检查 API Key 的业务空间权限及服务地址。")
        if data.get("success") is not True or not isinstance(output, dict) or not isinstance(output.get("models"), list):
            return result("warning", "百炼模型查询返回格式不匹配。", "请确认服务提供 /api/v1/models 原生查询接口。")
        normalized = {"data": [{"id": item.get("model")} for item in output["models"] if isinstance(item, dict)]}
        models = _model_ids(normalized, secrets=(*credentials, token)) or ()
        return result("success", "百炼模型查询接口连接成功。", GENERATION_NOTE,
                      "本次仅查询目录首页样本，不代表所有媒体模型权限。", models=models)
    if provider in {"ark", "kling"}:
        # 各平台的任务列表结构单独验证，HTTP 200 的网页或任意 JSON 不算测试通过。
        payload = data.get("data")
        valid = isinstance(data.get("items"), list) if provider == "ark" else (
            data.get("code") in (0, "0") and isinstance(payload, list)
        )
        if not valid:
            return result("warning", "服务器已响应，但任务查询返回格式不匹配。", "请确认当前地址实现了对应供应商的视频任务查询协议。")
        return result("success", "视频任务查询接口连接成功。", GENERATION_NOTE)
    models = _model_ids(data, video_catalog=provider == "xai" and not fallback, secrets=(*credentials, token))
    if models is None:
        return result("warning", "服务器已响应，但模型列表格式不匹配。", "请检查 API 协议或中转配置；不能据此确认模型可用。")
    expected = {
        "xai": lambda value: value.startswith("grok-imagine-video"),
        "muse": lambda value: value == "muse-video",
        "openai": lambda value: value.startswith("gpt-image"),
        "dashscope": lambda value: value.startswith(("wan", "happyhorse")),
    }[provider]
    relevant = tuple(value for value in models if expected(value))
    if not relevant:
        return result("warning", "模型查询接口已连接，但未返回当前接入的媒体模型。", GENERATION_NOTE,
                      "检查中转是否提供所需图像/视频模型及对应接口；部分服务不在列表中公开媒体模型。", models=models)
    notes = (GENERATION_NOTE,)
    if provider == "xai" and fallback:
        notes += ("该服务仅通过通用模型列表检查；仍需支持 xAI 的视频提交与任务查询协议。",)
    return result("success", f"模型查询接口连接成功，发现 {len(relevant)} 个相关模型。", *notes, models=relevant)
