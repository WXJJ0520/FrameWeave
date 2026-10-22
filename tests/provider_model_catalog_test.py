"""模型目录离线验收：显式读取当前配置，仅 GET，不探测或创建生成任务。"""

import copy
import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from pixelle_video.services.api_services import model_catalog


def response(data=None, status=200, raw=None):
    reply = requests.Response()
    reply.status_code = status
    reply._content = raw if raw is not None else json.dumps(data).encode("utf-8")
    reply._content_consumed = True
    return reply


class ProviderModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.__enter__.return_value = self.session
        patcher = patch.object(model_catalog.requests, "Session", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {"api_key": "fake-provider-key", "base_url": "https://relay.invalid/prefix/v1", "use_proxy": False}

    def test_openai_uses_only_current_config_and_keeps_all_model_types(self):
        self.session.get.return_value = response({"data": [
            {"id": "gpt-6.1-sol"}, {"id": "text-only-model"}, {"id": "gpt-image-2"},
            {"id": "gpt-6.1-sol"}, {"id": "org/vision-model"},
        ]})
        original = copy.deepcopy(self.config)
        result = model_catalog.load_provider_model_ids("openai", self.config, {"local_proxy": "http://unused.invalid:1234"})
        self.assertEqual(result, ["gpt-6.1-sol", "text-only-model", "gpt-image-2", "org/vision-model"])
        self.assertEqual(self.config, original)
        args, kwargs = self.session.get.call_args
        self.assertEqual(args[0], "https://relay.invalid/prefix/v1/models")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-provider-key")
        self.assertEqual(kwargs["proxies"], {})
        self.assertEqual(kwargs["timeout"], (10, 20))
        self.assertFalse(kwargs["allow_redirects"])
        self.assertFalse(self.session.trust_env)
        self.session.post.assert_not_called()

    def test_proxy_credentials_and_key_cannot_leak_as_model_ids(self):
        self.config["use_proxy"] = True
        self.session.get.return_value = response({"data": [
            {"id": "fake-provider-key"}, {"id": "fake-proxy-pass"}, {"id": "proxy-user"},
            {"id": "good-vision"}, {"id": "<script>alert(1)</script>"}, {"id": "x" * 161},
        ]})
        result = model_catalog.load_provider_model_ids(
            "openai", self.config, {"local_proxy": "http://proxy-user:fake-proxy-pass@127.0.0.1:7890"}
        )
        self.assertEqual(result, ["good-vision"])
        self.assertEqual(self.session.get.call_args.kwargs["proxies"]["https"], "http://proxy-user:fake-proxy-pass@127.0.0.1:7890")

    def test_llm_preserves_root_and_explicit_api_prefix(self):
        """目录地址与文本生成的 Base URL 一致，不为文本服务猜测 /v1。"""
        for base, expected in (
            ("https://text.invalid", "https://text.invalid/models"),
            ("https://text.invalid/", "https://text.invalid/models"),
            ("https://text.invalid/custom/v1", "https://text.invalid/custom/v1/models"),
        ):
            with self.subTest(base=base):
                self.session.get.return_value = response({"data": [{"id": "text-model"}]})
                result = model_catalog.load_provider_model_ids("llm", {**self.config, "base_url": base})
                self.assertEqual(result, ["text-model"])
                self.assertEqual(self.session.get.call_args.args[0], expected)
                self.assertIsNone(self.session.get.call_args.kwargs["params"])
                self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])
        self.session.post.assert_not_called()

    def test_dashscope_uses_native_pagination_without_changing_host(self):
        first = [{"model": f"qwen-{index}"} for index in range(100)]
        self.session.get.side_effect = [
            response({"success": True, "output": {"total": 101, "models": first}}),
            response({"success": True, "output": {"total": 101, "models": [{"model": "qwen-new"}]}}),
        ]
        config = {"api_key": "fake-dashscope-key", "base_url": "https://qwen.invalid/proxy/api/v1"}
        result = model_catalog.load_provider_model_ids("dashscope", config)
        self.assertEqual(len(result), 101)
        self.assertEqual(result[-1], "qwen-new")
        for index, call in enumerate(self.session.get.call_args_list, 1):
            self.assertEqual(call.args[0], "https://qwen.invalid/proxy/api/v1/models")
            self.assertEqual(call.kwargs["params"], {"page_no": index, "page_size": 100})
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer fake-dashscope-key")
        self.session.post.assert_not_called()

    def test_explicit_compatible_dashscope_url_uses_same_models_path(self):
        self.session.get.return_value = response({"data": [{"id": "qwen-vision"}]})
        result = model_catalog.load_provider_model_ids("dashscope", {
            "api_key": "fake-qwen-key", "base_url": "https://qwen.invalid/compatible-mode/v1",
        })
        self.assertEqual(result, ["qwen-vision"])
        self.assertEqual(self.session.get.call_args.args[0], "https://qwen.invalid/compatible-mode/v1/models")
        self.assertIsNone(self.session.get.call_args.kwargs["params"])

    def test_missing_or_invalid_config_never_reads_environment_or_sends_request(self):
        invalid = [
            ("unknown", self.config, {}), ("openai", {**self.config, "api_key": ""}, {}),
            ("openai", {**self.config, "api_key": "fake\nkey"}, {}),
            ("openai", {**self.config, "base_url": "https://fake-secret@relay.invalid/v1"}, {}),
            ("openai", {**self.config, "base_url": "https://relay.invalid/v1?key=fake-secret"}, {}),
            ("openai", {**self.config, "use_proxy": True}, {}),
            ("llm", {**self.config, "base_url": ""}, {}),
            ("llm", {**self.config, "base_url": "https://relay.invalid/v1/models"}, {}),
        ]
        for provider, config, network in invalid:
            with self.subTest(provider=provider, config=config), self.assertRaises(ValueError) as error:
                model_catalog.load_provider_model_ids(provider, config, network)
            self.assertNotIn("fake-secret", str(error.exception))
        self.session.get.assert_not_called()

    def test_http_errors_are_redacted_and_redirects_are_not_followed(self):
        for status in (301, 302, 400, 401, 403, 404, 405, 429, 500):
            with self.subTest(status=status):
                self.session.get.return_value = response({"error": "fake-provider-key"}, status=status)
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as error:
                    model_catalog.load_provider_model_ids("openai", self.config)
                self.assertNotIn("fake-provider-key", str(error.exception))
        self.assertEqual(self.session.get.call_count, 9)

    def test_invalid_oversized_and_business_error_responses_are_not_exposed(self):
        replies = [
            response(raw=b"not-json fake-provider-key"), response(raw=b"x" * (1024 * 1024 + 1)),
            response({"data": {}}), response({"data": [], "error": "fake-provider-key"}),
            response({"success": False, "message": "fake-provider-key"}),
        ]
        for reply in replies:
            with self.subTest(reply=reply):
                self.session.get.return_value = reply
                with self.assertRaises(RuntimeError) as error:
                    model_catalog.load_provider_model_ids("openai", self.config)
                self.assertNotIn("fake-provider-key", str(error.exception))

    def test_timeouts_do_not_expose_raw_request_or_secret(self):
        for exception in (requests.ReadTimeout("fake-provider-key"), requests.ConnectionError("fake-provider-key")):
            with self.subTest(exception=exception):
                self.session.get.side_effect = exception
                with self.assertRaises(RuntimeError) as error:
                    model_catalog.load_provider_model_ids("openai", self.config)
                self.assertNotIn("fake-provider-key", str(error.exception))

    def test_partial_or_unbounded_catalog_is_not_reported_as_complete(self):
        for reply in (
            response({"data": [{"id": "gpt-6.1-sol"}], "has_more": True}),
            response({"data": [{"id": f"model-{index}"} for index in range(1001)]}),
            response({"output": {"models": [{"model": "qwen"}], "total": 1001}}),
        ):
            with self.subTest(reply=reply):
                self.session.get.return_value = reply
                with self.assertRaises(RuntimeError):
                    model_catalog.load_provider_model_ids("dashscope", self.config)
        # 反代忽略页码、重复返回首页时停止，不能无界轮询。
        self.session.get.return_value = response({"output": {"models": [{"model": "qwen"}], "total": 10}})
        self.session.get.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "后续"):
            model_catalog.load_provider_model_ids("dashscope", self.config)
        self.assertEqual(self.session.get.call_count, 2)

    def test_stream_read_obeys_catalog_deadline(self):
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.status_code = 200
        reply.iter_content.return_value = [b'{"data":[]}']
        self.session.get.return_value = reply
        with patch.object(model_catalog.time, "monotonic", side_effect=[0, 0, 31]):
            with self.assertRaisesRegex(RuntimeError, "超时"):
                model_catalog.load_provider_model_ids("openai", self.config)

    def test_xai_specific_directory_then_same_service_fallback(self):
        self.session.get.return_value = response({"models": [{"id": "grok-imagine-video-new"}]})
        self.assertEqual(model_catalog.load_provider_model_ids("xai", self.config), ["grok-imagine-video-new"])
        self.assertEqual(self.session.get.call_args.args[0], "https://relay.invalid/prefix/v1/video-generation-models")
        for status in (404, 405):
            with self.subTest(status=status):
                self.session.get.reset_mock()
                self.session.get.side_effect = [response({}, status), response({"data": [{"id": "relay-video"}]})]
                self.assertEqual(model_catalog.load_provider_model_ids("xai", self.config), ["relay-video"])
                self.assertEqual([call.args[0] for call in self.session.get.call_args_list], [
                    "https://relay.invalid/prefix/v1/video-generation-models", "https://relay.invalid/prefix/v1/models",
                ])
        self.session.get.reset_mock()
        self.session.get.side_effect = [response({}, 401)]
        with self.assertRaisesRegex(RuntimeError, "401"):
            model_catalog.load_provider_model_ids("xai", self.config)
        self.assertEqual(self.session.get.call_count, 1)

    def test_muse_uses_configured_instance_and_unverified_providers_never_request(self):
        self.session.get.return_value = response({"data": [{"id": "muse-video"}]})
        self.assertEqual(model_catalog.load_provider_model_ids("muse", {**self.config, "base_url": "https://muse.invalid/custom"}), ["muse-video"])
        self.assertEqual(self.session.get.call_args.args[0], "https://muse.invalid/custom/v1/models")
        self.session.get.reset_mock()
        for provider in ("ark", "kling"):
            with self.subTest(provider=provider), self.assertRaisesRegex(ValueError, "暂未接入"):
                model_catalog.load_provider_model_ids(provider, self.config)
        self.session.get.assert_not_called()


