"""自建 muse2api 视频适配器：异步提交、轮询以及原子下载。

协议来源：czg86389-hub/muse2api 的 app.py（VideoRequest、create_video、get_video）。
这是用户自建反代的接口，不是 Meta 官方 Model API。时长和比例为上游生成请求，
不能保证实际视频严格达到该规格；分辨率、音频开关没有可验证的控制协议。
"""

import base64
import binascii
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests

from .config import Config


class MuseVideoClient:
    """调用用户指定的 muse2api 服务，不重试创建任务以避免重复生成。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        local_proxy: Optional[str] = None,
        poll_interval: float = 3,
        max_polls: int = 300,
        poll_timeout: float = 900,
        request_timeout: float = 30,
    ) -> None:
        self.api_key = (Config.MUSE_API_KEY if api_key is None else api_key).strip()
        configured_base = Config.MUSE_BASE_URL if base_url is None else base_url
        self.base_url = self._normalize_base_url(configured_base)
        if not self.api_key:
            raise ValueError("请填写自建 muse2api 的 API Key。")
        if any(char in self.api_key for char in "\r\n"):
            raise ValueError("muse2api API Key 不能包含换行符。")
        if poll_interval < 0 or max_polls < 1 or poll_timeout <= 0 or request_timeout <= 0:
            raise ValueError("muse2api 轮询次数和超时必须为正数，间隔不能为负数。")
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self.poll_timeout = poll_timeout
        self.request_timeout = request_timeout
        self.proxies = {"http": local_proxy, "https": local_proxy} if local_proxy else {}
        self._session = requests.Session()
        self._download_session = requests.Session()
        # 禁用环境代理和 netrc 隐式鉴权；下载会话永远不携带 API Key。
        self._session.trust_env = False
        self._download_session.trust_env = False

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """允许填写服务根地址或 /v1，拒绝把密钥放到 URL 中。"""
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("请填写自建 muse2api 服务地址，例如 https://muse.example.com/v1。")
        value = base_url.strip().rstrip("/")
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.netloc
                or parts.username or parts.password or parts.query or parts.fragment):
            raise ValueError("muse2api 地址必须是 HTTP(S) 服务地址，不能含账号、查询参数或片段。")
        path = parts.path.rstrip("/")
        if path.endswith("/v1"):
            path = path[:-3]
        return urlunsplit((parts.scheme, parts.netloc, path + "/v1", "", ""))

    @staticmethod
    def _reference_image(image_path: str) -> str:
        """将本地首帧转成 Data URL；远程 URL 交给反代下载，不携带鉴权头。"""
        value = str(image_path)
        if value.startswith("data:"):
            header, separator, encoded = value.partition(",")
            if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
                raise ValueError("Muse 首帧图片必须是有效的图片 Base64 Data URL。")
            try:
                if not base64.b64decode(encoded, validate=True):
                    raise ValueError("空图片")
            except (ValueError, binascii.Error):
                raise ValueError("Muse 首帧图片 Base64 内容无效。") from None
            return value
        if value.startswith(("http://", "https://")):
            parts = urlsplit(value)
            if not parts.netloc or parts.username or parts.password:
                raise ValueError("Muse 首帧图片 URL 无效。")
            return value
        path = Path(value)
        if not path.is_file():
            raise FileNotFoundError("Muse 首帧图片文件不存在。")
        mime = mimetypes.guess_type(path.name)[0] or ""
        if not mime.startswith("image/"):
            raise ValueError("Muse 首帧文件必须是图片。")
        content = path.read_bytes()
        if not content:
            raise ValueError("Muse 首帧图片文件为空。")
        return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

    def _request_json(self, method: str, url: str, *, payload=None, timeout=None) -> dict:
        """仅调用固定服务上的 API，禁止重定向带走鉴权，也不回显原始错误体。"""
        response = self._session.request(
            method, url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout or self.request_timeout,
            proxies=self.proxies,
            allow_redirects=False,
        )
        try:
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError("muse2api 暂时不可用", response=response)
            if response.status_code in {401, 403}:
                raise RuntimeError(f"muse2api 鉴权失败（HTTP {response.status_code}），请检查服务地址与 API Key。")
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"muse2api 请求失败（HTTP {response.status_code}）。")
            try:
                result = response.json()
            except ValueError:
                raise RuntimeError("muse2api 返回了非 JSON 响应，请检查服务地址和反向代理。") from None
            if not isinstance(result, dict):
                raise RuntimeError("muse2api 返回了无法识别的任务响应。")
            return result
        finally:
            response.close()

    def _task_label(self, task_id: str) -> str:
        """任务 ID 用于定位超时任务；过滤控制字符并避免意外回显密钥。"""
        return re.sub(r"[\x00-\x1f\x7f]", "", task_id.replace(self.api_key, "[已隐藏]"))[:160]

    def _poll_task(self, task_id: str) -> str:
        """查询网络失败仅重试 GET，超时保留任务 ID，绝不重新 POST。"""
        deadline = time.monotonic() + self.poll_timeout
        label = self._task_label(task_id)
        endpoint = f"{self.base_url}/videos/{quote(task_id, safe='')}"
        for _ in range(self.max_polls):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                data = self._request_json("GET", endpoint, timeout=min(self.request_timeout, remaining))
            except requests.RequestException:
                # 连接故障、限流与 5xx 均不代表生成失败，继续查询原任务。
                data = {"status": "processing"}
            except RuntimeError as exc:
                raise RuntimeError(f"{exc} 任务 ID：{label}；未重复提交。") from None
            status = str(data.get("status", "")).lower()
            if status in {"completed", "succeeded", "success", "done"}:
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                video = data.get("video") if isinstance(data.get("video"), dict) else {}
                remote = data.get("url") or result.get("url") or video.get("url")
                if not isinstance(remote, str) or not remote.strip():
                    raise RuntimeError(f"Muse 任务已完成，但没有返回视频下载地址。任务 ID：{label}")
                resolved = urljoin(self.base_url + "/", remote.strip())
                parts = urlsplit(resolved)
                if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
                    raise RuntimeError(f"Muse 返回的视频下载地址无效。任务 ID：{label}")
                return resolved
            if status in {"failed", "error", "cancelled", "canceled", "expired"}:
                # 反代的 error 可能包含账号诊断和上游凭据，不直接放进用户日志。
                raise RuntimeError(f"Muse 视频生成失败（{status}）。任务 ID：{label}；请在 muse2api 后台查看原因。")
            if status not in {"queued", "pending", "processing", "running", "in_progress"}:
                raise RuntimeError(f"Muse 返回了无法识别的任务状态。任务 ID：{label}；未重复提交。")
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(self.poll_interval, remaining))
        raise TimeoutError(f"等待 Muse 视频超时。任务 ID：{label}；服务端任务可能仍在运行，未自动重新生成。")

    @staticmethod
    def _video_header_valid(header: bytes) -> bool:
        """识别常见 MP4/MOV、WebM 和 AVI，防止将封面或错误网页保存成视频。"""
        return (len(header) >= 12 and header[4:8] in {b"ftyp", b"moov", b"mdat"}
                or header.startswith(b"\x1a\x45\xdf\xa3")
                or header.startswith(b"RIFF") and header[8:12] == b"AVI ")

    def _download_video(self, video_url: str, save_path: str) -> None:
        """下载到同目录临时文件，完整验证后原子替换；失败不会破坏已有成片。"""
        destination = Path(save_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            # muse2api 的 /v1/media 无鉴权。独立会话对同域和跨域均不发送 Key。
            with self._download_session.get(
                video_url, stream=True, timeout=self.request_timeout,
                proxies=self.proxies, allow_redirects=True,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f"视频下载失败（HTTP {response.status_code}）。")
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type and not (content_type.startswith("video/") or content_type == "application/octet-stream"):
                    raise RuntimeError("下载响应不是视频，请检查 muse2api 的媒体地址配置。")
                total = 0
                header = b""
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False,
                ) as output:
                    temporary = Path(output.name)
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            if len(header) < 32:
                                header += chunk[:32 - len(header)]
                            output.write(chunk)
                            total += len(chunk)
                expected = response.headers.get("Content-Length", "")
                if not total or (expected.isdigit() and int(expected) != total):
                    raise RuntimeError("视频下载不完整，请从原任务重试下载。")
                if not self._video_header_valid(header):
                    raise RuntimeError("下载内容不是受支持的视频文件，未写入成片。")
                os.replace(temporary, destination)
                temporary = None
        except requests.RequestException:
            raise RuntimeError("视频下载连接失败，生成结果仍保留在 muse2api 服务端。") from None
        except OSError:
            raise RuntimeError("视频保存失败，请检查输出目录权限和磁盘空间。") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def generate_video(
        self,
        prompt: str,
        image_path: Optional[str],
        save_path: str,
        model: str = "muse-video",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        resolution: Optional[str] = None,
        generate_audio: Optional[bool] = None,
    ) -> str:
        """生成文生/首帧图生视频，保存本地成片并返回远程 URL。"""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Muse 视频提示词不能为空。")
        if model != "muse-video":
            raise ValueError("muse2api 视频模型只支持 muse-video。")
        if type(duration) is not int or duration not in {5, 6, 8, 10}:
            raise ValueError("Muse 视频时长请求支持 5、6、8、10 秒；实际时长以生成结果为准。")
        if aspect_ratio not in {"16:9", "9:16"}:
            raise ValueError("Muse 视频画幅请求支持 16:9 和 9:16。")
        if resolution is not None or generate_audio is not None:
            raise ValueError("muse2api 当前接入不支持可验证的分辨率或音频开关，请使用默认输出。")
        if not save_path:
            raise ValueError("请指定 Muse 视频输出文件路径。")
        payload = {"model": model, "prompt": prompt.strip(), "duration": duration, "size": aspect_ratio}
        if image_path:
            payload["reference_image"] = self._reference_image(image_path)
        try:
            # 一次调用只创建一次；连接中断时无法判定上游是否已接收，禁止自动补发。
            data = self._request_json("POST", f"{self.base_url}/videos", payload=payload)
        except requests.RequestException:
            raise RuntimeError("Muse 视频提交未确认，未自动重试。请先检查 muse2api 后台是否已创建任务。") from None
        task_id = data.get("id") or data.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise RuntimeError("Muse 未返回有效任务 ID，未自动重试；请检查 muse2api 后台。")
        video_url = self._poll_task(task_id)
        try:
            self._download_video(video_url, save_path)
        except RuntimeError as exc:
            raise RuntimeError(f"{exc} 任务 ID：{self._task_label(task_id)}；未重复生成。") from None
        return video_url
