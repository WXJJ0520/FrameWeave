"""素材创作页模型目录修复：内存配置、模拟目录接口，不上传或生成素材。"""

import copy
import runpy
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
_fixture = runpy.run_path(str(ROOT / "tests/asset_creation_flow_test.py"))["AssetCreationFlowTest"]
_fixture_setup = _fixture.setUp


class AssetCatalogUITest(unittest.TestCase):
    app = _fixture.app

    def setUp(self):
        _fixture_setup(self)
        self.vlm_models = []
        self.manager.set_llm_config("fake-text-key", "https://text.invalid/v1", "text-only")
        self.manager.set_api_provider_config("common", {"local_proxy": "http://127.0.0.1:7890"})
        self.manager.set_api_provider_config("openai", {
            "api_key": "fake-vision-key", "base_url": "https://vision.invalid/custom/v1",
            "use_proxy": True, "model_catalog": {},
        })
        catalog_factory = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["catalog_test_module"]
        self.catalog = catalog_factory()
        self.catalog.load_provider_model_ids = Mock(return_value=["codex-auto-review", "test-vision"])
        imports = patch.dict(sys.modules, {"pixelle_video.services.api_services.model_catalog": self.catalog})
        imports.start()
        self.addCleanup(imports.stop)
        service_class = runpy.run_path(str(ROOT / "pixelle_video/services/api_asset_analysis.py"))["APIAssetAnalysisService"]
        # 每次渲染读取新配置，模拟正式页面由配置摘要重建服务后的目录行为。
        self.core.api_asset_analysis.list_models = Mock(side_effect=lambda **kwargs: service_class(
            self.manager.config.model_dump(),
        ).list_models(**kwargs))
        self.load_and_save = runpy.run_path(str(ROOT / "web/pipelines/asset_catalog.py"))["load_and_save_asset_catalog"]

    def preview(self, app):
        app.session_state["_test_ready_assets"] = True
        app.button(key="creation_flow_custom_media_next").click().run()
        app.button(key="creation_flow_custom_media_next").click().run()
        self.assertFalse(app.exception)

    def test_configured_provider_without_catalog_can_return_from_preview_preserving_draft(self):
        app = self.app()
        self.assertEqual(app.selectbox(key="asset_analysis_provider").value, "openai")
        self.assertFalse(app.button(key="asset_load_analysis_models").disabled)
        app.text_input(key="asset_video_title").set_value("保留标题")
        app.text_area(key="asset_intent").set_value("保留创作方向")
        app.slider(key="asset_duration").set_value(90)
        app.session_state["creation_upload_custom_media"] = {"directory": "not-accessed", "files": {"fake": "asset.png"}}
        self.preview(app)
        self.assertEqual(app.session_state["_asset_flow_params"]["analysis_vlm_status"], "missing_catalog")
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assertTrue(any("视觉服务已配置，但缺少" in item.value for item in app.info))
        app.button(key="asset_return_to_analysis").click().run()
        self.assertEqual(app.session_state["creation_flow_custom_media_step"], 1)
        self.assertEqual(app.text_input(key="asset_video_title").value, "保留标题")
        self.assertEqual(app.text_area(key="asset_intent").value, "保留创作方向")
        self.assertEqual(app.slider(key="asset_duration").value, 90)
        self.assertEqual(app.session_state["creation_upload_custom_media"]["files"], {"fake": "asset.png"})
        self.catalog.load_provider_model_ids.assert_not_called()
        self.media.assert_not_awaited()
        self.core.tts.assert_not_awaited()

    def test_explicit_load_saves_only_vision_catalog_reruns_and_requires_model_selection(self):
        before = copy.deepcopy(self.manager.config.model_dump())
        app = self.app()
        app.button(key="asset_load_analysis_models").click().run()
        self.assertFalse(app.exception)
        self.catalog.load_provider_model_ids.assert_called_once()
        provider, passed_config, network = self.catalog.load_provider_model_ids.call_args.args
        self.assertEqual(provider, "openai")
        self.assertEqual(passed_config["api_key"], "fake-vision-key")
        self.assertEqual(passed_config["base_url"], "https://vision.invalid/custom/v1")
        self.assertEqual(network["local_proxy"], "http://127.0.0.1:7890")
        self.assertEqual(len(self.manager.saved), 1)
        after = copy.deepcopy(self.manager.config.model_dump())
        snapshot = after["api_providers"]["openai"]["model_catalog"]
        self.assertEqual(snapshot["models"], ["codex-auto-review", "test-vision"])
        after["api_providers"]["openai"]["model_catalog"] = {}
        self.assertEqual(after, before)
        self.assertIsNone(app.selectbox(key="asset_analysis_workflow").value)
        self.preview(app)
        self.assertEqual(app.session_state["_asset_flow_params"]["analysis_vlm_status"], "not_selected")
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        app.button(key="asset_return_to_analysis").click().run()
        app.selectbox(key="asset_analysis_workflow").set_value("test-vision - API OpenAI / Compatible").run()
        app.button(key="creation_flow_custom_media_next").click().run()
        self.assertFalse(app.button(key="asset_generate").disabled)
        self.assertEqual(app.session_state["_asset_flow_params"]["analysis_vlm_model"], "test-vision")
        self.media.assert_not_awaited()
        self.core.tts.assert_not_awaited()

    def test_load_failure_is_redacted_and_cannot_enable_generation(self):
        self.catalog.load_provider_model_ids.side_effect = RuntimeError("upstream echoed fake-vision-key")
        app = self.app()
        app.button(key="asset_load_analysis_models").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertNotIn("fake-vision-key", " ".join(item.value for item in app.error))
        self.assertEqual(self.manager.saved, [])
        self.preview(app)
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assertEqual(self.manager.get_api_providers_config()["openai"]["model_catalog"], {})

    def test_empty_response_is_saved_but_reported_as_zero_and_remains_blocked(self):
        self.catalog.load_provider_model_ids.return_value = []
        app = self.app()
        app.button(key="asset_load_analysis_models").click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any("0 个模型" in item.value for item in app.warning))
        self.assertEqual(len(self.manager.saved), 1)
        self.preview(app)
        self.assertTrue(app.button(key="asset_generate_disabled").disabled)
        self.assertEqual(self.manager.get_api_providers_config()["openai"]["model_catalog"]["models"], [])

    def test_connection_change_during_query_rejects_stale_result(self):
        def changed(*_):
            self.manager.set_api_provider_config("openai", {"base_url": "https://changed.invalid/v1"})
            return ["stale-model"]

        self.catalog.load_provider_model_ids.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "配置已变化"):
            self.load_and_save(self.manager, "openai")
        self.assertEqual(self.manager.saved, [])
        self.assertEqual(self.manager.get_api_providers_config()["openai"]["model_catalog"], {})

    def test_non_connection_edits_survive_partial_save_and_save_failure_rolls_back(self):
        def edited(*_):
            self.manager.set_api_provider_config("openai", {"vision_models": ["unsaved-legacy-name"]})
            self.manager.set_api_provider_config("muse", {"base_url": "https://other-edit.invalid/v1"})
            return ["new-vision"]

        self.catalog.load_provider_model_ids.side_effect = edited
        first = self.load_and_save(self.manager, "openai")
        self.assertEqual(self.manager.get_api_providers_config()["openai"]["vision_models"], ["unsaved-legacy-name"])
        self.assertEqual(self.manager.get_api_providers_config()["muse"]["base_url"], "https://other-edit.invalid/v1")
        self.manager.save = Mock(side_effect=OSError("private-path fake-vision-key"))
        with self.assertRaisesRegex(RuntimeError, "未能保存") as error:
            self.load_and_save(self.manager, "openai")
        self.assertNotIn("fake-vision-key", str(error.exception))
        self.assertEqual(self.manager.get_api_providers_config()["openai"]["model_catalog"], first)

# 不暴露复用的 unittest 类，避免 pytest 额外收集步骤往返测试。
del _fixture


if __name__ == "__main__":
    unittest.main()
