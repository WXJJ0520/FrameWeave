"""ComfyUI 只读连通诊断：不加载配置、不生成内容、不输出原始服务端错误。"""

import errno
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError

# 诊断文案只取自本地映射，第三方返回体和异常可能含有密钥，不能直接显示。
MESSAGES = {
    "empty": (
        "请填写 ComfyUI 服务地址。",
        "例如 http://127.0.0.1:8188；远程部署填写实际可访问的地址。",
        "Enter a ComfyUI service URL.",
        "For example, http://127.0.0.1:8188; use the accessible server URL for a remote deployment.",
    ),
    "url": (
        "ComfyUI 地址格式不正确。",
        "使用完整 http:// 或 https:// 地址；密钥填在独立字段中，不要附带查询参数或页面锚点。",
        "The ComfyUI URL is invalid.",
        "Use a complete http:// or https:// URL. Put the key in its own field, without query parameters or page fragments.",
    ),
    "endpoint": (
        "这里需要服务根地址，不是 system_stats 查询接口。",
        "请填写 ComfyUI 服务的基础地址；反向代理的合法子路径可以保留。",
        "Enter the service base URL, not the system_stats endpoint.",
        "Use the ComfyUI base URL. A valid reverse-proxy path prefix is supported.",
    ),
    "key": (
        "密钥格式不正确。",
        "请检查复制内容，不要包含换行或控制字符。",
        "The API key format is invalid.",
        "Check the copied value for line breaks or control characters.",
    ),
    "ok": (
        "ComfyUI 查询接口连接成功。",
        "仅确认服务 API 可访问；请在 ComfyUI 中单独运行所选工作流，确认节点与模型齐全后再生成。",
        "The ComfyUI status API is reachable.",
        "This only checks API access. Run your selected workflow in ComfyUI to verify its nodes and models before generating.",
    ),
    "unexpected": (
        "服务器已响应，但未识别到 ComfyUI 状态数据。",
        "检查是否填成了网站首页、登录页或其他模型 API；反代需要将 /system_stats 转发给 ComfyUI。",
        "The server responded, but its response was not recognized as ComfyUI status data.",
        "Check for a website, login page or another model API. The proxy must forward /system_stats to ComfyUI.",
    ),
    "timeout": (
        "连接或读取响应超时。",
        "检查服务是否启动、端口是否可访问，以及反代是否能访问上游；超时不能直接说明密钥错误。",
        "The connection or response timed out.",
        "Check the service, port and proxy-to-upstream connection. A timeout does not establish that the key is wrong.",
    ),
    "refused": (
        "目标端口拒绝连接。",
        "先启动 ComfyUI，再核对监听地址与端口。部署在容器或其他服务器时，127.0.0.1 指向运行本应用的环境。",
        "The destination port refused the connection.",
        "Start ComfyUI and check its listening address and port. In a container or remote deployment, 127.0.0.1 refers to the environment running this app.",
    ),
    "dns": (
        "无法解析服务域名。",
        "核对域名拼写、当前网络和 DNS；此时尚未完成密钥验证。",
        "The service hostname could not be resolved.",
        "Check the hostname, network and DNS. Authentication has not yet been verified.",
    ),
    "connection": (
        "未能建立服务连接。",
        "检查服务进程、地址、端口和防火墙；当前结果不足以判断是密钥还是反代配置问题。",
        "A connection to the service could not be established.",
        "Check the service, address, port and firewall. This result does not identify an API-key or proxy configuration fault.",
    ),
    "tls": (
        "HTTPS 证书或安全连接验证失败。",
        "核对证书有效期、域名和证书链；不要通过关闭证书验证来处理。",
        "HTTPS certificate or secure-connection verification failed.",
        "Check the certificate validity, hostname and certificate chain.",
    ),
    "auth": (
        "服务返回认证或访问权限错误。",
        "核对 ComfyUI 密钥、反代鉴权与访问规则；本测试和生成客户端均使用 Authorization: Bearer 认证。",
        "The service returned an authentication or access error.",
        "Check the ComfyUI key, proxy authentication and access rules. This test and the generation client use Authorization: Bearer.",
    ),
    "missing": (
        "服务未找到 /system_stats 接口。",
        "核对 ComfyUI 基础地址和反代路径；OpenAI 兼容的 /v1 接口不能直接替代原生 ComfyUI API。",
        "The /system_stats endpoint was not found.",
        "Check the ComfyUI base URL and proxy path. An OpenAI-compatible /v1 endpoint cannot directly replace the native ComfyUI API.",
    ),
    "upstream": (
        "服务返回网关或暂时不可用错误。",
        "检查反代上游地址、ComfyUI 运行状态和服务端日志；仅凭此状态码不能确认具体根因。",
        "The service returned a gateway or temporary-unavailability error.",
        "Check the proxy upstream, ComfyUI service and server logs. This status alone does not establish the root cause.",
    ),
    "redirect": (
        "服务返回重定向，尚未验证 ComfyUI 接口。",
        "请填写可直接访问的 ComfyUI 基础地址，并检查反代是否跳转到登录页面。",
        "The service redirected the request; its ComfyUI API has not been verified.",
        "Use a directly accessible ComfyUI base URL and check whether the proxy redirects to a login page.",
    ),
    "http": (
        "服务返回非成功状态。",
        "根据下方 HTTP 状态检查服务端日志与反代设置；测试不会自动重试或创建生成任务。",
        "The service returned an unsuccessful status.",
        "Use the HTTP status below to check server logs and proxy settings. The test does not retry or create generation tasks.",
    ),
    "unknown": (
        "连接测试未完成。",
        "请检查服务地址和运行状态；未获得足够信息，无法判定具体原因。",
        "The connection test could not be completed.",
        "Check the service URL and status. There is not enough information to identify a cause.",
    ),
}


