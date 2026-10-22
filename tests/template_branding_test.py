"""模板品牌回归：真实参数解析、精准旧缓存迁移以及新旧图库隔离。"""

import ast
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def branding_helpers():
    """提取无副作用的真实函数，测试时不初始化 Streamlit 或读取真实配置。"""
    tree = ast.parse((ROOT / "web/components/style_config.py").read_text(encoding="utf-8"))
    names = {"migrate_template_branding", "get_template_preview_path"}
    module = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    namespace = {"Path": Path}
    exec(compile(module, "style_config.py", "exec"), namespace)
    return namespace


class TemplateBrandingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helpers = branding_helpers()
        cls.generator = runpy.run_path(str(ROOT / "docs/rebuild_template_previews.py"))["load_frame_generator"]()

    def test_all_bundled_templates_parse_and_render_current_brand_defaults(self):
        expected = {
            "author": "@镜织 FrameWeave", "signature": "@镜织 FrameWeave",
            "brand": "镜织 FrameWeave", "describe": "用 AI 把想法变成视频",
        }
        branded = 0
        for path in sorted((ROOT / "templates").rglob("*.html")):
            with self.subTest(template=path.name):
                generator = self.generator(str(path))
                params = generator.parse_template_parameters()
                branded += bool(set(params) & set(expected))
                for name, value in expected.items():
                    if name in params:
                        self.assertEqual(params[name]["default"], value)
                rendered = generator._replace_parameters(generator.template, {"title": "测试", "text": "内容", "image": "", "index": 1})
                self.assertNotIn("Pixelle", rendered)
        self.assertEqual(branded, 22)

    def test_migration_only_updates_exact_old_defaults_and_runs_once(self):
        migrate = self.helpers["migrate_template_branding"]
        params = {
            "author": {"default": "@镜织 FrameWeave"},
            "signature": {"default": "@镜织 FrameWeave"},
            "brand": {"default": "镜织 FrameWeave"},
            "describe": {"default": "用 AI 把想法变成视频"},
        }
        state = {
            "video_custom_author": "@Pixelle.AI",
            "video_custom_signature": "@我的频道",
            "video_custom_brand": "Pixelle-Video",
            "video_custom_describe": "Open Source Omnimodal AI Creative Agent",
            "preview_text": "Pixelle.AI 正在用人工智能改变内容创作的方式，让每个人都能轻松制作专业级视频。",
        }
        migrate(state, params, "镜织预览")
        self.assertEqual(state["video_custom_author"], "@镜织 FrameWeave")
        self.assertEqual(state["video_custom_signature"], "@我的频道")
        self.assertEqual(state["video_custom_brand"], "镜织 FrameWeave")
        self.assertEqual(state["video_custom_describe"], "用 AI 把想法变成视频")
        self.assertEqual(state["preview_text"], "镜织预览")
        # 第一次升级后，主动填写的作者值不再被每次 rerun 强制覆盖。
        state["video_custom_author"] = "@Pixelle.AI"
        migrate(state, params, "镜织预览")
        self.assertEqual(state["video_custom_author"], "@Pixelle.AI")

    def test_custom_template_defaults_and_custom_preview_text_are_preserved(self):
        state = {"video_custom_author": "@Pixelle.AI", "preview_text": "我自己的 Pixelle.AI 教程示例"}
        self.helpers["migrate_template_branding"](state, {"author": {"default": "原创作者"}}, "镜织预览")
        self.assertEqual(state["video_custom_author"], "@Pixelle.AI")
        self.assertEqual(state["preview_text"], "我自己的 Pixelle.AI 教程示例")

    def test_real_template_inputs_migrate_cached_defaults_and_keep_user_edits(self):
        fixture_class = runpy.run_path(str(ROOT / "tests/api_shared_ui_test.py"))["APISharedUITest"]
        fixture = fixture_class("test_quick_create_migrates_old_source_and_uses_selected_api_model")
        fixture.setUp()
        try:
            # 配置和服务由既有内存夹具隔离，模板参数依旧来自真正的 HTML 解析器。
            generator = self.generator(str(ROOT / "templates/1080x1920/image_default.html"))
            fake_generator = sys.modules["pixelle_video.services.frame_html"].HTMLFrameGenerator
            fake_generator.return_value.parse_template_parameters = generator.parse_template_parameters
            app = AppTest.from_string(
                "import runpy\nimport streamlit as st\nfrom api_shared_core import core\n"
                f"result = runpy.run_path({str(ROOT / 'web/components/style_config.py')!r})['render_style_config'](core)\n"
                "st.session_state['_result'] = result\n",
                default_timeout=10,
            )
            app.session_state["video_custom_author"] = "@Pixelle.AI"
            app.session_state["video_custom_brand"] = "我的个人品牌"
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.text_input(key="video_custom_author").value, "@镜织 FrameWeave")
            self.assertEqual(app.text_input(key="video_custom_brand").value, "我的个人品牌")
            self.assertEqual(app.session_state["_result"]["template_params"]["author"], "@镜织 FrameWeave")
            app.text_input(key="video_custom_author").set_value("@我的教学账号").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["_result"]["template_params"]["author"], "@我的教学账号")
            fixture.core.tts.assert_not_awaited()
        finally:
            fixture.doCleanups()

    def test_preview_lookup_prefers_new_brand_but_preserves_user_template_override(self):
        lookup = self.helpers["get_template_preview_path"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative in ("docs/images/frameweave/1080x1920/image_default_en.png", "docs/images/1080x1920/image_default_en.jpg"):
                image = root / relative
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(b"preview-fixture")
            current = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(Path(lookup("1080x1920/image_default.html", "en_US")), Path("docs/images/frameweave/1080x1920/image_default_en.png"))
                custom_template = root / "data/templates/1080x1920/image_default.html"
                custom_template.parent.mkdir(parents=True)
                custom_template.write_text("用户自定义模板", encoding="utf-8")
                self.assertEqual(Path(lookup("1080x1920/image_default.html", "en_US")), Path("docs/images/1080x1920/image_default_en.jpg"))
            finally:
                os.chdir(current)

    def test_current_locale_product_copy_has_new_brand(self):
        for language in ("zh_CN", "en_US"):
            translations = json.loads((ROOT / f"web/i18n/locales/{language}.json").read_text(encoding="utf-8"))["t"]
            for key in ("app.title", "template.preview_default_text", "welcome.first_time"):
                with self.subTest(language=language, key=key):
                    self.assertIn("FrameWeave", translations[key])
                    self.assertNotIn("Pixelle", translations[key])

    def test_all_bundled_templates_have_current_brand_gallery_previews(self):
        # 读取实际 PNG 文件头，验证图库资源不是只有清单而没有可显示的图片。
        manifest = json.loads((ROOT / "docs/images/frameweave/manifest.json").read_text(encoding="utf-8"))
        templates = sorted((ROOT / "templates").rglob("*.html"))
        self.assertEqual(manifest["templates"], len(templates))
        self.assertEqual(len(manifest["previews"]), 2 * len(templates))
        for template in templates:
            for suffix in ("", "_en"):
                preview = ROOT / "docs/images/frameweave" / template.parent.name / f"{template.stem}{suffix}.png"
                with self.subTest(preview=preview.name):
                    self.assertIn(preview.relative_to(ROOT).as_posix(), manifest["previews"])
                    self.assertEqual(preview.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
