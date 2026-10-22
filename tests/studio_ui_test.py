"""工作台行为回归：真实界面控件与翻译，内存配置及模拟生成，不访问真实服务。"""

import asyncio
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup


ROOT = Path(__file__).resolve().parents[1]


def make_module(name, **attributes):
    """隔离有初始化副作用的模块，让界面测试无法加载真实配置或服务。"""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)
    return module


class StudioUITest(unittest.TestCase):
    def setUp(self):
        # Streamlit 1.53.1 的 AppTest 会把单选字符串逐字符序列化，普通 rerun 因而报错。
        # 仅修正本测试语言单选控件的测试器序列化；真实控件、回调与会话状态均不替换。
        original_indices = ButtonGroup.indices.fget

        def language_indices(widget):
            if widget.key != "studio_language" or widget.proto.click_mode != widget.proto.SINGLE_SELECT:
                return original_indices(widget)
            value = widget.value
            values = value if isinstance(value, list) else ([] if value is None else [value])
            return [widget.options.index(widget.format_func(item)) for item in values]

        indices_patch = patch.object(ButtonGroup, "indices", property(language_indices))
        indices_patch.start()
        self.addCleanup(indices_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.video = Path(self.temp.name) / "模拟成片.mp4"
        # 只给 Streamlit 本地媒体缓存提供容器头，不冒充真实可播放的生成视频。
        self.video.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2")
        result = types.SimpleNamespace(
            video_path=str(self.video), file_size=self.video.stat().st_size,
            storyboard=types.SimpleNamespace(
                frames=[object(), object(), object()],
                config=types.SimpleNamespace(frame_template="test-template.html"),
            ),
        )
        self.core = types.SimpleNamespace(generate_video=AsyncMock(return_value=result))
        self.manager = types.SimpleNamespace(validate=Mock(return_value=True))
        # 保留真实翻译表和切换函数；它们只读取仓库内的公开 locale JSON。
        i18n = make_module("web.i18n")
        i18n.__dict__.update(runpy.run_path(str(ROOT / "web/i18n/__init__.py")))
        # 模拟另一个会话最后使用英文，新会话仍必须由真实初始化函数选中文。
        i18n.set_language("en_US")
        modules = {
            "web": make_module("web", __path__=[str(ROOT / "web")]),
            "web.i18n": i18n,
            "web.components": make_module("web.components", __path__=[str(ROOT / "web/components")]),
            "web.utils": make_module("web.utils", __path__=[]),
            "web.utils.async_helpers": make_module(
                "web.utils.async_helpers", run_async=asyncio.run, get_project_version=lambda: "test",
            ),
            "web.utils.streamlit_helpers": make_module("web.utils.streamlit_helpers", safe_rerun=st.rerun),
            "pixelle_video": make_module("pixelle_video", __path__=[]),
            "pixelle_video.config": make_module("pixelle_video.config", config_manager=self.manager),
            "pixelle_video.models": make_module("pixelle_video.models", __path__=[]),
            "pixelle_video.models.progress": make_module("pixelle_video.models.progress", ProgressEvent=object),
            "pixelle_video.utils": make_module("pixelle_video.utils", __path__=[]),
            "pixelle_video.utils.template_util": make_module(
                "pixelle_video.utils.template_util", get_template_type=lambda path: "video",
                resolve_template_path=lambda path: path, parse_template_size=lambda path: (1280, 720),
            ),
            "studio_test_services": make_module("studio_test_services", core=self.core),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        # 组件测试没有多页面注册表；仅替换链接注册，保留侧栏真实品牌及语言文案。
        page_link_patch = patch("streamlit.page_link")
        page_link_patch.start()
        self.addCleanup(page_link_patch.stop)
        # 按文件加载实际组件，避免 web/pipelines 包初始化其它服务。
        header = str(ROOT / "web/components/header.py")
        content = str(ROOT / "web/components/content_input.py")
        output = str(ROOT / "web/components/output_preview.py")
        session = str(ROOT / "web/state/session.py")
        script = (
            "import runpy\n"
            "import streamlit as st\n"
            "from web.components.studio import render_studio_intro\n"
            "from studio_test_services import core\n"
            f"state = runpy.run_path({session!r})\n"
            "state['init_session_state']()\n"
            "state['init_i18n']()\n"
            f"runpy.run_path({header!r})['render_header']()\n"
            "render_studio_intro()\n"
            f"params = runpy.run_path({content!r})['render_content_input']()\n"
            "params.update(frame_template='test-template.html', media_workflow='api/xai/grok-imagine-video', "
            "tts_inference_mode='local', tts_voice='zh-CN-YunjianNeural', tts_speed=1.0)\n"
            f"runpy.run_path({output!r})['render_output_preview'](core, params)\n"
        )
        self.app = AppTest.from_string(script, default_timeout=5).run()
        self.assertFalse(self.app.exception)

    def change_language(self, code):
        """操作真实语言控件，覆盖其触发的 rerun，而不是直接修改会话语言。"""
        self.app.button_group(key="studio_language").set_value([code]).run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["language"], code)

    def test_each_session_initializer_defaults_to_chinese_and_preserves_english(self):
        """两种入口均独立验证：默认不继承全局英文，已有会话选择也不被重置。"""
        session = str(ROOT / "web/state/session.py")
        for initializer in ("init_session_state", "init_i18n"):
            for existing in (None, "en_US"):
                with self.subTest(initializer=initializer, existing=existing):
                    script = (
                        "import runpy\nimport streamlit as st\n"
                        "from web.i18n import set_language\n"
                        "set_language('en_US')\n"
                        f"runpy.run_path({session!r})[{initializer!r}]()\n"
                        "st.text(st.session_state.language)\n"
                    )
                    app = AppTest.from_string(script)
                    if existing:
                        app.session_state["language"] = existing
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.session_state["language"], existing or "zh_CN")
        self.core.generate_video.assert_not_awaited()

    def test_explicit_english_survives_initialization_on_subsequent_rerun(self):
        """用户手选英语后，真实初始化函数再次执行也应保持英语及两个明确入口。"""
        self.assertEqual(self.app.session_state["language"], "zh_CN")
        self.change_language("en_US")
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["language"], "en_US")
        self.assertEqual(self.app.session_state["studio_language"], "en_US")
        labels = [option.content for option in self.app.button_group(key="studio_language").options]
        self.assertEqual(labels, ["中文", "English"])
        self.core.generate_video.assert_not_awaited()

    def test_clicking_selected_language_keeps_selection_and_draft(self):
        """再次点击已选项产生空选择时，真实回调恢复当前语言且不丢脚本。"""
        self.app.text_area(key="quick_create_text").set_value("保留这段未提交的中文草稿").run()
        for code in ("zh_CN", "en_US"):
            with self.subTest(code=code):
                self.change_language(code)
                self.app.button_group(key="studio_language").set_value([]).run()
                self.assertFalse(self.app.exception)
                self.assertEqual(self.app.session_state["language"], code)
                self.assertEqual(self.app.session_state["studio_language"], code)
                self.assertEqual(self.app.text_area(key="quick_create_text").value, "保留这段未提交的中文草稿")
        self.core.generate_video.assert_not_awaited()

    def test_chinese_branding_has_no_english_promotional_copy(self):
        """检查实际头部、侧栏和引导文案，不对 CSS 或元素布局作断言。"""
        def visible_html():
            return "\n".join(element.proto.body for element in self.app.get("html")
                             if not element.proto.body.lstrip().startswith("<style>"))

        for return_to_chinese in (False, True):
            if return_to_chinese:
                self.change_language("en_US")
                self.assertIn("CREATIVE STUDIO", visible_html())
                self.change_language("zh_CN")
            rendered = visible_html()
            for phrase in ("创作工作台", "本地工作空间", "从灵感开始创作"):
                self.assertIn(phrase, rendered)
            for phrase in ("CREATIVE STUDIO", "LOCAL WORKSPACE", "YOUR WORKSPACE", "MAKE SOMETHING THAT MOVES"):
                self.assertNotIn(phrase, rendered)

    def test_language_round_trip_keeps_single_script_title_and_scene_count(self):
        """中文、英文往返后，已编辑脚本、标题和镜头数量不因标签翻译而丢失。"""
        self.app.text_area(key="quick_create_text").set_value("未来失物招领处，寻找昨天的十分钟。")
        self.app.text_input(key="quick_create_title").set_value("十分钟")
        self.app.slider(key="quick_create_n_scenes").set_value(7).run()
        chinese_label = self.app.text_area(key="quick_create_text").label
        for code in ("en_US", "zh_CN"):
            self.change_language(code)
            self.assertEqual(self.app.text_area(key="quick_create_text").value, "未来失物招领处，寻找昨天的十分钟。")
            self.assertEqual(self.app.text_input(key="quick_create_title").value, "十分钟")
            self.assertEqual(self.app.slider(key="quick_create_n_scenes").value, 7)
            if code == "en_US":
                self.assertNotEqual(self.app.text_area(key="quick_create_text").label, chinese_label)
        self.core.generate_video.assert_not_awaited()

    def test_fixed_script_and_split_selection_survive_language_switch(self):
        """改变创作模式及语言不清空统一脚本，分段方式保留业务值。"""
        self.app.text_area(key="quick_create_text").set_value("第一段\n第二段").run()
        self.app.radio(key="quick_create_mode").set_value("fixed").run()
        self.assertEqual(self.app.text_area(key="quick_create_text").value, "第一段\n第二段")
        self.app.selectbox(key="quick_create_split_mode").set_value("line").run()
        self.change_language("en_US")
        self.assertEqual(self.app.radio(key="quick_create_mode").value, "fixed")
        self.assertEqual(self.app.selectbox(key="quick_create_split_mode").value, "line")
        self.assertEqual(self.app.text_area(key="quick_create_text").value, "第一段\n第二段")
        self.core.generate_video.assert_not_awaited()

    def test_batch_draft_survives_language_round_trip(self):
        """批量主题、标题前缀与数量在语言切换后保留，不触发批量执行。"""
        self.app.checkbox(key="quick_create_batch_mode").set_value(True).run()
        self.app.text_area(key="quick_create_batch_topics").set_value("月球便利店\n时间邮局")
        self.app.text_input(key="quick_create_batch_title_prefix").set_value("未来日记")
        self.app.slider(key="quick_create_batch_n_scenes").set_value(9).run()
        for code in ("en_US", "zh_CN"):
            self.change_language(code)
            self.assertTrue(self.app.checkbox(key="quick_create_batch_mode").value)
            self.assertEqual(self.app.text_area(key="quick_create_batch_topics").value, "月球便利店\n时间邮局")
            self.assertEqual(self.app.text_input(key="quick_create_batch_title_prefix").value, "未来日记")
            self.assertEqual(self.app.slider(key="quick_create_batch_n_scenes").value, 9)
        self.core.generate_video.assert_not_awaited()

    def test_generated_video_survives_rerun_and_language_changes_without_resubmission(self):
        """仅明确点击生成时执行一次，后续编辑、刷新和换语言只展示已有成片。"""
        self.app.text_area(key="quick_create_text").set_value("离线界面测试脚本")
        self.app.button(key="studio_generate").click().run()
        self.assertFalse(self.app.exception)
        self.core.generate_video.assert_awaited_once()
        self.assertEqual(self.core.generate_video.call_args.kwargs["text"], "离线界面测试脚本")
        for action in (lambda: self.app.run(), lambda: self.change_language("en_US"),
                       lambda: self.app.text_input(key="quick_create_title").set_value("后续草稿").run()):
            action()
            self.assertFalse(self.app.exception)
            self.assertEqual(len(self.app.get("video")), 1)
            self.assertEqual(len(self.app.get("download_button")), 1)
            self.assertEqual(self.app.session_state["studio_last_video_result"]["video_path"], str(self.video))
            self.core.generate_video.assert_awaited_once()

    def test_invalid_input_or_configuration_does_not_generate(self):
        """保留原有输入与配置检查，错误按钮点击不能提交任务。"""
        self.app.button(key="studio_generate").click().run()
        self.assertTrue(self.app.error)
        self.core.generate_video.assert_not_awaited()
        self.manager.validate.return_value = False
        self.app.text_area(key="quick_create_text").set_value("有脚本但配置未完成")
        self.app.button(key="studio_generate").click().run()
        self.assertTrue(self.app.error)
        self.core.generate_video.assert_not_awaited()

    def test_moved_cached_video_returns_to_empty_state_without_generation(self):
        """缓存文件已移走时清理失效引用，不能偷偷重新生成替代视频。"""
        self.app.text_area(key="quick_create_text").set_value("离线测试")
        self.app.button(key="studio_generate").click().run()
        self.video.unlink()
        self.app.run()
        self.assertFalse(self.app.exception)
        self.assertNotIn("studio_last_video_result", self.app.session_state)
        self.assertEqual(len(self.app.get("video")), 0)
        self.assertEqual(len(self.app.get("download_button")), 0)
        self.core.generate_video.assert_awaited_once()

    def test_api_only_media_guard_blocks_old_or_missing_model_before_submission(self):
        """旧草稿和空模型不能调用默认工作流；静态模板仍可不选模型。"""
        output = str(ROOT / "web/components/output_preview.py")
        for workflow in (None, "runninghub/old.json", "selfhost/old.json"):
            with self.subTest(workflow=workflow):
                params = {"text": "离线守卫测试", "frame_template": "image_test.html", "media_workflow": workflow, "requires_api_media": True}
                script = (
                    "import runpy\nfrom studio_test_services import core\n"
                    f"runpy.run_path({output!r})['render_output_preview'](core, {params!r})\n"
                )
                app = AppTest.from_string(script).run()
                self.assertFalse(app.exception)
                self.assertTrue(app.button(key="studio_generate").disabled)
                self.assertTrue(app.warning)
        self.core.generate_video.assert_not_awaited()
        ready = runpy.run_path(output)["_api_media_ready"]
        self.assertTrue(ready({"frame_template": "static_test.html", "requires_api_media": False}))
        self.assertTrue(ready({"media_workflow": "api/xai/grok-imagine-video", "requires_api_media": True}))
        self.assertFalse(ready({"media_workflow": "selfhost/old.json", "requires_api_media": False}))

    def test_batch_cannot_submit_with_old_workflow(self):
        """批量入口沿用相同API来源检查，在构建任务前停止。"""
        output = str(ROOT / "web/components/output_preview.py")
        params = {"batch_mode": True, "topics": ["测试主题"], "media_workflow": "runninghub/old.json", "requires_api_media": True}
        script = (
            "import runpy\nfrom studio_test_services import core\n"
            f"runpy.run_path({output!r})['render_output_preview'](core, {params!r})\n"
        )
        app = AppTest.from_string(script).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertEqual(len(app.button), 0)
        self.core.generate_video.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
