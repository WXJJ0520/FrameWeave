"""文本模型候选升级的协议回归；用 SDK 替身检查请求，不读取配置或请求云服务。"""

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
LLMService = runpy.run_path(str(ROOT / "pixelle_video/services/llm_service.py"))["LLMService"]


class ScriptAnswer(BaseModel):
    title: str


class LLMModelCompatibilityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = LLMService({})
        self.service._get_config_value = Mock(return_value="")
        self.create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content="测试文案"),
        )]))
        self.client = SimpleNamespace(
            base_url="https://unit-test.invalid/v1",
            chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)),
        )
        self.service._create_client = Mock(return_value=self.client)

    async def test_gpt6_text_uses_reasoning_compatible_parameters_and_preserves_model(self):
        for model in ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "openai/gpt-6.1-sol"):
            with self.subTest(model=model):
                self.assertEqual(await self.service("脚本", model=model, max_tokens=3456, top_p=0.6, logprobs=True), "测试文案")
                params = self.create.call_args.kwargs
                self.assertEqual(params["model"], model)
                self.assertEqual(params["max_completion_tokens"], 3456)
                self.assertEqual(params["reasoning_effort"], "low")
                for forbidden in ("max_tokens", "temperature", "top_p", "logprobs"):
                    self.assertNotIn(forbidden, params)

    async def test_structured_output_uses_same_compatible_request(self):
        self.create.return_value.choices[0].message.content = '{"title":"完整脚本"}'
        result = await self.service("按结构写", model="gpt-6.1-sol", response_type=ScriptAnswer)
        self.assertEqual(result.title, "完整脚本")
        self.assertIn("max_completion_tokens", self.create.call_args.kwargs)
        self.assertNotIn("temperature", self.create.call_args.kwargs)

    async def test_existing_relay_and_legacy_models_keep_parameters(self):
        for model in ("qwen-plus", "gpt-4.1", "relay-my-model", "gpt-6-unverified"):
            with self.subTest(model=model):
                await self.service("旧模型", model=model, temperature=0.3, max_tokens=1000)
                params = self.create.call_args.kwargs
                self.assertEqual(params["temperature"], 0.3)
                self.assertEqual(params["max_tokens"], 1000)
                self.assertNotIn("reasoning_effort", params)

    async def test_supported_none_and_explicit_output_budget_are_preserved(self):
        await self.service("轻任务", model="gpt-6-luna", reasoning_effort="none", temperature=0.2, max_completion_tokens=6000)
        params = self.create.call_args.kwargs
        self.assertEqual(params["reasoning_effort"], "none")
        self.assertEqual(params["temperature"], 0.2)
        self.assertEqual(params["max_completion_tokens"], 6000)
        self.assertNotIn("max_tokens", params)

    async def test_unsupported_effort_and_tools_stop_before_network(self):
        for extra in ({"reasoning_effort": "none"}, {"reasoning_effort": "minimal"}, {"tools": [{"type": "function"}]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                await self.service("不发请求", model="gpt-6.1-sol", **extra)
        self.create.assert_not_awaited()

    async def test_truncated_plain_and_structured_output_is_not_success(self):
        self.create.return_value.choices[0].finish_reason = "length"
        for response_type in (None, ScriptAnswer):
            with self.subTest(response_type=response_type), self.assertRaisesRegex(ValueError, "长度上限"):
                await self.service("不完整文案", model="gpt-6.1-sol", response_type=response_type)

    async def test_unselected_model_does_not_silently_call_legacy_default(self):
        with self.assertRaisesRegex(ValueError, "选择文本模型"):
            await self.service("没有配置")
        self.create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
