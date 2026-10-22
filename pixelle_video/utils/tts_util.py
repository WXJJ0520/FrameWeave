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
Edge TTS Utility - 本地合成模式使用的微软在线语音服务。

TTSService 调用本模块完成语音合成；网络协议与证书验证由 edge-tts SDK 处理。
本模块负责并发限制、有界重试及不暴露服务令牌的中文错误提示。
"""

import asyncio
import random
import edge_tts as edge_tts_sdk
from edge_tts.exceptions import NoAudioReceived
from loguru import logger
from aiohttp import WSServerHandshakeError, ClientResponseError


# 仅对限流、服务端错误和无音频响应进行有界重试；认证拒绝交给用户处理。
_RETRY_COUNT = 5           # Default retry count
_RETRY_BASE_DELAY = 1.0     # Base retry delay in seconds (for exponential backoff)
_MAX_RETRY_DELAY = 10.0     # Maximum retry delay in seconds

# Rate limiting configuration
_REQUEST_DELAY = 0.5        # Minimum delay before each request (seconds)
_MAX_CONCURRENT_REQUESTS = 3  # Maximum concurrent requests

# Global semaphore for rate limiting (created per event loop)
_request_semaphore = None
_semaphore_loop = None


def _safe_request_error(operation: str, status: int | None = None) -> str:
    """只使用固定说明与状态码，避免 SDK 异常中的完整令牌 URL 进入日志。"""
    if status in (401, 403):
        return (
            f"Edge TTS {operation}被服务拒绝（HTTP {status}），已停止重试。"
            "请检查网络访问与 edge-tts 版本后重试；此服务不需要填写 API 密钥。"
        )
    if status == 429:
        return f"Edge TTS {operation}受到限流（HTTP 429），重试仍未成功，请稍后再试。"
    if status is not None and 500 <= status < 600:
        return f"Edge TTS {operation}暂时不可用（HTTP {status}），重试仍未成功，请稍后再试。"
    if status is not None:
        return f"Edge TTS {operation}失败（HTTP {status}），已停止重试，请检查网络与请求设置。"
    return f"Edge TTS {operation}失败，请检查网络连接和语音设置后重试。"


def _get_request_semaphore():
    """Get or create request semaphore for current event loop"""
    global _request_semaphore, _semaphore_loop
    
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop
        return asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
    
    # If semaphore doesn't exist or belongs to different loop, create new one
    if _request_semaphore is None or _semaphore_loop != current_loop:
        _request_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        _semaphore_loop = current_loop
    
    return _request_semaphore


async def edge_tts(
    text: str,
    voice: str = "[Chinese] zh-CN Yunjian",
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
    output_path: str = None,
    retry_count: int = _RETRY_COUNT,
    retry_base_delay: float = _RETRY_BASE_DELAY,
) -> bytes:
    """
    Convert text to speech using Microsoft Edge TTS
    
    This service is free and requires no API key.
    Supports 400+ voices across 100+ languages.
    
    Returns audio data as bytes (MP3 format).
    
    Includes bounded retry with exponential backoff and jitter for HTTP 429,
    server errors and responses without audio. Permanent rejections are not retried.
    Also includes concurrent request limiting and rate limiting.
    
    Args:
        text: Text to convert to speech
        voice: Voice ID (e.g., [Chinese] zh-CN Yunjian, [English] en-US Jenny)
        rate: Speech rate (e.g., +0%, +50%, -20%)
        volume: Speech volume (e.g., +0%, +50%, -20%)
        pitch: Speech pitch (e.g., +0Hz, +10Hz, -5Hz)
        output_path: Optional output file path to save audio
        retry_count: Number of retries on failure (default: 5)
        retry_base_delay: Base delay for exponential backoff (default: 1.0s)
    
    Returns:
        Audio data as bytes (MP3 format)
    
    Popular Chinese voices:
    - [Chinese] zh-CN Yunjian (male, default)
    - [Chinese] zh-CN Xiaoxiao (female)
    - [Chinese] zh-CN Yunxi (male)
    - [Chinese] zh-CN Xiaoyi (female)
    
    Popular English voices:
    - [English] en-US Jenny (female)
    - [English] en-US Guy (male)
    - [English] en-GB Sonia (female, British)
    
    Example:
        audio_bytes = await edge_tts(
            text="你好，世界！",
            voice="[Chinese] zh-CN Yunjian",
            rate="+20%"
        )
    """
    logger.debug(f"Calling Edge TTS with voice: {voice}, rate: {rate}, retry_count: {retry_count}")
    
    # Use semaphore to limit concurrent requests
    request_semaphore = _get_request_semaphore()
    async with request_semaphore:
        # Add a small random delay before each request to avoid rate limiting
        pre_delay = _REQUEST_DELAY + random.uniform(0, 0.3)
        logger.debug(f"Waiting {pre_delay:.2f}s before request (rate limiting)")
        await asyncio.sleep(pre_delay)
        
        last_error = None
        
        # Retry loop
        for attempt in range(retry_count + 1):  # +1 because first attempt is not a retry
            if attempt > 0:
                # Exponential backoff with jitter
                # delay = base * (2 ^ attempt) + random jitter
                exponential_delay = retry_base_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, retry_base_delay)
                retry_delay = min(exponential_delay + jitter, _MAX_RETRY_DELAY)
                
                logger.info(f"🔄 Retrying Edge TTS (attempt {attempt + 1}/{retry_count + 1}) after {retry_delay:.2f}s delay...")
                await asyncio.sleep(retry_delay)
            
            try:
                # SDK 自行校验证书并处理协议层 403 校时重试，不覆盖其 TLS 设置。
                communicate = edge_tts_sdk.Communicate(
                    text=text,
                    voice=voice,
                    rate=rate,
                    volume=volume,
                    pitch=pitch,
                )
                
                # Collect audio chunks
                audio_chunks = []
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_chunks.append(chunk["data"])
                
                audio_data = b"".join(audio_chunks)
                if not audio_data:
                    # 流正常结束却没有音频同样视为失败，避免写出空 MP3 并继续视频流程。
                    raise NoAudioReceived("Edge TTS 未返回音频数据。")
                
                if attempt > 0:
                    logger.success(f"✅ Retry succeeded on attempt {attempt + 1}")
                
                logger.info(f"Generated {len(audio_data)} bytes of audio data")
                
                # Save to file if output_path is provided
                if output_path:
                    with open(output_path, "wb") as f:
                        f.write(audio_data)
                    logger.info(f"Audio saved to: {output_path}")
                
                return audio_data
            
            except (WSServerHandshakeError, ClientResponseError) as exc:
                status = exc.status if isinstance(exc.status, int) else None
                message = _safe_request_error("语音合成", status)
                retryable = status == 429 or (status is not None and 500 <= status < 600)
                last_error = RuntimeError(message)
                if not retryable or attempt >= retry_count:
                    logger.error(message)
                    # 不保留 SDK 异常链，防止上层 logger.exception 展示含令牌的 URL。
                    raise RuntimeError(message) from None
                logger.warning(f"Edge TTS 暂时请求失败（HTTP {status}），将进行第 {attempt + 1} 次重试。")
            
            except NoAudioReceived:
                # 无音频可能是临时服务异常，可重试；达到上限后给出固定安全提示。
                message = "Edge TTS 未返回可用音频，重试仍未成功，请检查网络与所选音色后再试。"
                last_error = RuntimeError(message)
                logger.warning(f"⚠️  Edge TTS NoAudioReceived (attempt {attempt + 1}/{retry_count + 1})")
                logger.debug(f"This is usually a temporary Microsoft service issue. Will retry with longer delay...")
                
                if attempt >= retry_count:
                    logger.error(message)
                    raise RuntimeError(message) from None
                # Add extra delay for NoAudioReceived errors
                await asyncio.sleep(2.0)
            
            except Exception:
                # 其它异常不盲重试，且不记录可能带 URL、令牌或代理凭据的原文。
                message = _safe_request_error("语音合成")
                logger.error(message)
                raise RuntimeError(message) from None
        
        # Should not reach here, but just in case
        if last_error:
            raise last_error from None
        else:
            raise RuntimeError("Edge TTS 语音合成未完成，请检查重试次数与网络设置。")


def get_audio_duration(audio_path: str) -> float:
    """
    Get audio file duration in seconds
    
    Args:
        audio_path: Path to audio file
    
    Returns:
        Duration in seconds
    """
    try:
        # Try using ffmpeg-python
        import ffmpeg
        probe = ffmpeg.probe(audio_path)
        duration = float(probe['format']['duration'])
        return duration
    except Exception:
        logger.warning("无法读取音频实际时长，暂按文件大小估算。")
        # Fallback: estimate based on file size (very rough)
        import os
        file_size = os.path.getsize(audio_path)
        # Assume ~16kbps for MP3, so 2KB per second
        estimated_duration = file_size / 2000
        return max(1.0, estimated_duration)  # At least 1 second


async def list_voices(locale: str = None, retry_count: int = _RETRY_COUNT, retry_base_delay: float = _RETRY_BASE_DELAY) -> list[str]:
    """
    List all available voices for Edge TTS
    
    Returns a list of voice IDs (ShortName).
    Optionally filter by locale.
    
    Includes automatic retry mechanism with exponential backoff and jitter
    to handle network errors and rate limiting.
    
    Args:
        locale: Filter by locale (e.g., zh-CN, en-US, ja-JP)
        retry_count: Number of retries on failure (default: 5)
        retry_base_delay: Base delay for exponential backoff (default: 1.0s)
    
    Returns:
        List of voice IDs
    
    Example:
        # List all voices
        voices = await list_voices()
        # Returns: ['[Chinese] zh-CN Yunjian', '[Chinese] zh-CN Xiaoxiao', ...]
        
        # List Chinese voices only
        voices = await list_voices(locale="zh-CN")
        # Returns: ['[Chinese] zh-CN Yunjian', '[Chinese] zh-CN Xiaoxiao', ...]
    """
    logger.debug(f"Fetching Edge TTS voices, locale filter: {locale}, retry_count: {retry_count}")
    
    # Use semaphore to limit concurrent requests
    request_semaphore = _get_request_semaphore()
    async with request_semaphore:
        # Add a small random delay before each request to avoid rate limiting
        pre_delay = _REQUEST_DELAY + random.uniform(0, 0.3)
        logger.debug(f"Waiting {pre_delay:.2f}s before request (rate limiting)")
        await asyncio.sleep(pre_delay)
        
        last_error = None
        
        # Retry loop
        for attempt in range(retry_count + 1):
            if attempt > 0:
                # Exponential backoff with jitter
                exponential_delay = retry_base_delay * (2 ** (attempt - 1))
                jitter = random.uniform(0, retry_base_delay)
                retry_delay = min(exponential_delay + jitter, _MAX_RETRY_DELAY)
                
                logger.info(f"🔄 Retrying list voices (attempt {attempt + 1}/{retry_count + 1}) after {retry_delay:.2f}s delay...")
                await asyncio.sleep(retry_delay)
            
            try:
                # Get all voices (edge-tts handles SSL internally)
                voices = await edge_tts_sdk.list_voices()
                
                # Filter by locale if specified
                if locale:
                    voices = [v for v in voices if v["Locale"].startswith(locale)]
                
                # Extract voice IDs (ShortName)
                voice_ids = [voice["ShortName"] for voice in voices]
                
                if attempt > 0:
                    logger.success(f"✅ Retry succeeded on attempt {attempt + 1}")
                
                logger.info(f"Found {len(voice_ids)} voices" + (f" for locale '{locale}'" if locale else ""))
                return voice_ids
            
            except (WSServerHandshakeError, ClientResponseError) as exc:
                status = exc.status if isinstance(exc.status, int) else None
                message = _safe_request_error("音色列表查询", status)
                retryable = status == 429 or (status is not None and 500 <= status < 600)
                last_error = RuntimeError(message)
                if not retryable or attempt >= retry_count:
                    logger.error(message)
                    raise RuntimeError(message) from None
                logger.warning(f"Edge TTS 音色查询暂时失败（HTTP {status}），将进行第 {attempt + 1} 次重试。")
            
            except Exception:
                message = _safe_request_error("音色列表查询")
                logger.error(message)
                raise RuntimeError(message) from None
        
        # Should not reach here, but just in case
        if last_error:
            raise last_error from None
        else:
            raise RuntimeError("Edge TTS 音色列表查询未完成，请检查重试次数与网络设置。")

