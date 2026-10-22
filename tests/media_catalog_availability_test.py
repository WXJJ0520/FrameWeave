"""媒体下拉只读取当前配置目录与已接入协议的交集，不查询网络或用户配置。"""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pixelle_video.services.api_media import APIProviderMediaService
from pixelle_video.services.api_services.model_catalog import make_model_catalog
from web.pipelines.api_workflows import list_api_media_workflows


class MediaCatalogAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.providers = {"common": {"local_proxy": "http://127.0.0.1:9090"}}
        # 服务对象保留旧构造参数，列表必须读取管理器的当前配置，而非过期快照。
        self.service = APIProviderMediaService({"api_providers": {"openai": {"api_key": "stale-test-only"}}})
        manager = SimpleNamespace(get_api_providers_config=lambda: copy.deepcopy(self.providers))
        self.enterContext(patch("pixelle_video.services.api_media.config_manager", manager))
        self.enterContext(patch("requests.sessions.Session.request", side_effect=AssertionError("展示模型下拉不得联网")))

    def configure(self, provider, model_ids, *, source="api", **values):
        """仅使用不可用的测试地址与假凭据生成目录快照，不调用加载接口。"""
        cfg = {"base_url": f"https://{provider}.example.invalid/v1", "use_proxy": False, **values}
        if provider == "kling":
            # 可灵适配器自行拼接 /v1，目录指纹也必须使用相同的服务根地址。
            cfg["base_url"] = f"https://{provider}.example.invalid"
            cfg.update(access_key="test-access", secret_key="test-secret")
        else:
            cfg["api_key"] = f"test-{provider}-key"
        cfg["model_catalog"] = make_model_catalog(
            provider, cfg, self.providers["common"], model_ids, source=source,
        )
        self.providers[provider] = cfg
        return cfg

    def keys(self):
        return [workflow["key"] for workflow in self.service.list_available_workflows()]

    def test_empty_or_unloaded_catalog_never_exposes_internal_presets(self):
        self.assertEqual(self.keys(), [])
        self.providers["openai"] = {"api_key": "test-openai-key", "base_url": "https://example.invalid/v1"}
        self.assertEqual(self.keys(), [])
        # 内部生成协议目录保持完整，避免破坏已保存任务和后端解析。
        self.assertEqual(len(self.service.list_workflows()), 27)
        self.assertEqual(self.service.resolve_workflow("api/openai/gpt-image-2")["model"], "gpt-image-2")

    def test_loaded_catalog_only_exposes_registered_intersection(self):
        self.configure("openai", ["gpt-image-2", "gpt-6.1-sol", "brand-new-video"])
        self.configure("xai", ["grok-imagine-video-1.5-lite", "future-grok-video"])
        self.assertEqual(set(self.keys()), {"api/openai/gpt-image-2", "api/xai/grok-imagine-video-1.5-lite"})
        self.assertNotIn("api/xai/grok-imagine-video", self.keys())

    def test_unknown_ids_do_not_gain_media_capabilities_from_their_name(self):
        self.configure("xai", ["grok-future-video", "grok-imagine-video-custom"])
        self.configure("openai", ["custom-gpt-image", "gpt-6.1-sol"])
        self.assertEqual(self.keys(), [])

    def test_manual_catalog_is_explicit_and_ark_maps_to_both_adapters(self):
        self.configure("ark", ["doubao-seedream-5-0-260128", "doubao-seedance-2-0-260128", "gpt-image-2"], source="manual")
        self.assertEqual(set(self.keys()), {
            "api/seedream/doubao-seedream-5-0-260128", "api/seedance/doubao-seedance-2-0-260128",
        })

    def test_same_name_from_another_provider_does_not_authorize_the_original_provider(self):
        self.configure("openai", ["wan2.7-t2v", "grok-imagine-video", "gpt-image-2"])
        self.assertEqual(self.keys(), ["api/openai/gpt-image-2"])
        self.configure("dashscope", ["wan2.7-t2v"])
        self.assertEqual(set(self.keys()), {"api/openai/gpt-image-2", "api/dashscope/wan2.7-t2v"})

    def test_changed_credentials_address_or_proxy_invalidates_catalog(self):
        changes = (
            {"api_key": "different-test-key"},
            {"base_url": "https://different.example.invalid/v1"},
            {"use_proxy": True},
        )
        for change in changes:
            with self.subTest(change=change):
                cfg = self.configure("xai", ["grok-imagine-video"])
                self.assertEqual(len(self.keys()), 1)
                cfg.update(change)
                self.assertEqual(self.keys(), [])
        self.configure("xai", ["grok-imagine-video"], use_proxy=True)
        self.providers["common"]["local_proxy"] = "http://127.0.0.1:9091"
        self.assertEqual(self.keys(), [])

    def test_removed_credentials_hide_models_even_if_a_snapshot_remains(self):
        cfg = self.configure("muse", ["muse-video"], source="manual")
        self.assertEqual(self.keys(), ["api/muse/muse-video"])
        cfg["api_key"] = ""
        self.assertEqual(self.keys(), [])
        cfg = self.configure("kling", ["kling-v3"], source="manual")
        self.assertEqual(self.keys(), ["api/kling/kling-v3"])
        cfg["secret_key"] = ""
        self.assertEqual(self.keys(), [])

    def test_current_saved_directory_replaces_old_options_on_the_same_service_instance(self):
        self.configure("xai", ["grok-imagine-video"])
        self.assertEqual(self.keys(), ["api/xai/grok-imagine-video"])
        self.configure("xai", ["grok-imagine-video-1.5"])
        self.assertEqual(self.keys(), ["api/xai/grok-imagine-video-1.5"])

    def test_web_list_uses_available_catalog_and_keeps_capability_filtering(self):
        self.configure("dashscope", ["wan2.7-i2v", "wan2.7-videoedit", "wan2.7-image"])
        core = SimpleNamespace(api_media=self.service)
        images = list_api_media_workflows(core, "image")
        videos = list_api_media_workflows(core, "video", ["first_frame_i2v"], verified_only=True)
        self.assertEqual([item["model"] for item in images], ["wan2.7-image"])
        self.assertEqual([item["model"] for item in videos], ["wan2.7-i2v"])

    def test_web_missing_availability_interface_does_not_fall_back_to_static_registry(self):
        registry = Mock(return_value=[{"key": "api/xai/grok-imagine-video", "media_type": "video"}])
        core = SimpleNamespace(api_media=SimpleNamespace(list_workflows=registry))
        self.assertEqual(list_api_media_workflows(core, "video"), [])
        registry.assert_not_called()
