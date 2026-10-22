"""OpenAI Chat Completions 图像输入适配器，也支持相同协议的中转服务。

协议：https://developers.openai.com/api/docs/guides/images-vision
只发送有界图像与文本，不向 Chat Completions 传入原始视频。
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlsplit, urlunsplit

import requests

MAX_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT = (10, 120)


def normalize_base_url(value: str, default: str) -> str:
    """保留反代前缀，根域名补默认路径，不回显可能含凭据的错误 URL。"""
    value = (value or default).strip().rstrip("/")
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"https", "http"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or any(char.isspace() for char in value)):
            raise ValueError
        _ = parts.port
        path = parts.path or urlsplit(default).path
        if path.endswith(("/chat/completions", "/models", "/generation")):
            raise ValueError
        return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))
    except ValueError:
        raise ValueError("请填写有效的 HTTP(S) 服务基础地址，不要包含接口路径、密钥或查询参数。") from None


class OpenAIVisionClient:
    """请求只使用传入的提供商凭据与显式代理，禁用环境代理和自动重定向。"""

    label = "OpenAI/兼容视觉服务"
    default_url = "https://api.openai.com/v1"
    endpoint = "/chat/completions"

    def __init__(self, api_key: str, base_url: str = "", local_proxy: str = ""):
        if not isinstance(api_key, str) or not api_key.strip():
            raise RuntimeError(f"{self.label} API Key 未配置。")
        self.api_key = api_key.strip()
        self.base_url = normalize_base_url(base_url, self.default_url)
        self.local_proxy = (local_proxy or "").strip()
        if self.local_proxy:
            try:
                proxy = urlsplit(self.local_proxy)
                if proxy.scheme not in {"http", "https"} or not proxy.hostname:
                    raise ValueError
                _ = proxy.port
            except ValueError:
                raise ValueError("视觉服务代理地址无效，请填写 HTTP(S) 代理地址。") from None

    def _payload(self, model: str, content: list[dict]) -> dict:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "max_completion_tokens": 4096,
        }
        # GPT-6.1 Sol / Astra 不支持 none；素材描述使用 low，避免默认 medium
        # 消耗全部预算。仅匹配已核实型号/日期快照，不猜测中转自定义别名能力。
        # https://developers.openai.com/api/docs/guides/latest-model
        supported_reasoning_models = ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna")
        if any(model == known or self._is_dated_snapshot(model, known)
               for known in supported_reasoning_models):
            payload["reasoning_effort"] = "low"
        # 有推理时不能带 temperature/top_p/logprobs；整个视觉适配器均不发送它们。
        return payload

    @staticmethod
    def _is_dated_snapshot(model: str, known: str) -> bool:
        """只识别精确 YYYY-MM-DD 后缀，不能把 relay 自定义模型当成官方型号。"""
        from datetime import date

        if not model.startswith(known + "-"):
            return False
        suffix = model[len(known) + 1:]
        if len(suffix) != 10:
            return False
        try:
            date.fromisoformat(suffix)
            return True
        except ValueError:
            return False

    def _extract(self, data: dict) -> str:
        choice = data["choices"][0]
        # 推理 Token 也占输出预算；非空但被截断的说明不能当作完整素材分析。
        # DashScope 原生返回经子类转为同一 choices 结构，也执行此保护。
        if choice.get("finish_reason") == "length":
            raise RuntimeError(f"{self.label} 输出达到长度上限，素材描述可能不完整，请减少采样帧数或缩短提示后重试。")
        content = choice["message"].get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(item["text"] for item in content
                             if isinstance(item, dict) and isinstance(item.get("text"), str)).strip()
        return ""

    def chat(self, content: list[dict], model: str) -> str:
        """限制响应体与读取时间；异常不包含请求头、响应正文或 Base64。"""
        try:
            with requests.Session() as session:
                session.trust_env = False
                if self.local_proxy:
                    session.proxies.update({"http": self.local_proxy, "https": self.local_proxy})
                with session.post(
                    self.base_url + self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=self._payload(model, content), timeout=REQUEST_TIMEOUT,
                    allow_redirects=False, stream=True,
                ) as response:
                    status = response.status_code
                    if not 200 <= status < 300:
                        hint = {
                            400: "请确认模型支持图像输入以及当前接口参数。",
                            401: "请检查该提供商的 API Key。",
                            403: "请检查该密钥的模型访问权限。",
                            404: "请检查 Base URL 和视觉模型名称。",
                            429: "请求过多或额度不足，请检查额度后重试。",
                        }.get(status, "请检查服务状态及接口地址后重试。")
                        raise RuntimeError(f"{self.label} 返回 HTTP {status}。{hint}")
                    chunks, total = [], 0
                    deadline = time.monotonic() + REQUEST_TIMEOUT[1]
                    for chunk in response.iter_content(chunk_size=16384):
                        total += len(chunk)
                        if total > MAX_RESPONSE_BYTES:
                            raise RuntimeError(f"{self.label} 响应过大，已停止读取。")
                        if time.monotonic() > deadline:
                            raise RuntimeError(f"{self.label} 读取响应超时。")
                        chunks.append(chunk)
                    data = json.loads(b"".join(chunks))
                    text = self._extract(data)
                    if not text:
                        raise RuntimeError(f"{self.label} 未返回可用描述，请确认模型具备图像输入能力。")
                    return text
        except requests.Timeout:
            raise RuntimeError(f"{self.label} 连接或读取超时，请检查地址、代理和服务状态。") from None
        except requests.RequestException:
            raise RuntimeError(f"{self.label} 网络连接失败，请检查地址、代理和服务状态。") from None
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise RuntimeError(f"{self.label} 返回格式不兼容，请确认使用视觉 Chat Completions 接口。") from None
