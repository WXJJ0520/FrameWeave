"""配置变更必须刷新服务快照；使用内存配置和核心替身，禁止读取真实凭据。"""

import asyncio
import copy
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, **attributes):
    """隔离动态导入，防止测试核心构造时触及实际配置与外部服务。"""
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    return result


class MemoryState(dict):
    """提供 Streamlit 会话状态需要的字典与属性访问。"""

    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value


class APISessionRefreshTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "api_providers": {"dashscope": {"api_key": "offline-test-key", "base_url": "https://test.invalid"}},
            "llm": {"api_key": "offline-llm-key", "base_url": "https://llm.invalid/v1", "model": "offline-model"},
            "comfyui": {"tts": {"local": {"voice": "zh-CN-YunjianNeural"}}},
        }
        self.state = MemoryState()
        self.created = []

        def create_core():
            # 快照内容与真实核心一致，但不读取文件、联网或启动浏览器。
            core = types.SimpleNamespace(
                config=copy.deepcopy(self.config), initialize=AsyncMock(), cleanup=AsyncMock(),
            )
            self.created.append(core)
            return core

        self.create_core = Mock(side_effect=create_core)
        manager = types.SimpleNamespace(config=types.SimpleNamespace(to_dict=lambda: copy.deepcopy(self.config)))
        modules = {
            "streamlit": module("streamlit", session_state=self.state),
            "web.i18n": module("web.i18n", set_language=lambda value: None),
            "web.utils.async_helpers": module("web.utils.async_helpers", run_async=asyncio.run),
            "pixelle_video.service": module("pixelle_video.service", PixelleVideoCore=self.create_core),
            "pixelle_video.config": module("pixelle_video.config", config_manager=manager),
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.get_core = runpy.run_path(str(ROOT / "web/state/session.py"))["get_pixelle_video"]

    def test_unchanged_config_reuses_initialized_core(self):
        first = self.get_core()
        self.assertIs(self.get_core(), first)
        self.create_core.assert_called_once()
        first.initialize.assert_awaited_once()
        first.cleanup.assert_not_awaited()

    def test_provider_change_recreates_core_with_new_snapshot(self):
        first = self.get_core()
        self.config["api_providers"]["dashscope"]["api_key"] = "offline-replacement-key"
        second = self.get_core()
        self.assertIsNot(second, first)
        first.cleanup.assert_awaited_once()
        second.initialize.assert_awaited_once()
        self.assertEqual(second.config["api_providers"], self.config["api_providers"])

    def test_llm_change_recreates_core(self):
        first = self.get_core()
        self.config["llm"]["model"] = "offline-next-model"
        second = self.get_core()
        self.assertIsNot(second, first)
        first.cleanup.assert_awaited_once()
        self.assertEqual(second.config["llm"]["model"], "offline-next-model")

    def test_saved_voice_change_still_recreates_core(self):
        first = self.get_core()
        self.config["comfyui"]["tts"]["local"]["voice"] = "zh-CN-XiaoxiaoNeural"
        second = self.get_core()
        self.assertIsNot(second, first)
        first.cleanup.assert_awaited_once()

    def test_mapping_order_does_not_trigger_recreation(self):
        first = self.get_core()
        self.config["llm"] = dict(reversed(list(self.config["llm"].items())))
        self.assertIs(self.get_core(), first)
        self.create_core.assert_called_once()

    def test_non_service_display_change_keeps_core(self):
        first = self.get_core()
        self.config["project_name"] = "离线测试展示名"
        self.assertIs(self.get_core(), first)
        first.cleanup.assert_not_awaited()
