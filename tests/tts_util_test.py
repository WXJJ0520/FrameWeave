"""Edge TTS 重试和脱敏测试：独立加载模块，仅运行本地 mock，不请求微软服务。"""

import importlib.util
import tempfile
import traceback
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import ClientResponseError, WSServerHandshakeError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "tts_util_isolated_test", ROOT / "pixelle_video/utils/tts_util.py"
)
tts_util = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tts_util)
PRIVATE_TOKEN = "test-private-edge-token-never-log"


def http_error(status, websocket=False):
    """异常刻意携带令牌 URL，用于验证日志和抛出异常均不泄漏它。"""
    cls = WSServerHandshakeError if websocket else ClientResponseError
    request = types.SimpleNamespace(
        real_url=f"wss://speech.example.invalid/synthesize?Sec-MS-GEC={PRIVATE_TOKEN}"
    )
    return cls(request, (), status=status, message=f"upstream rejected {PRIVATE_TOKEN}")


class FakeCommunicate:
    def __init__(self, outcome):
        self.outcome = outcome

    async def stream(self):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        for item in self.outcome:
            yield item


class TTSUtilTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.logs = []
        sink = tts_util.logger.add(lambda message: self.logs.append(str(message)), level="DEBUG")
        self.addCleanup(tts_util.logger.remove, sink)
        sleep_patch = patch.object(tts_util.asyncio, "sleep", new=AsyncMock())
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "audio.mp3"

    def communicate(self, *outcomes):
        return patch.object(
            tts_util.edge_tts_sdk, "Communicate",
            side_effect=[FakeCommunicate(outcome) for outcome in outcomes],
        )

    def assert_safe_failure(self, exception):
        self.assertIsInstance(exception, RuntimeError)
        exposed = "\n".join(self.logs) + "".join(traceback.format_exception(exception))
        self.assertNotIn(PRIVATE_TOKEN, exposed)
        self.assertNotIn("wss://speech.example.invalid", exposed)
        self.assertNotIn("Sec-MS-GEC", exposed)

    async def test_permanent_http_failures_stop_after_one_sdk_call(self):
        """SDK 已处理协议层重试，外层遇到 401/403/400/404 不再重复请求。"""
        for status in (401, 403, 400, 404):
            with self.subTest(status=status):
                with self.communicate(http_error(status, websocket=True)) as constructor:
                    with self.assertRaises(RuntimeError) as caught:
                        await tts_util.edge_tts("测试", output_path=str(self.output), retry_count=5)
                constructor.assert_called_once()
                self.assertIn(f"HTTP {status}", str(caught.exception))
                self.assertIn("已停止重试", str(caught.exception))
                self.assert_safe_failure(caught.exception)
                self.assertFalse(self.output.exists())

    async def test_retryable_http_errors_then_success(self):
        """限流和服务端错误仍可有界重试，成功后保存完整音频。"""
        for status in (429, 500, 503):
            with self.subTest(status=status):
                with self.communicate(http_error(status), [{"type": "audio", "data": b"mp3-data"}]) as constructor:
                    audio = await tts_util.edge_tts("测试", output_path=str(self.output), retry_count=1)
                self.assertEqual(constructor.call_count, 2)
                self.assertEqual(audio, b"mp3-data")
                self.assertEqual(self.output.read_bytes(), b"mp3-data")
                self.assertNotIn(PRIVATE_TOKEN, "\n".join(self.logs))

    async def test_retry_exhaustion_is_safe_and_bounded(self):
        """持续服务端错误只执行配置的初次请求加重试次数。"""
        with self.communicate(http_error(503), http_error(503), http_error(503)) as constructor:
            with self.assertRaises(RuntimeError) as caught:
                await tts_util.edge_tts("测试", retry_count=2)
        self.assertEqual(constructor.call_count, 3)
        self.assert_safe_failure(caught.exception)

    async def test_empty_audio_is_failure_and_does_not_write_file(self):
        """空流及只有边界元数据的流均不可产生空 MP3。"""
        for stream in ([], [{"type": "WordBoundary", "text": "测试"}], [{"type": "audio", "data": b""}]):
            with self.subTest(stream=stream):
                with self.communicate(stream, stream) as constructor:
                    with self.assertRaises(RuntimeError) as caught:
                        await tts_util.edge_tts("测试", output_path=str(self.output), retry_count=1)
                self.assertEqual(constructor.call_count, 2)
                self.assertIn("未返回可用音频", str(caught.exception))
                self.assertFalse(self.output.exists())

    async def test_no_audio_exception_can_retry_then_succeed(self):
        """SDK 的 NoAudioReceived 同样可重试，且不回显其异常信息。"""
        no_audio = tts_util.NoAudioReceived(f"no audio {PRIVATE_TOKEN}")
        with self.communicate(no_audio, [{"type": "audio", "data": b"recovered"}]) as constructor:
            audio = await tts_util.edge_tts("测试", retry_count=1)
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual(audio, b"recovered")
        self.assertNotIn(PRIVATE_TOKEN, "\n".join(self.logs))

    async def test_unexpected_error_is_sanitized_without_retry(self):
        """未知网络或 SDK 错误不把原始地址传给页面与上层日志。"""
        with self.communicate(ValueError(f"failed URL https://example.invalid/?token={PRIVATE_TOKEN}")) as constructor:
            with self.assertRaises(RuntimeError) as caught:
                await tts_util.edge_tts("测试", retry_count=5)
        constructor.assert_called_once()
        self.assert_safe_failure(caught.exception)

    async def test_success_preserves_parameters_and_writes_bytes(self):
        """正常路径保留已有参数 API，忽略元数据并按顺序连接音频块。"""
        chunks = [
            {"type": "audio", "data": b"first-"},
            {"type": "WordBoundary", "text": "测试"},
            {"type": "audio", "data": b"second"},
        ]
        with self.communicate(chunks) as constructor:
            audio = await tts_util.edge_tts(
                "中文测试", voice="zh-CN-YunjianNeural", rate="+20%", volume="-10%", pitch="+5Hz",
                output_path=str(self.output),
            )
        constructor.assert_called_once_with(
            text="中文测试", voice="zh-CN-YunjianNeural", rate="+20%", volume="-10%", pitch="+5Hz"
        )
        self.assertEqual(audio, b"first-second")
        self.assertEqual(self.output.read_bytes(), audio)

    async def test_list_voices_permanent_error_is_safe_without_retry(self):
        """音色列表查询也必须在 403 后停止，不能泄漏 SDK 请求 URL。"""
        with patch.object(tts_util.edge_tts_sdk, "list_voices", new=AsyncMock(side_effect=http_error(403))) as query:
            with self.assertRaises(RuntimeError) as caught:
                await tts_util.list_voices(retry_count=5)
        query.assert_awaited_once()
        self.assertIn("音色列表查询", str(caught.exception))
        self.assert_safe_failure(caught.exception)

    async def test_list_voices_retries_transient_errors_and_filters_locale(self):
        """音色接口的临时错误可重试，成功后保持 locale 筛选行为。"""
        voices = [
            {"Locale": "zh-CN", "ShortName": "zh-CN-YunjianNeural"},
            {"Locale": "en-US", "ShortName": "en-US-JennyNeural"},
        ]
        for status in (429, 503):
            with self.subTest(status=status):
                with patch.object(tts_util.edge_tts_sdk, "list_voices", new=AsyncMock(side_effect=[http_error(status), voices])) as query:
                    found = await tts_util.list_voices(locale="zh", retry_count=1)
                self.assertEqual(query.await_count, 2)
                self.assertEqual(found, ["zh-CN-YunjianNeural"])
                self.assertNotIn(PRIVATE_TOKEN, "\n".join(self.logs))

    async def test_list_voices_unknown_error_is_safe(self):
        with patch.object(tts_util.edge_tts_sdk, "list_voices", new=AsyncMock(side_effect=RuntimeError(PRIVATE_TOKEN))) as query:
            with self.assertRaises(RuntimeError) as caught:
                await tts_util.list_voices(retry_count=5)
        query.assert_awaited_once()
        self.assert_safe_failure(caught.exception)

    async def test_upstream_logger_exception_cannot_reveal_sdk_token(self):
        """模拟页面使用 logger.exception，确认完整异常回溯也不会重现 SDK URL。"""
        with self.communicate(http_error(403)), patch.object(
            tts_util.edge_tts_sdk, "list_voices", new=AsyncMock(side_effect=http_error(403))
        ):
            for operation in (tts_util.edge_tts, tts_util.list_voices):
                try:
                    if operation is tts_util.edge_tts:
                        await operation("测试", retry_count=0)
                    else:
                        await operation(retry_count=0)
                except RuntimeError:
                    # 与现有页面的异常记录方式相同，包含完整安全异常回溯。
                    tts_util.logger.exception("页面捕获语音服务错误")
                else:
                    self.fail("Expected a safe RuntimeError")
        exposed = "\n".join(self.logs)
        self.assertIn("RuntimeError", exposed)
        self.assertNotIn(PRIVATE_TOKEN, exposed)
        self.assertNotIn("Sec-MS-GEC", exposed)
        self.assertNotIn("wss://speech.example.invalid", exposed)


if __name__ == "__main__":
    unittest.main()
