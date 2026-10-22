"""媒体配置界面回归测试：所有密钥均为测试值，不读写真实配置或访问网络。"""

import copy
import importlib.util
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
# 单独加载 schema，避免导入 pixelle_video 时初始化真实 config_manager。
PixelleVideoConfig = runpy.run_path(str(ROOT / "pixelle_video/config/schema.py"))[
    "PixelleVideoConfig"
]


class MemoryConfigManager:
    """只在内存中记录保存结果的替身，任何测试均不会触及用户配置文件。"""

    def __init__(self, data):
        self.config = PixelleVideoConfig.model_validate(data)
        self.saved = []
        self.llm_updates = []

    def validate(self):
        return self.config.validate_required()

    def get_llm_config(self):
        return self.config.llm.model_dump()

    def get_comfyui_config(self):
        return self.config.comfyui.model_dump()

    def get_api_providers_config(self):
        return self.config.api_providers.model_dump()

    def set_llm_config(self, api_key, base_url, model, *, model_catalog=None):
        self.llm_updates.append((api_key, base_url, model))
        self.config.llm = type(self.config.llm)(
            api_key=api_key,
            base_url=runpy.run_path(str(ROOT / "pixelle_video/utils/llm_util.py"))["normalize_openai_base_url"](base_url),
            model=model,
            model_catalog=self.config.llm.model_catalog if model_catalog is None else model_catalog,
        )

    def set_comfyui_config(self, **updates):
        # 与实际管理器一样，未提供的可选字段不覆盖现有值。
        data = self.config.comfyui.model_dump()
        data.update({key: value for key, value in updates.items() if value is not None})
        self.config.comfyui = type(self.config.comfyui).model_validate(data)

    def set_api_provider_config(self, provider, updates):
        data = self.config.api_providers.model_dump()
        data[provider].update(updates)
        self.config.api_providers = type(self.config.api_providers).model_validate(data)

    def save(self):
        self.saved.append(copy.deepcopy(self.config.model_dump()))


def make_module(name, **attributes):
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


