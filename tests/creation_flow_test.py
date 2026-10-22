"""共享创作步骤的交互回归：真实 Streamlit 状态，完全不读取配置或调用生成服务。"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.runtime.memory_uploaded_file_manager import MemoryUploadedFileManager
from streamlit.runtime.uploaded_file_manager import UploadedFileRec
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
FLOW_PATH = ROOT / "web/components/creation_flow.py"
FLOW_KEYS = ("standard", "digital_human", "i2v", "asset_based", "action_transfer")


class CreationFlowTest(unittest.TestCase):
    def setUp(self):
        self.language = "zh_CN"
        # 只隔离语言入口；步骤类、所有输入组件和 Streamlit 回调执行真实代码。
        i18n = types.ModuleType("web.i18n")
        i18n.get_language = lambda: self.language
        language_patch = patch.dict(sys.modules, {"web.i18n": i18n})
        language_patch.start()
        self.addCleanup(language_patch.stop)
        no_network = patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("创作步骤测试不得访问网络"),
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def make_app(self, keys=("standard",), initial=None):
        # AppTest 只模拟组件树，不执行 CSS；可见布局另由实际浏览器检查。
        app = AppTest.from_string(
            "import runpy\nimport streamlit as st\n"
            f"CreationFlow = runpy.run_path({str(FLOW_PATH)!r})['CreationFlow']\n"
            f"for key in {keys!r}:\n"
            "    flow = CreationFlow(key, [('创作内容', '准备文本与素材'), "
            "('生成设置', '选择模型与配音'), ('预览与生成', '确认后开始生成')])\n"
            "    flow.render_header()\n"
            "    with flow.step(0):\n"
            "        st.text_area('创作文本', key=f'{key}_text')\n"
            "        uploaded = st.file_uploader('上传素材', key=f'{key}_upload')\n"
            "        st.session_state[f'{key}_upload_snapshot'] = "
            "None if uploaded is None else (uploaded.name, uploaded.getvalue())\n"
            "    with flow.step(1):\n"
            "        st.selectbox('模型', ['模型 A', '模型 B'], key=f'{key}_model')\n"
            "        st.slider('时长', 1, 20, 5, key=f'{key}_duration')\n"
            "    with flow.step(2):\n"
            "        if flow.is_active(2):\n"
            "            st.session_state[f'{key}_output_views'] = "
            "st.session_state.get(f'{key}_output_views', 0) + 1\n"
            "            if st.button('生成测试结果', key=f'{key}_generate'):\n"
            "                st.session_state[f'{key}_generation_calls'] = "
            "st.session_state.get(f'{key}_generation_calls', 0) + 1\n"
            "    flow.render_navigation()\n",
            default_timeout=10,
        )
        if initial:
            for key, value in initial.items():
                app.session_state[key] = value
        app.run()
        self.assertFalse(app.exception)
        return app

    def move(self, app, direction, key="standard"):
        app.button(key=f"creation_flow_{key}_{direction}").click().run()
        self.assertFalse(app.exception)

    def test_forward_and_back_preserve_text_model_and_duration(self):
        app = self.make_app()
        app.text_area(key="standard_text").set_value("我的机械表为什么会走？").run()
        self.move(app, "next")
        app.selectbox(key="standard_model").set_value("模型 B").run()
        app.slider(key="standard_duration").set_value(12).run()
        self.move(app, "next")
        self.move(app, "previous")
        self.move(app, "previous")
        self.assertEqual(app.session_state["creation_flow_standard_step"], 0)
        self.assertEqual(app.text_area(key="standard_text").value, "我的机械表为什么会走？")
        self.assertEqual(app.selectbox(key="standard_model").value, "模型 B")
        self.assertEqual(app.slider(key="standard_duration").value, 12)

    def test_uploaded_bytes_survive_navigation_and_can_be_removed(self):
        # AppTest 尚无 file_uploader.set_value；使用真实上传管理器和 widget protobuf
        # 模拟浏览器提交文件。没有改写上传控件 session_state，也没有读取用户素材。
        manager = MemoryUploadedFileManager("/test/upload")
        record = UploadedFileRec(
            file_id="creation-flow-test-image", name="人物素材.png",
            type="image/png", data=b"test-only-image-bytes",
        )
        manager.add_file("test session id", record)
        with patch(
            "streamlit.testing.v1.local_script_runner.MemoryUploadedFileManager",
            return_value=manager,
        ):
            app = self.make_app()
            upload_id = app.get("file_uploader")[0].proto.id
            states = app._tree.get_widget_states()
            uploaded_state = states.widgets.add(id=upload_id)
            uploaded_state.file_uploader_state_value.uploaded_file_info.add(
                file_id=record.file_id, name=record.name, size=len(record.data),
            )
            app._run(states)
            self.assertFalse(app.exception)
            self.assertEqual(
                app.session_state["standard_upload_snapshot"], (record.name, record.data),
            )
            for direction in ("next", "next", "previous", "previous"):
                app.button(key=f"creation_flow_standard_{direction}").click()
                # 浏览器 rerun 会携带已挂载上传框的文件 ID。AppTest 不支持上传框，
                # 普通 run() 会遗漏这个 state，因此在此补齐真实客户端的协议字段。
                next_states = app._tree.get_widget_states()
                next_states.widgets.add().CopyFrom(uploaded_state)
                app._run(next_states)
                self.assertFalse(app.exception)
                self.assertEqual(app.get("file_uploader")[0].proto.id, upload_id)
                self.assertEqual(
                    app.session_state["standard_upload_snapshot"], (record.name, record.data),
                )
            # 清除后也应保持清除状态，避免旧草稿恢复逻辑重新塞回已经删除的文件。
            cleared_states = app._tree.get_widget_states()
            cleared = cleared_states.widgets.add(id=upload_id)
            cleared.file_uploader_state_value.SetInParent()
            app._run(cleared_states)
            self.move(app, "next")
            self.assertIsNone(app.session_state["standard_upload_snapshot"])

    def test_five_flows_have_independent_navigation_and_drafts(self):
        app = self.make_app(FLOW_KEYS)
        for index, key in enumerate(FLOW_KEYS):
            with self.subTest(key=key):
                app.text_area(key=f"{key}_text").set_value(f"独立草稿 {index}").run()
                self.move(app, "next", key)
                self.assertEqual(app.session_state[f"creation_flow_{key}_step"], 1)
                for other in FLOW_KEYS[index + 1:]:
                    self.assertEqual(app.session_state[f"creation_flow_{other}_step"], 0)
        self.move(app, "next", "action_transfer")
        for index, key in enumerate(FLOW_KEYS):
            self.assertEqual(app.text_area(key=f"{key}_text").value, f"独立草稿 {index}")
            self.assertEqual(
                app.session_state[f"creation_flow_{key}_step"],
                2 if key == "action_transfer" else 1,
            )

    def test_generation_only_appears_at_final_step_and_navigation_never_submits(self):
        app = self.make_app()
        self.assertTrue(app.button(key="creation_flow_standard_previous").disabled)
        self.assertNotIn("standard_generate", [item.key for item in app.button])
        self.assertNotIn("standard_output_views", app.session_state)
        self.move(app, "next")
        self.assertNotIn("standard_generate", [item.key for item in app.button])
        self.move(app, "next")
        self.assertNotIn("creation_flow_standard_next", [item.key for item in app.button])
        self.assertIn("standard_generate", [item.key for item in app.button])
        self.assertNotIn("standard_generation_calls", app.session_state)
        views_at_final = app.session_state["standard_output_views"]
        self.move(app, "previous")
        self.assertEqual(app.session_state["standard_output_views"], views_at_final)
        self.assertNotIn("standard_generate", [item.key for item in app.button])
        self.move(app, "next")
        # 这是内存计数器，不调用任何媒体生成；证明只有明确点击才提交。
        app.button(key="standard_generate").click().run()
        self.assertEqual(app.session_state["standard_generation_calls"], 1)
        self.move(app, "previous")
        self.move(app, "next")
        self.assertEqual(app.session_state["standard_generation_calls"], 1)

    def test_chinese_and_english_navigation_labels_and_progress(self):
        for language, previous, next_label, progress in (
            ("zh_CN", "上一步", "下一步", "第 1 步 / 共 3 步"),
            ("en_US", "Previous", "Next", "Step 1 of 3"),
        ):
            with self.subTest(language=language):
                self.language = language
                app = self.make_app()
                self.assertEqual(app.button(key="creation_flow_standard_previous").label, previous)
                self.assertEqual(app.button(key="creation_flow_standard_next").label, next_label)
                self.assertIn(progress, "\n".join(item.proto.body for item in app.get("html")))

    def test_invalid_or_old_step_state_recovers_to_existing_step(self):
        for saved, expected in ((-1, 0), (99, 2), ("2", 0), (None, 0), (True, 0)):
            with self.subTest(saved=saved):
                app = self.make_app(initial={"creation_flow_standard_step": saved})
                self.assertEqual(app.session_state["creation_flow_standard_step"], expected)
                self.assertEqual(
                    app.button(key="creation_flow_standard_previous").disabled, expected == 0,
                )


if __name__ == "__main__":
    unittest.main()