class ModelCatalogSnapshotTests(unittest.TestCase):
    """以虚构凭据验证目录绑定；这些纯函数不能发请求或读取全局配置。"""

    def setUp(self):
        self.config = {"api_key": "fake-key", "base_url": "https://relay.invalid/v1", "use_proxy": False}
        self.network = {"local_proxy": "http://127.0.0.1:7890"}

    def bind(self, provider="openai", models=None, source="api"):
        self.config["model_catalog"] = model_catalog.make_model_catalog(
            provider, self.config, self.network, models if models is not None else ["only-api-returned-model"], source,
        )

    def test_missing_directory_has_no_static_or_legacy_custom_fallback(self):
        self.config.update({"model": "gpt-6.1-sol", "vision_models": ["old-custom-vision"]})
        with patch.object(model_catalog.requests, "Session") as session:
            self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config, self.network), [])
            session.assert_not_called()
        self.bind()
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config, self.network), ["only-api-returned-model"])

    def test_snapshot_tracks_only_endpoint_credentials_and_enabled_proxy(self):
        self.bind()
        self.config.update({"model": "different-selection", "vision_models": ["different-custom"]})
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config, {"local_proxy": "http://unused.invalid:9000"}), ["only-api-returned-model"])
        for field, value in (("api_key", "changed-key"), ("base_url", "https://other.invalid/v1"), ("use_proxy", True)):
            with self.subTest(field=field):
                changed = {**self.config, field: value}
                self.assertEqual(model_catalog.get_configured_model_ids("openai", changed, self.network), [])
        self.config["use_proxy"] = True
        self.bind()
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config, {"local_proxy": "http://127.0.0.1:7891"}), [])
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config, self.network), ["only-api-returned-model"])

    def test_base_normalization_and_provider_isolation(self):
        self.bind()
        normalized = {**self.config, "base_url": "https://RELAY.INVALID:443/v1/", "api_key": " fake-key "}
        self.assertEqual(model_catalog.get_configured_model_ids("openai", normalized, self.network), ["only-api-returned-model"])
        self.assertEqual(model_catalog.get_configured_model_ids("llm", self.config, self.network), [])
        self.assertEqual(model_catalog.get_configured_model_ids("xai", self.config, self.network), [])
        self.bind(provider="llm")
        self.assertEqual(model_catalog.get_configured_model_ids("llm", self.config, self.network), ["only-api-returned-model"])

    def test_access_secret_are_both_bound_and_not_stored_in_snapshot(self):
        config = {"base_url": "https://kling.invalid", "access_key": "fake-access", "secret_key": "fake-secret"}
        catalog = model_catalog.make_model_catalog("kling", config, {}, ["provided-kling-id"], source="manual")
        config["model_catalog"] = catalog
        self.assertEqual(model_catalog.get_configured_model_ids("kling", config), ["provided-kling-id"])
        for field in ("access_key", "secret_key"):
            self.assertEqual(model_catalog.get_configured_model_ids("kling", {**config, field: "changed"}), [])
        serialized = json.dumps(catalog)
        self.assertNotIn("fake-access", serialized)
        self.assertNotIn("fake-secret", serialized)
        self.assertEqual(catalog["source"], "manual")

    def test_llm_root_and_v1_catalogs_are_not_interchangeable(self):
        """即使同域同密钥，文本接口的不同基础路径也必须重新加载目录。"""
        for base, changed in (
            ("https://text.invalid", "https://text.invalid/v1"),
            ("https://text.invalid/v1", "https://text.invalid"),
        ):
            with self.subTest(base=base):
                cfg = {**self.config, "base_url": base}
                cfg["model_catalog"] = model_catalog.make_model_catalog("llm", cfg, {}, ["text-model"])
                self.assertEqual(model_catalog.get_configured_model_ids("llm", cfg), ["text-model"])
                self.assertEqual(model_catalog.get_configured_model_ids("llm", {**cfg, "base_url": base + "/"}), ["text-model"])
                self.assertEqual(model_catalog.get_configured_model_ids("llm", {**cfg, "base_url": changed}), [])

    def test_empty_malformed_and_invalid_source_snapshots_are_safe(self):
        self.bind(models=[])
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config), [])
        for catalog in (None, [], {"fingerprint": "wrong", "models": ["wrong-model"]}):
            self.assertEqual(model_catalog.get_configured_model_ids("openai", {**self.config, "model_catalog": catalog}), [])
        with self.assertRaises(ValueError):
            model_catalog.make_model_catalog("openai", {**self.config, "api_key": ""}, {}, ["model"])
        self.assertEqual(model_catalog.catalog_fingerprint("openai", {**self.config, "api_key": ""}), "")
        with self.assertRaises(ValueError):
            model_catalog.make_model_catalog("openai", self.config, {}, ["model"], source="preset")

    def test_models_are_deduplicated_and_secret_echoes_removed(self):
        self.bind(models=["new-model", "new-model", " fake-key ", "org/another-model", "<script>"])
        self.assertEqual(model_catalog.get_configured_model_ids("openai", self.config), ["new-model", "org/another-model"])

    def test_schema_roundtrip_preserves_snapshots_for_all_config_types(self):
        from pixelle_video.config.schema import (
            AccessSecretProviderConfig,
            APIKeyProviderConfig,
            LLMConfig,
        )

        self.bind()
        catalog = self.config["model_catalog"]
        for schema in (APIKeyProviderConfig, AccessSecretProviderConfig, LLMConfig):
            with self.subTest(schema=schema):
                self.assertEqual(schema().model_catalog, {})
                self.assertEqual(schema.model_validate({"model_catalog": catalog}).model_dump()["model_catalog"], catalog)


if __name__ == "__main__":
    unittest.main()
