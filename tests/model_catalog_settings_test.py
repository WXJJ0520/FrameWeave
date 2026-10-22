"""动态目录设置回归：真实控件、真实快照算法、内存配置，禁止实际接口调用。"""

import ast
import runpy
import sys
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
_fixture = runpy.run_path(str(ROOT / "tests/provider_settings_test.py"))["ProviderSettingsTest"]


class ModelCatalogSettingsTest(unittest.TestCase):
    _set_up = _fixture.setUp
    save = _fixture.save

    def setUp(self):
        self._set_up()
        self.catalog = sys.modules["pixelle_video.services.api_services.model_catalog"]
        self.load = Mock(return_value=["relay-new-vision-999", "gpt-6.1-sol"])
        load_patch = patch.object(self.catalog, "load_provider_model_ids", self.load)
        load_patch.start()
        self.addCleanup(load_patch.stop)
        network_patch = patch("requests.sessions.Session.request", side_effect=AssertionError("禁止真实网络"))
        self.network = network_patch.start()
        self.addCleanup(network_patch.stop)

    def tearDown(self):
        self.network.assert_not_called()

    def load_catalog(self, provider="openai"):
        key = "load_models_btn" if provider == "llm" else f"api_media_{provider}_load_models"
        self.app.button(key=key).click().run()
        self.assertFalse(self.app.exception)

    def fresh_app(self):
        script = f"import runpy\nrunpy.run_path({str(ROOT / 'web/components/settings.py')!r})['render_advanced_settings']()\n"
        self.app = AppTest.from_string(script).run()
        self.assertFalse(self.app.exception)

    def creator_models(self, config):
        # 运行真正的素材模型目录消费方，证明保存结果可被创作页读取，而非仅 UI 缓存。
        service = runpy.run_path(str(ROOT / "pixelle_video/services/api_asset_analysis.py"))["APIAssetAnalysisService"]
        return service(config).list_models(configured_only=False)

    def save_external_openai_catalog(self, model_ids, *, source="api"):
        """模拟素材页的增量保存，只改内存管理器，不接触真实配置或网络。"""
        providers = self.manager.get_api_providers_config()
        snapshot = self.catalog.make_model_catalog(
            "openai", providers["openai"], providers["common"], model_ids, source=source,
        )
        self.manager.set_api_provider_config("openai", {"model_catalog": snapshot})
        self.manager.save()
        return snapshot

    def test_idle_settings_sync_external_catalog_and_do_not_overwrite_it(self):
        """同一连接初始无目录或已有旧目录，素材页保存后旧设置页均应同步。"""
        self.manager.set_api_provider_config("openai", {"use_proxy": False})
        for initial_ids in ([], ["old-saved-model"]):
            with self.subTest(initial_ids=initial_ids):
                self.manager.set_api_provider_config("openai", {"model_catalog": {}})
                if initial_ids:
                    self.save_external_openai_catalog(initial_ids)
                self.fresh_app()
                external = self.save_external_openai_catalog(["asset-page-new-model"])
                self.app.button(key="save_config_btn").click().run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.manager.saved[-1]["api_providers"]["openai"]["model_catalog"], external)
                state = self.app.session_state["api_media_openai_model_catalog_state"]
                self.assertEqual(state["snapshot"], external)
                self.assertFalse(state["dirty"])
        self.load.assert_not_called()

    def test_saved_local_catalog_becomes_clean_and_accepts_later_external_update(self):
        """本页保存成功要结束草稿，否则后续外部目录会一直被误判为冲突。"""
        self.app.checkbox(key="api_media_openai_use_proxy").set_value(False)
        self.load_catalog()
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.session_state["api_media_openai_model_catalog_state"]["dirty"])
        external = self.save_external_openai_catalog(["later-asset-page-model"])
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.manager.saved[-1]["api_providers"]["openai"]["model_catalog"], external)

    def test_external_update_does_not_restore_locally_failed_or_empty_catalog(self):
        """本页明确失败/空结果的清空意图，在保存前不能被外部目录复活。"""
        self.manager.set_api_provider_config("openai", {"use_proxy": False})
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.save_external_openai_catalog(["original-saved-model"])
                self.fresh_app()
                self.load.return_value = []
                self.load.side_effect = RuntimeError("HTTP 401：鉴权失败。") if fail else None
                self.load_catalog()
                local = self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"]
                self.save_external_openai_catalog(["external-model"])
                self.app.run()
                state = self.app.session_state["api_media_openai_model_catalog_state"]
                self.assertEqual(state["snapshot"], local)
                self.assertTrue(state["dirty"])
                self.assertTrue(any("本页有未保存的目录操作" in item.value for item in self.app.caption))
                self.app.button(key="save_config_btn").click().run()
                self.assertFalse(self.app.exception)
                saved = self.manager.saved[-1]["api_providers"]
                self.assertEqual(self.catalog.get_configured_model_ids("openai", saved["openai"], saved["common"]), [])
                self.assertFalse(self.app.session_state["api_media_openai_model_catalog_state"]["dirty"])

    def test_pending_manual_catalog_survives_external_save(self):
        """本页手工应用的未保存目录不能被其他页面的新 API 目录吞掉。"""
        self.manager.set_api_provider_config("openai", {"use_proxy": False})
        self.save_external_openai_catalog(["original-saved-model"])
        self.fresh_app()
        self.app.radio(key="api_media_openai_catalog_mode").set_value("manual").run()
        self.app.text_area(key="api_media_openai_manual_models").set_value("my-unpublished-alias")
        self.app.button(key="api_media_openai_apply_manual_models").click().run()
        self.save_external_openai_catalog(["external-api-model"])
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        saved = self.manager.saved[-1]["api_providers"]["openai"]["model_catalog"]
        self.assertEqual(saved["source"], "manual")
        self.assertEqual(saved["models"], ["my-unpublished-alias"])

    def test_clean_cache_syncs_external_source_change_and_clear(self):
        """来源一起同步，避免旧来源控件把新目录清掉；外部清空也应可见。"""
        self.manager.set_api_provider_config("openai", {"use_proxy": False})
        self.save_external_openai_catalog(["old-api-model"])
        self.fresh_app()
        external = self.save_external_openai_catalog(["external-manual-alias"], source="manual")
        self.app.run()
        self.assertEqual(self.app.radio(key="api_media_openai_catalog_mode").value, "manual")
        self.assertEqual(self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"], external)
        self.manager.set_api_provider_config("openai", {"model_catalog": {}})
        self.manager.save()
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.manager.saved[-1]["api_providers"]["openai"]["model_catalog"], {})

    def test_unloaded_selectors_have_no_hardcoded_models_or_legacy_fallback(self):
        self.load.assert_not_called()
        self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, [])
        self.assertEqual(self.creator_models(self.manager.config.model_dump()), [])
        self.assertEqual(self.manager.saved, [])
        self.manager.set_api_provider_config("openai", {"vision_models": ["legacy-handwritten-id"]})
        self.assertEqual(self.creator_models(self.manager.config.model_dump()), [])

    def test_api_load_save_roundtrip_populates_real_creator_with_new_model_ids(self):
        self.app.text_input(key="api_media_openai_key").set_value("test-current-key")
        self.app.text_input(key="api_media_openai_base_url").set_value("https://relay.example.invalid/custom/v1")
        self.app.checkbox(key="api_media_openai_use_proxy").set_value(True)
        self.app.text_input(key="api_media_local_proxy").set_value("http://127.0.0.1:17777")
        self.load_catalog()
        self.load.assert_called_once_with("openai", {
            "api_key": "test-current-key", "base_url": "https://relay.example.invalid/custom/v1", "use_proxy": True,
        }, {"local_proxy": "http://127.0.0.1:17777"})
        self.assertEqual(self.manager.saved, [])
        self.assertFalse(self.app.multiselect)
        saved = self.save()
        self.assertEqual(saved["api_providers"]["openai"]["model_catalog"]["source"], "api")
        self.assertEqual([item["model"] for item in self.creator_models(saved)], ["relay-new-vision-999", "gpt-6.1-sol"])
        self.fresh_app()
        self.assertEqual(self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"]["models"], ["relay-new-vision-999", "gpt-6.1-sol"])
        self.load.assert_called_once()

    def test_four_api_providers_load_complete_catalogs_without_confirmation_selection(self):
        for provider in ("openai", "dashscope", "xai", "muse"):
            with self.subTest(provider=provider):
                self.app.text_input(key=f"api_media_{provider}_key").set_value(f"test-{provider}-key")
                self.app.text_input(key=f"api_media_{provider}_base_url").set_value(f"https://{provider}.example.invalid/v1")
                self.app.checkbox(key=f"api_media_{provider}_use_proxy").set_value(False)
                self.load_catalog(provider)
                state = self.app.session_state[f"api_media_{provider}_model_catalog_state"]
                self.assertEqual(state["snapshot"]["models"], ["relay-new-vision-999", "gpt-6.1-sol"])
        saved = self.save()
        for provider in ("openai", "dashscope", "xai", "muse"):
            self.assertEqual(saved["api_providers"][provider]["model_catalog"]["source"], "api")

    def test_changed_credentials_clear_catalog_and_saving_does_not_rebind_old_ids(self):
        self.app.checkbox(key="api_media_openai_use_proxy").set_value(False)
        self.load_catalog()
        saved = self.save()
        self.assertTrue(self.creator_models(saved))
        self.app.text_input(key="api_media_openai_key").set_value("test-different-key").run()
        self.assertEqual(self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"], {})
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        saved = self.manager.saved[-1]
        self.assertEqual(saved["api_providers"]["openai"]["model_catalog"], {})
        self.assertEqual(self.creator_models(saved), [])

    def test_failure_or_empty_directory_clears_old_persistent_catalog(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.load.side_effect = None
                self.load.return_value = ["previous-model"]
                self.app.checkbox(key="api_media_openai_use_proxy").set_value(False)
                self.load_catalog()
                self.app.button(key="save_config_btn").click().run()
                self.load.return_value = []
                if fail:
                    self.load.side_effect = RuntimeError("HTTP 401：鉴权失败，请检查当前服务的 API Key。")
                self.load_catalog()
                self.app.button(key="save_config_btn").click().run()
                self.assertFalse(self.app.exception)
                saved = self.manager.saved[-1]
                self.assertEqual(self.creator_models(saved), [])
                snapshot = saved["api_providers"]["openai"]["model_catalog"]
                self.assertEqual(snapshot, {} if fail else {**snapshot, "models": []})

    def test_manual_directory_is_explicit_and_requires_apply_again_after_connection_change(self):
        self.app.radio(key="api_media_ark_catalog_mode").set_value("manual").run()
        self.app.text_area(key="api_media_ark_manual_models").set_value("relay-image-alias\nrelay-video-alias")
        self.app.button(key="api_media_ark_apply_manual_models").click().run()
        self.assertFalse(self.app.exception)
        self.load.assert_not_called()
        saved = self.save()
        self.assertEqual(saved["api_providers"]["ark"]["model_catalog"]["source"], "manual")
        self.assertEqual(saved["api_providers"]["ark"]["model_catalog"]["models"], ["relay-image-alias", "relay-video-alias"])
        self.app.text_input(key="api_media_ark_base_url").set_value("https://new-ark.example.invalid/v3").run()
        self.assertEqual(self.app.text_area(key="api_media_ark_manual_models").value, "relay-image-alias\nrelay-video-alias")
        self.app.button(key="save_config_btn").click().run()
        self.assertEqual(self.manager.saved[-1]["api_providers"]["ark"]["model_catalog"], {})
        self.app.button(key="api_media_ark_apply_manual_models").click().run()
        self.app.button(key="save_config_btn").click().run()
        self.assertEqual(self.manager.saved[-1]["api_providers"]["ark"]["model_catalog"]["models"], ["relay-image-alias", "relay-video-alias"])

    def test_llm_dropdown_only_loaded_ids_custom_model_is_separate_and_preserved(self):
        previous = {"api_key": "test-llm-key", "base_url": "https://llm.example.invalid/v1", "model": "my-old-alias"}
        self.manager.config.llm = type(self.manager.config.llm)(**previous)
        self.fresh_app()
        self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, [])
        self.assertEqual(self.app.text_input(key="llm_custom_model_input_Custom").value, "my-old-alias")
        self.load_catalog("llm")
        self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, ["relay-new-vision-999", "gpt-6.1-sol"])
        self.assertEqual(self.app.radio(key="llm_model_source").value, "custom")
        saved = self.save()
        self.assertEqual(saved["llm"]["model"], "my-old-alias")
        self.assertEqual(self.catalog.get_configured_model_ids("llm", saved["llm"]), ["relay-new-vision-999", "gpt-6.1-sol"])
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://other.example.invalid/v1").run()
        self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, [])
        self.assertEqual(self.app.text_input(key="llm_custom_model_input_Custom").value, "my-old-alias")
        self.app.button(key="save_config_btn").click().run()
        self.assertEqual(self.manager.saved[-1]["llm"]["model_catalog"], {})

    def test_new_llm_can_load_then_save_without_any_preset_model(self):
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-first-llm")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://new-llm.example.invalid/v1")
        self.load_catalog("llm")
        self.assertEqual(self.app.radio(key="llm_model_source").value, "catalog")
        self.app.selectbox(key="llm_model_select_Custom").set_value("gpt-6.1-sol").run()
        saved = self.save()
        self.assertEqual(saved["llm"]["model"], "gpt-6.1-sol")
        self.assertEqual(self.catalog.get_configured_model_ids("llm", saved["llm"]), ["relay-new-vision-999", "gpt-6.1-sol"])

    def test_llm_failed_or_empty_reload_persists_cleared_catalog_without_resurrecting_model(self):
        """目录模式下空/失败不能因没有已选模型而跳过保存、复活旧目录。"""
        for fail in (False, True):
            with self.subTest(fail=fail):
                self.load.side_effect = None
                self.load.return_value = ["old-directory-model"]
                self.app.text_input(key="llm_api_key_input_Custom").set_value("test-llm-key")
                self.app.text_input(key="llm_base_url_input_Custom").set_value("https://llm.example.invalid/v1")
                self.load_catalog("llm")
                self.app.radio(key="llm_model_source").set_value("catalog").run()
                self.app.button(key="save_config_btn").click().run()
                self.load.return_value = []
                if fail:
                    self.load.side_effect = RuntimeError("HTTP 401：鉴权失败。")
                self.load_catalog("llm")
                self.app.button(key="save_config_btn").click().run()
                self.assertFalse(self.app.exception)
                saved = self.manager.saved[-1]["llm"]
                self.assertEqual(saved["model"], "")
                self.assertEqual(self.catalog.get_configured_model_ids("llm", saved), [])
                self.fresh_app()
                self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, [])

    def test_model_diagnostics_do_not_echo_current_secrets_and_full_list_is_visible(self):
        self.app.checkbox(key="api_media_openai_use_proxy").set_value(False)
        self.load.return_value = [f"returned-model-{index}" for index in range(12)]
        self.load_catalog()
        self.assertIn("returned-model-11", "\n".join(item.value for item in self.app.code))
        self.load.side_effect = RuntimeError("bad test-openai-key request")
        self.load_catalog()
        visible = "\n".join(item.value for item in self.app.caption) + "\n".join(item.value for item in self.app.warning)
        self.assertNotIn("test-openai-key", visible)
        self.assertEqual(self.app.session_state["api_media_openai_model_catalog_state"]["snapshot"], {})

    def test_removed_llm_choice_requires_explicit_new_selection(self):
        """已有目录选中型号被接口移除时，不把新的首项静默应用为模型。"""
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-text-key")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://text.example.invalid/v1")
        self.load.return_value = ["old-model"]
        self.load_catalog("llm")
        self.app.button(key="save_config_btn").click().run()
        self.assertEqual(self.manager.saved[-1]["llm"]["model"], "old-model")
        self.load.return_value = ["different-model"]
        self.load_catalog("llm")
        self.assertEqual(self.app.selectbox(key="llm_model_select_Custom").options, ["different-model"])
        self.assertIsNone(self.app.selectbox(key="llm_model_select_Custom").value)
        # 额外重绘也不能把 None 重置成首项；只有显式点选后可使用新型号。
        self.app.run()
        self.assertIsNone(self.app.selectbox(key="llm_model_select_Custom").value)
        self.app.selectbox(key="llm_model_select_Custom").set_value("different-model").run()
        self.app.button(key="save_config_btn").click().run()
        self.assertEqual(self.manager.saved[-1]["llm"]["model"], "different-model")

    def test_llm_endpoint_paste_is_normalized_before_load_snapshot_and_save(self):
        """完整端点先规范到同一根路径，保存和重开时快照不会因路径不同而失效。"""
        for suffix in ("/chat/completions", "/completions", "/responses", "/models"):
            with self.subTest(suffix=suffix):
                self.app.text_input(key="llm_api_key_input_Custom").set_value("test-text-key")
                self.app.text_input(key="llm_base_url_input_Custom").set_value("https://text.example.invalid/v1" + suffix)
                self.load_catalog("llm")
                self.load.assert_called_with("llm", {
                    "api_key": "test-text-key", "base_url": "https://text.example.invalid/v1",
                }, {})
                self.app.radio(key="llm_model_source").set_value("catalog").run()
                self.app.selectbox(key="llm_model_select_Custom").set_value("gpt-6.1-sol").run()
                self.app.button(key="save_config_btn").click().run()
                saved = self.manager.saved[-1]["llm"]
                self.assertEqual(saved["base_url"], "https://text.example.invalid/v1")
                self.assertEqual(self.catalog.get_configured_model_ids("llm", saved), ["relay-new-vision-999", "gpt-6.1-sol"])
                self.fresh_app()
                self.assertIn("gpt-6.1-sol", self.app.selectbox(key="llm_model_select_Custom").options)

    def test_actual_manager_replaces_empty_catalog_and_preserves_other_fields(self):
        """直接运行生产管理器类，验证 {} 整块清除而不是被深合并保留。"""
        tree = ast.parse((ROOT / "pixelle_video/config/manager.py").read_text(encoding="utf-8"))
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "ConfigManager")
        # 只加载类定义并注入内存配置；不执行模块初始化、_load 或真实文件写入。
        namespace = {"Path": Path, "Any": Any, "Optional": Optional, "PixelleVideoConfig": type(self.manager.config)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "config_manager_offline", "exec"), namespace)
        manager = object.__new__(namespace["ConfigManager"])
        manager.config = self.manager.config.model_copy(deep=True)
        cfg = manager.get_api_providers_config()["openai"]
        cfg["use_proxy"] = False
        snapshot = self.catalog.make_model_catalog("openai", cfg, {}, ["test-new-model"])
        manager.set_api_provider_config("openai", {**cfg, "model_catalog": snapshot})
        self.assertEqual(manager.get_api_providers_config()["openai"]["model_catalog"], snapshot)
        manager.set_api_provider_config("openai", {"model_catalog": {}})
        self.assertEqual(manager.get_api_providers_config()["openai"]["model_catalog"], {})
        self.assertEqual(manager.get_api_providers_config()["openai"]["api_key"], cfg["api_key"])
        self.assertEqual(manager.get_api_providers_config()["deepseek"]["api_key"], "test-deepseek-key")
        llm_cfg = {"api_key": "test-llm-key", "base_url": "https://llm.example.invalid/v1"}
        llm_snapshot = self.catalog.make_model_catalog("llm", llm_cfg, {}, ["test-text-model"])
        manager.set_llm_config(llm_cfg["api_key"], llm_cfg["base_url"] + "/responses", "test-text-model", model_catalog=llm_snapshot)
        self.assertEqual(manager.get_llm_config()["model_catalog"], llm_snapshot)
        self.assertEqual(manager.get_llm_config()["base_url"], llm_cfg["base_url"])
        manager.set_llm_config(llm_cfg["api_key"], llm_cfg["base_url"], "", model_catalog={})
        self.assertEqual(manager.get_llm_config()["model_catalog"], {})


# 复用 fixture 方法，不重复收集旧测试类。
del _fixture


if __name__ == "__main__":
    unittest.main()