@dataclass(frozen=True)
class ConnectionResult:
    """只包含固定诊断码与 HTTP 状态，不保留地址、密钥或响应正文。"""

    code: str
    http_status: int | None = None

    @property
    def level(self) -> str:
        if self.code == "ok":
            return "success"
        return "warning" if self.code in {"unexpected", "redirect"} else "error"

    def text(self, zh: bool = True) -> tuple[str, str]:
        """中英文界面共享诊断分类，避免翻译导致业务分支差异。"""
        messages = MESSAGES[self.code]
        return messages[:2] if zh else messages[2:]


def validate_base_url(value: str) -> tuple[str, str | None]:
    """校验基础地址但不猜测或重写域名；合法反代路径原样保留。"""
    base_url = value.strip()
    if not base_url:
        return "", "empty"
    try:
        parsed = urlsplit(base_url)
        invalid = (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in base_url
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base_url)
        )
        # 访问 port 属性会检查非数字端口和越界端口，避免请求阶段才报错。
        parsed.port
        if invalid:
            return "", "url"
    except ValueError:
        return "", "url"
    if parsed.path.rstrip("/").endswith("/system_stats"):
        return "", "endpoint"
    return base_url.rstrip("/"), None


def _connection_error_code(error: BaseException) -> str:
    """根据异常类型/系统错误码分类，不解析或展示可能含凭据的错误文本。"""
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        # Requests 读取响应体时会将 urllib3 的读取超时包装成 ConnectionError；
        # 沿异常链识别真实类型，不能因此误报为连接尚未建立，也不解析错误正文。
        if isinstance(current, (requests.exceptions.Timeout, Urllib3TimeoutError, TimeoutError)):
            return "timeout"
        if isinstance(current, socket.gaierror):
            return "dns"
        if isinstance(current, OSError) and current.errno in {errno.ECONNREFUSED, 10061}:
            return "refused"
        pending.extend(item for item in current.args if isinstance(item, BaseException))
        pending.extend(
            item
            for item in (current.__cause__, current.__context__, getattr(current, "reason", None))
            if isinstance(item, BaseException)
        )
    return "connection"


def check_comfyui_connection(base_url: str, api_key: str = "") -> ConnectionResult:
    """以当前表单值执行一次只读查询，认证方式与 ComfyKit 客户端保持一致。"""
    base_url, error_code = validate_base_url(base_url)
    if error_code:
        return ConnectionResult(error_code)
    if any(ord(char) < 32 or ord(char) == 127 for char in api_key):
        return ConnectionResult("key")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with requests.Session() as session:
            # ComfyKit 的 aiohttp 会话默认不使用环境代理；测试也避免 localhost
            # 被系统 HTTP_PROXY 转发。这里不修改环境变量或其他模型的代理配置。
            session.trust_env = False
            with session.get(
                f"{base_url}/system_stats",
                headers=headers,
                timeout=(5, 10),
                allow_redirects=False,
            ) as response:
                status = response.status_code
                if status == 200:
                    try:
                        payload = response.json()
                    except ValueError:
                        return ConnectionResult("unexpected", status)
                    valid = isinstance(payload, dict) and isinstance(payload.get("system"), dict)
                    return ConnectionResult("ok" if valid else "unexpected", status)
                if status in {401, 403}:
                    return ConnectionResult("auth", status)
                if status == 404:
                    return ConnectionResult("missing", status)
                if status in {502, 503, 504}:
                    return ConnectionResult("upstream", status)
                if 300 <= status < 400:
                    return ConnectionResult("redirect", status)
                return ConnectionResult("http", status)
    except requests.exceptions.Timeout:
        return ConnectionResult("timeout")
    except requests.exceptions.SSLError:
        return ConnectionResult("tls")
    except requests.exceptions.ConnectionError as error:
        return ConnectionResult(_connection_error_code(error))
    except Exception:
        return ConnectionResult("unknown")