def catalog_test_module():
    """加载纯目录模块，不导入 pixelle_video.__init__ 或任何真实配置。"""
    package = make_module("_settings_catalog_fixture", __path__=[])
    with patch.dict(sys.modules, {package.__name__: package}):
        for filename in ("connectivity", "model_catalog"):
            name = f"{package.__name__}.{filename}"
            spec = importlib.util.spec_from_file_location(name, ROOT / f"pixelle_video/services/api_services/{filename}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        return module


def llm_util_test_module():
    """纯工具函数无需应用初始化；规范化与生产代码保持同一实现。"""
    module = make_module("pixelle_video.utils.llm_util")
    module.__dict__.update(runpy.run_path(str(ROOT / "pixelle_video/utils/llm_util.py")))
    return module


class ProviderSettingsTest(unittest.TestCase):
    def setUp(self):
        # 旧平台使用互不相同的测试凭据，以便发现误覆盖或错误复用。
        self.original_providers = {
            provider: {
                "api_key": f"test-{provider}-key",
                "base_url": f"https://{provider}.example.invalid/v1",
                "use_proxy": provider == "openai",
            }
            for provider in ("openai", "dashscope", "ark", "deepseek", "gemini")
        }
        self.original_providers["kling"] = {
            "access_key": "test-kling-access",
            "secret_key": "test-kling-secret",
            "base_url": "https://kling.example.invalid",
            "use_proxy": True,
        }
        self.manager = MemoryConfigManager({"api_providers": self.original_providers})
        self.reruns = []
        # 所有带初始化副作用的项目导入均替换为隔离模块。
        modules = {
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module(
                "pixelle_video.config", config_manager=self.manager
            ),
            "pixelle_video.services.api_services.model_catalog": catalog_test_module(),
            "pixelle_video.utils.llm_util": llm_util_test_module(),
            "pixelle_video.llm_presets": make_module(
                "pixelle_video.llm_presets",
                get_preset_names=lambda: [],
                get_preset=lambda name: {},
                find_preset_by_base_url_and_model=lambda url, model: None,
            ),
            "web": make_module("web", __path__=[]),
            "web.i18n": make_module(
                "web.i18n", tr=lambda key: key, get_language=lambda: "zh_CN"
            ),
            "web.utils": make_module("web.utils", __path__=[]),
            "web.utils.streamlit_helpers": make_module(
                "web.utils.streamlit_helpers", safe_rerun=lambda: self.reruns.append(True)
            ),
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        # 渲染真实设置组件，按钮与输入均通过 Streamlit 的真实控件测试接口操作。
        settings_path = str(ROOT / "web/components/settings.py")
        script = (
            "import runpy\n"
            f"namespace = runpy.run_path({settings_path!r})\n"
            "namespace['render_advanced_settings']()\n"
        )
        self.app = AppTest.from_string(script).run()
        self.assertFalse(self.app.exception)

    def save(self):
        self.app.button(key="save_config_btn").click().run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.error)
        self.assertEqual(len(self.manager.saved), 1)
        return self.manager.saved[-1]

    def assert_existing_providers_preserved(self, saved):
        for provider, expected in self.original_providers.items():
            expected = {**expected, "model_catalog": {}}
            # 旧配置升级时仅新增空视觉目录，不改写原有密钥、地址与隐藏提供商。
            if provider in {"openai", "dashscope"}:
                expected = {**expected, "vision_models": []}
            self.assertEqual(saved["api_providers"][provider], expected)

    def test_xai_and_muse_save_without_llm(self):
        """未配置 LLM 时仍可保存两套独立媒体凭据与代理选项。"""
        self.app.text_input(key="api_media_xai_key").set_value("test-xai-key")
        self.app.text_input(key="api_media_xai_base_url").set_value("https://api.x.ai/v1")
        self.app.checkbox(key="api_media_xai_use_proxy").set_value(True)
        self.app.text_input(key="api_media_muse_key").set_value("test-muse-key")
        self.app.text_input(key="api_media_muse_base_url").set_value(
            "https://muse.example.invalid/v1"
        )
        saved = self.save()
        self.assertEqual(saved["api_providers"]["xai"], {
            "api_key": "test-xai-key", "base_url": "https://api.x.ai/v1", "use_proxy": True,
            "model_catalog": {},
        })
        self.assertEqual(saved["api_providers"]["muse"], {
            "api_key": "test-muse-key", "base_url": "https://muse.example.invalid/v1",
            "use_proxy": False,
            "model_catalog": {},
        })
        self.assertEqual(saved["llm"], {"api_key": "", "base_url": "", "model": "", "model_catalog": {}})
        self.assertEqual(self.manager.llm_updates, [])
        self.assert_existing_providers_preserved(saved)
        self.assertEqual(len(self.app.warning), 1)
        self.assertIn("已保存", self.app.warning[0].value)

    def test_defaults_do_not_reuse_other_provider_keys(self):
        """新增默认项为空凭据，不会复制或覆盖已有平台设置。"""
        self.assertEqual(self.app.text_input(key="api_media_xai_key").value, "")
        self.assertEqual(self.app.text_input(key="api_media_muse_key").value, "")
        self.assertEqual(self.app.text_input(key="api_media_muse_base_url").value, "")
        saved = self.save()
        self.assert_existing_providers_preserved(saved)
        self.assertEqual(saved["api_providers"]["xai"]["api_key"], "")
        self.assertEqual(saved["api_providers"]["muse"], {
            "api_key": "", "base_url": "", "use_proxy": False,
            "model_catalog": {},
        })

    def test_incomplete_llm_keeps_previous_llm_configuration(self):
        """编辑中的 LLM 缺项不能清空原设置，也不能阻止媒体配置保存。"""
        previous = {"api_key": "test-old-llm-key", "base_url": "https://llm.example.invalid/v1", "model": "test-model"}
        self.manager.config.llm = type(self.manager.config.llm)(**previous)
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-incomplete-key")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("")
        saved = self.save()
        self.assertEqual(saved["llm"], {**previous, "model_catalog": {}})
        self.assertEqual(self.manager.llm_updates, [])

    def test_complete_llm_still_saves_and_reruns(self):
        """完整 LLM 的原有保存与刷新行为继续生效。"""
        self.app.text_input(key="llm_api_key_input_Custom").set_value("test-llm-key")
        self.app.text_input(key="llm_base_url_input_Custom").set_value("https://llm.example.invalid/v1")
        self.app.text_input(key="llm_custom_model_input_Custom").set_value("test-model")
        saved = self.save()
        self.assertEqual(saved["llm"]["api_key"], "test-llm-key")
        self.assertEqual(len(self.manager.llm_updates), 1)
        self.assertEqual(self.reruns, [True])
        self.assertFalse(self.app.warning)
        self.assert_existing_providers_preserved(saved)


if __name__ == "__main__":
    unittest.main()
