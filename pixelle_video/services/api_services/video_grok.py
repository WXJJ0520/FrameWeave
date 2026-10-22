"""xAI Grok Imagine 文生视频、图生视频适配器。

协议来源：https://docs.x.ai/developers/model-capabilities/video/generation
采用一次提交、限时轮询、原子下载，防止重复提交产生额外费用。
"""

import base64
import binascii
import io
import logging
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from PIL import Image

logger = logging.getLogger(__name__)

GROK_VIDEO_MODELS = frozenset({
    "grok-imagine-video", "grok-imagine-video-1.5", "grok-imagine-video-1.5-lite",
})
ASPECT_RATIOS = frozenset({"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "5:2"})


class GrokVideoClient:
    """仅使用独立 xAI 密钥，不读取或复用其它平台的配置。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        local_proxy: Optional[str] = None,
        *,
        poll_interval: float = 5,
        poll_timeout: float = 600,
        request_timeout: float = 120,
        download_timeout: float = 600,
    ) -> None:
        raw_key = api_key or os.getenv("XAI_API_KEY", "")
        # 复制密钥时混入换行会导致请求头异常，应在发起请求前明确拒绝。
        if not isinstance(raw_key, str) or "\r" in raw_key or "\n" in raw_key:
            raise ValueError("Grok API Key 必须是单行文本，请删除密钥中的换行")
        self.api_key = raw_key.strip()
        self.base_url = (base_url or os.getenv("XAI_BASE_URL") or "https://api.x.ai/v1").strip().rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Grok Base URL 必须是 HTTP 或 HTTPS 接口地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Grok Base URL 不能包含账号、密码、查询参数或锚点")
        if not parsed.path:
            self.base_url += "/v1"
        for name, value in {
            "poll_interval": poll_interval, "poll_timeout": poll_timeout,
            "request_timeout": request_timeout, "download_timeout": download_timeout,
        }.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是大于 0 的有限秒数")
        self.local_proxy = local_proxy
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.request_timeout = request_timeout
        self.download_timeout = download_timeout
        # requests 默认不重试；不要给创建任务的 POST 添加自动重试。
        self._session = requests.Session()
        self._session.trust_env = False
        # 独立下载会话不继承 Authorization、Cookie 或系统 .netrc 凭据。
        self._download_session = requests.Session()
        self._download_session.trust_env = False

    def _proxies(self) -> dict:
        return {"http": self.local_proxy, "https": self.local_proxy} if self.local_proxy else {}

    def _safe_text(self, value: object) -> str:
        """服务端错误可能回显凭据，展示前脱敏且限制长度。"""
        text = str(value)
        if self.api_key:
            text = text.replace(self.api_key, "[已隐藏密钥]")
        text = re.sub(r"(?i)Bearer\s+[^\s,;\"']+", "Bearer [已隐藏密钥]", text)
        text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        return text[:400]

    def _error_detail(self, data: dict) -> str:
        error = data.get("error")
        if isinstance(error, dict):
            return self._safe_text(f"{error.get('code', 'unknown')}: {error.get('message', '未知错误')}")
        return self._safe_text(error or "请检查模型权限、额度及接口配置")

    def _request_json(self, method: str, endpoint: str, *, payload=None, timeout=None) -> dict:
        """统一处理 HTTP / JSON 错误，避免异常输出请求头或完整响应。"""
        response = None
        try:
            response = self._session.request(
                method, f"{self.base_url}/{endpoint}",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload, timeout=timeout or self.request_timeout,
                proxies=self._proxies(), allow_redirects=False,
            )
            try:
                data = response.json()
            except ValueError:
                raise RuntimeError(f"Grok 接口返回非 JSON 数据（HTTP {response.status_code}）") from None
            if not isinstance(data, dict):
                raise RuntimeError("Grok 接口返回格式错误，期望 JSON 对象")
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Grok 接口 HTTP {response.status_code}：{self._error_detail(data)}")
            return data
        except requests.Timeout:
            suffix = "任务可能已在服务端创建，请先核对平台记录，避免重复提交" if method == "POST" else "本地等待已停止，云端任务可能仍在运行"
            raise TimeoutError(f"Grok 接口请求超时；{suffix}") from None
        except requests.RequestException:
            raise RuntimeError("Grok 接口网络连接失败，请检查地址和代理；本次未自动重新提交任务") from None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _image_data_uri(content: bytes) -> str:
        """按图片实际格式生成 data URI，避免扩展名与 MIME 不一致。"""
        try:
            with Image.open(io.BytesIO(content)) as image:
                mime = Image.MIME.get(image.format)
                image.verify()
        except (OSError, ValueError, SyntaxError):
            raise ValueError("Grok 首帧文件不是有效图片") from None
        if not mime or not mime.startswith("image/"):
            raise ValueError("Grok 首帧图片格式无法识别")
        return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

    @classmethod
    def _prepare_image(cls, image_path: str) -> str:
        """支持本地文件、公开图片 URL 和 base64 data URI。"""
        image_path = os.fspath(image_path)
        if image_path.startswith(("https://", "http://")):
            parsed = urlsplit(image_path)
            if not parsed.netloc or parsed.username or parsed.password:
                raise ValueError("Grok 首帧图片 URL 无效")
            return image_path
        if image_path.startswith("data:"):
            try:
                header, encoded = image_path.split(",", 1)
                if not header.startswith("data:image/") or not header.endswith(";base64"):
                    raise ValueError
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("Grok 首帧必须是有效的图片 base64 data URI") from None
            return cls._image_data_uri(content)
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError("Grok 首帧图片不存在，请重新选择图片")
        return cls._image_data_uri(path.read_bytes())

    def _resolve_video_url(self, value: str, *, relative_to: Optional[str] = None) -> str:
        """中转可返回相对内容地址；归一后仍只允许无用户凭据的 HTTP(S)。"""
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("Grok 任务完成但未返回视频 URL")
        value = value.strip()
        # 避免反斜杠和控制字符在 URL 解析器、HTTP 客户端之间产生不同解释。
        if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise RuntimeError("Grok 返回的视频 URL 无效")
        try:
            resolved = urljoin(relative_to or self.base_url + "/", value)
            parsed = urlsplit(resolved)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
                raise ValueError
            _ = parsed.port
        except ValueError:
            raise RuntimeError("Grok 返回的视频 URL 无效") from None
        # fragment 不参与 HTTP 请求；签名下载所需的查询参数必须原样保留。
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        """鉴权按协议、主机、有效端口三者判断同源，不能只比较域名。"""
        parsed = urlsplit(url)
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        return parsed.scheme.lower(), parsed.hostname.lower(), port

    def _poll_until_done(self, request_id: str) -> str:
        """用单调时钟限制总轮询时长，不重新创建已提交任务。"""
        deadline = time.monotonic() + self.poll_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Grok 视频生成等待超时；云端任务可能仍在运行，请先核对平台记录")
            data = self._request_json("GET", f"videos/{quote(request_id, safe='')}", timeout=min(30, remaining))
            status = data.get("status")
            if status == "done":
                video = data.get("video")
                if not isinstance(video, dict):
                    raise RuntimeError("Grok 任务完成但缺少视频信息")
                if video.get("respect_moderation") is False:
                    raise RuntimeError("Grok 视频未通过内容审核，请调整提示词或首帧图片")
                url = video.get("url")
                return self._resolve_video_url(url)
            if status in ("failed", "expired"):
                # 当前官方列出 failed；兼容服务返回 expired 时也应立即停止。
                raise RuntimeError(f"Grok 视频生成{'失败' if status == 'failed' else '已过期'}：{self._error_detail(data)}")
            if status != "pending":
                raise RuntimeError("Grok 接口返回未知任务状态，请检查接口是否兼容 xAI 视频协议")
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(self.poll_interval, remaining))

    def _open_video_download(self, video_url: str) -> requests.Response:
        """首个 API 同源内容请求可鉴权；重定向逐跳校验且一律不转发密钥。"""
        current_url = self._resolve_video_url(video_url)
        for redirect_count in range(6):
            headers = {}
            # 部分中转提供 /v1/videos/{id}/content，下载该受保护内容需要同一 API Key。
            # Bearer 仅放在首个同源请求头，绝不写入 Session 默认头或外部媒体请求。
            if redirect_count == 0 and self._origin(current_url) == self._origin(self.base_url):
                headers["Authorization"] = f"Bearer {self.api_key}"
            response = self._download_session.get(
                current_url, headers=headers, stream=True, timeout=self.download_timeout,
                proxies=self._proxies(), allow_redirects=False,
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            response.close()
            if redirect_count == 5:
                raise RuntimeError("Grok 视频下载重定向次数过多")
            if not location:
                raise RuntimeError("Grok 视频下载重定向缺少目标地址")
            # 即使跳回 API 源或降级为 HTTP，后续跳转也不能重新携带 Bearer。
            current_url = self._resolve_video_url(location, relative_to=current_url)
        raise RuntimeError("Grok 视频下载重定向次数过多")

    def _download_video(self, video_url: str, save_path: str) -> None:
        """完整下载后原子替换目标，失败时保留旧文件并清理临时文件。"""
        target = Path(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        response = None
        try:
            response = self._open_video_download(video_url)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Grok 视频下载失败（HTTP {response.status_code}）")
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type.startswith("text/") or "json" in content_type:
                raise RuntimeError("Grok 视频地址返回了错误页面，未保存为视频")
            with tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".part", dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                size = 0
                header = b""
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        output.write(chunk)
                        size += len(chunk)
                        if len(header) < 24:
                            header += chunk[:24 - len(header)]
            if not size:
                raise RuntimeError("Grok 返回的视频文件为空")
            # requests 会自动解压；只有未压缩响应才可直接比较字节数。
            encoding = response.headers.get("Content-Encoding", "").strip().lower()
            content_length = response.headers.get("Content-Length")
            if encoding in ("", "identity") and content_length is not None:
                try:
                    expected_size = int(content_length)
                except (TypeError, ValueError):
                    raise RuntimeError("Grok 视频下载响应中的 Content-Length 无效") from None
                if expected_size < 0 or expected_size != size:
                    raise RuntimeError("Grok 视频下载不完整，文件大小与 Content-Length 不一致")
            # 官方生成 MP4；校验 ftyp 容器头，拒绝伪装成二进制的错误页。
            box_size = int.from_bytes(header[:4], "big")
            if len(header) < 12 or header[4:8] != b"ftyp":
                raise RuntimeError("Grok 下载内容不是有效的 MP4 视频文件头")
            if box_size == 1:
                box_size = int.from_bytes(header[8:16], "big")
                valid_box_size = len(header) >= 24 and 24 <= box_size <= size
            else:
                valid_box_size = 16 <= box_size <= size
            if not valid_box_size:
                raise RuntimeError("Grok 下载的 MP4 文件头不完整")
            os.replace(temporary, target)
            logger.info("Grok 视频已下载完成")
        except requests.RequestException:
            raise RuntimeError("Grok 视频下载中断；云端生成可能已成功，请先核对平台记录") from None
        finally:
            if response is not None:
                response.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def resume_video(self, request_id: str, save_path: str) -> str:
        """只查询并下载已有任务，恢复失败预览时不会再次提交收费生成请求。"""
        if not self.api_key:
            raise ValueError("请在系统配置中填写 xAI / Grok API Key")
        if not isinstance(request_id, str) or not request_id.strip() or any(ord(char) < 32 for char in request_id):
            raise ValueError("请提供有效的 Grok 任务 ID")
        if not save_path or Path(save_path).is_dir():
            raise ValueError("请指定有效的视频保存文件路径")
        request_id = request_id.strip()
        try:
            video_url = self._poll_until_done(request_id)
            self._download_video(video_url, save_path)
        except (RuntimeError, OSError, ValueError) as error:
            # 任务一旦创建就可能计费，失败提示保留脱敏 ID，便于再次查询和恢复。
            message = f"{self._safe_text(error)}（Grok 任务 ID：{self._safe_text(request_id)}）"
            error_type = TimeoutError if isinstance(error, TimeoutError) else RuntimeError
            raise error_type(message) from None
        return video_url

    def generate_video(
        self,
        prompt: str,
        image_path: Optional[str],
        save_path: str,
        model: str = "grok-imagine-video",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        resolution: Optional[str] = "720p",
        generate_audio: Optional[bool] = None,
    ) -> str:
        """提交文生/图生任务、等待并保存视频，返回远端临时 URL。"""
        if not self.api_key:
            raise ValueError("请在系统配置中填写 xAI / Grok API Key")
        if model not in GROK_VIDEO_MODELS:
            raise ValueError("不支持的 Grok 视频模型，请选择 Grok Imagine Video 系列")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 1 <= duration <= 15:
            raise ValueError("Grok 视频时长必须是 1 至 15 秒的整数")
        # 统一路由器用 None 表示未选择分辨率，保持与界面默认值一致。
        if resolution is None:
            resolution = "720p"
        if resolution not in ("480p", "720p", "1080p"):
            raise ValueError("Grok 视频分辨率只能是 480p、720p 或 1080p")
        if model == "grok-imagine-video" and resolution == "1080p":
            raise ValueError("grok-imagine-video 最高支持 720p，请选择 1.5 系列使用 1080p")
        if not isinstance(prompt, str) or (not prompt.strip() and not image_path):
            raise ValueError("Grok 文生视频需要非空提示词")
        if generate_audio is not None and not isinstance(generate_audio, bool):
            raise ValueError("Grok generate_audio 必须为布尔值")
        if not save_path or Path(save_path).is_dir():
            raise ValueError("请指定有效的视频保存文件路径")
        payload = {"model": model, "duration": duration, "resolution": resolution}
        if prompt.strip():
            payload["prompt"] = prompt.strip()
        if image_path:
            # xAI 图生视频继承首帧比例，不发送会被服务端忽略的 aspect_ratio。
            payload["image"] = {"url": self._prepare_image(image_path)}
        else:
            if aspect_ratio not in ASPECT_RATIOS:
                raise ValueError("Grok 文生视频画幅比例不受支持")
            payload["aspect_ratio"] = aspect_ratio
        if generate_audio is not None:
            payload["generate_audio"] = generate_audio
        result = self._request_json("POST", "videos/generations", payload=payload)
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise RuntimeError("Grok 未返回任务 ID；请先核对平台记录，避免重复提交")
        return self.resume_video(request_id, save_path)
