"""上传公共缓存的离线行为测试，不读取用户素材或调用生成服务。"""

import io
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.proto.Common_pb2 import FileURLs
from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec

ROOT = Path(__file__).resolve().parents[1]
persist_uploaded_files = runpy.run_path(str(ROOT / "web/components/creation_uploads.py"))["persist_uploaded_files"]


def upload(name, contents):
    """模拟 Streamlit 上传对象，保持其 getbuffer 接口。"""
    item = io.BytesIO(contents)
    item.name = name
    return item


def streamlit_upload(file_id, name, contents):
    """使用真实上传类型与虚构记录，模拟 rerun 从同一上传记录重建对象。"""
    return UploadedFile(UploadedFileRec(file_id, name, "video/mp4", contents), FileURLs())


class CreationUploadsTest(unittest.TestCase):
    def test_streamlit_identity_skips_repeated_buffer_reads_and_content_hashing(self):
        """同一上传在步骤切换后以新对象出现，仍不重复读取完整文件。"""
        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_test": {"directory": folder, "files": {}}}
            first_upload = streamlit_upload("test-file-id", "长素材.mp4", b"offline-video-bytes")
            rerun_upload = streamlit_upload("test-file-id", "长素材.mp4", b"offline-video-bytes")
            with (
                patch("streamlit.session_state", state),
                patch.object(first_upload, "getbuffer", wraps=first_upload.getbuffer) as first_buffer,
                patch.object(rerun_upload, "getbuffer", wraps=rerun_upload.getbuffer) as rerun_buffer,
            ):
                first = persist_uploaded_files([first_upload], key="test")
                again = persist_uploaded_files([rerun_upload], key="test")
                self.assertEqual(first, again)
                first_buffer.assert_called_once_with()
                rerun_buffer.assert_not_called()
                self.assertEqual(Path(first[0]).read_bytes(), b"offline-video-bytes")
                # 索引只保存身份与摘要，不把 UploadedFile 或字节缓存进 session_state。
                identities = state["creation_upload_test"]["upload_identities"]
                self.assertEqual(list(identities), [("test-file-id", "长素材.mp4", 19)])
                self.assertTrue(all(isinstance(digest, str) for digest in identities.values()))

    def test_new_upload_id_same_name_and_size_does_not_reuse_old_content(self):
        """同名等大小替换仍以新 ID 重新校验内容，原历史路径继续可用。"""
        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_test": {"directory": folder, "files": {}}}
            replacement = streamlit_upload("replacement-id", "same.mp4", b"second")
            with (
                patch("streamlit.session_state", state),
                patch.object(replacement, "getbuffer", wraps=replacement.getbuffer) as replacement_buffer,
            ):
                first = persist_uploaded_files([streamlit_upload("first-id", "same.mp4", b"first!")], key="test")
                changed = persist_uploaded_files([replacement], key="test")
                replacement_buffer.assert_called_once_with()
                self.assertNotEqual(first, changed)
                self.assertEqual(Path(first[0]).read_bytes(), b"first!")
                self.assertEqual(Path(changed[0]).read_bytes(), b"second")
                self.assertEqual(persist_uploaded_files([], key="test"), [])
                self.assertTrue(Path(first[0]).is_file())
                self.assertTrue(Path(changed[0]).is_file())

    def test_missing_identity_cache_file_is_rebuilt_from_the_upload(self):
        """外部清理过素材缓存时，命中上传身份也必须重新读取并恢复文件。"""
        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_test": {"directory": folder, "files": {}}}
            file = streamlit_upload("same-id", "video.mp4", b"test-media")
            with patch("streamlit.session_state", state):
                first = persist_uploaded_files([file], key="test")
                Path(first[0]).unlink()
                with patch.object(file, "getbuffer", wraps=file.getbuffer) as buffer:
                    recovered = persist_uploaded_files([file], key="test")
                    buffer.assert_called_once_with()
                self.assertEqual(first, recovered)
                self.assertEqual(Path(recovered[0]).read_bytes(), b"test-media")

    def test_generic_objects_do_not_gain_identity_shortcuts_from_similar_attributes(self):
        """只有真实 Streamlit 身份可复用，普通可变文件仍每次比较内容。"""
        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_test": {"directory": folder, "files": {}}}
            generic = upload("sample.mp4", b"first!")
            generic.file_id = "untrusted-id"
            generic.size = 6
            with patch("streamlit.session_state", state):
                first = persist_uploaded_files([generic], key="test")
                generic.seek(0)
                generic.write(b"second")
                changed = persist_uploaded_files([generic], key="test")
                self.assertNotEqual(first, changed)
                self.assertEqual(Path(changed[0]).read_bytes(), b"second")
                self.assertEqual(state["creation_upload_test"]["upload_identities"], {})

    def test_reuses_replaces_removes_and_recovers_deleted_cache_file(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {"creation_upload_test": {"directory": folder, "files": {}}}
            with patch("streamlit.session_state", state):
                first = persist_uploaded_files([upload("素材.png", b"original")], key="test")
                again = persist_uploaded_files([upload("素材.png", b"original")], key="test")
                self.assertEqual(first, again)
                self.assertEqual(len(list(Path(folder).iterdir())), 1)
                changed = persist_uploaded_files([upload("素材.png", b"updated")], key="test")
                self.assertNotEqual(first, changed)
                self.assertEqual(Path(changed[0]).read_bytes(), b"updated")
                self.assertEqual(persist_uploaded_files([], key="test"), [])
                self.assertEqual(Path(first[0]).read_bytes(), b"original")
                # 缓存文件被外部清理时，原上传数据能在同一路径补回。
                Path(first[0]).unlink()
                recovered = persist_uploaded_files([upload("素材.png", b"original")], key="test")
                self.assertEqual(recovered, first)
                self.assertEqual(Path(recovered[0]).read_bytes(), b"original")

    def test_business_keys_isolate_upload_roles_and_preserve_input_order(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {
                "creation_upload_person": {"directory": str(Path(folder) / "person"), "files": {}},
                "creation_upload_motion": {"directory": str(Path(folder) / "motion"), "files": {}},
            }
            with patch("streamlit.session_state", state):
                person = persist_uploaded_files([upload("same.png", b"same")], key="person")
                motion = persist_uploaded_files(
                    [upload("../same.png", b"same"), upload("other.mp4", b"second")], key="motion"
                )
                self.assertNotEqual(person[0], motion[0])
                self.assertEqual(Path(motion[0]).parent, Path(folder) / "motion")
                self.assertEqual([Path(path).read_bytes() for path in motion], [b"same", b"second"])
                self.assertEqual(len(state["creation_upload_person"]["files"]), 1)
                self.assertEqual(len(state["creation_upload_motion"]["files"]), 2)


if __name__ == "__main__":
    unittest.main()
