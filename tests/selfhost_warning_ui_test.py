"""本地工作流提醒的界面回归：隔离配置，不访问真实服务或凭据。"""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def make_module(name, **attributes):
    """只提供组件所需依赖，避免导入配置管理器时读取用户配置。"""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class SelfHostWarningUITest(unittest.TestCase):
    def setUp(self):
        self.language = "zh_CN"
        self.locales = {
            code: json.loads((ROOT / f"web/i18n/locales/{code}.json").read_text(encoding="utf-8"))["t"]
            for code in ("zh_CN", "en_US")
        }
        self.manager = types.SimpleNamespace(
            get_comfyui_config=Mock(return_value={"comfyui_url": "http://127.0.0.1:19188"})
        )
        modules = {
            "web": make_module("web", __path__=[]),
            "web.i18n": make_module("web.i18n", tr=self.translate),
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=self.manager),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        # 即便将来重新加入脚本注入，测试也会在 iframe 写入前失败。
        html_patch = patch("streamlit.components.v1.html", side_effect=AssertionError("不得注入浏览器脚本"))
        self.html = html_patch.start()
        self.addCleanup(html_patch.stop)
        helper_path = str(ROOT / "web/utils/streamlit_helpers.py")
        self.script = (
            "import runpy\n"
            "import streamlit as st\n"
            f"helpers = runpy.run_path({helper_path!r})\n"
            "helpers['check_and_warn_selfhost_workflow'](st.session_state.get('workflow'))\n"
        )

    def translate(self, key, **kwargs):
        return self.locales[self.language][key].format(**kwargs)

    def test_selfhost_keeps_all_instructions_without_browser_alert_on_rerun(self):
        """中英文说明完整保留当前服务地址和工作流路径，刷新仅重绘折叠内容。"""
        app = AppTest.from_string(self.script)
        for language in ("zh_CN", "en_US"):
            self.language = language
            for workflow in ("selfhost/analyse_image.json", "selfhost/tts_edge.json"):
                with self.subTest(language=language, workflow=workflow):
                    app.session_state["workflow"] = workflow
                    app.run()
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(len(app.expander), 1)
                    self.assertFalse(app.expander[0].proto.expanded)
                    self.assertEqual(app.expander[0].label, self.translate("selfhost.warning.title"))
                    self.assertEqual(
                        app.markdown[0].value,
                        self.translate("selfhost.warning.message", comfyui_url="http://127.0.0.1:19188",
                                       workflow_path=f"workflows/{workflow}"),
                    )
                    self.assertEqual(app.warning[0].value, self.translate("selfhost.warning.hint"))
                    self.assertFalse(app.get("iframe"))
        self.html.assert_not_called()

    def test_other_workflows_show_no_warning_and_do_not_read_comfyui_config(self):
        """空选择、云工作流及媒体 API 不显示本地调试说明，也不读取本地配置。"""
        app = AppTest.from_string(self.script)
        for workflow in (None, "", "runninghub/image.json", "api/xai/grok-imagine-video", "api/muse/muse-video"):
            with self.subTest(workflow=workflow):
                app.session_state["workflow"] = workflow
                app.run()
                self.assertFalse(app.exception)
                self.assertFalse(app.expander)
                self.assertFalse(app.warning)
                self.assertFalse(app.markdown)
                self.assertFalse(app.get("iframe"))
        self.manager.get_comfyui_config.assert_not_called()
        self.html.assert_not_called()


if __name__ == "__main__":
    unittest.main()
