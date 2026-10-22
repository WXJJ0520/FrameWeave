"""图片上传凭据回归：只模拟网络，不加载用户配置或真实环境凭据。"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# 单独加载图片工具，避免包初始化读取本地用户配置。
spec = importlib.util.spec_from_file_location(
    "image_processor_credentials_under_test",
    Path(__file__).resolve().parents[1]
    / "pixelle_video/services/api_services/image_processor.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImageProcessorCredentialsTest(unittest.TestCase):
    def setUp(self):
        # 清空环境凭据并拦截所有 requests 请求，保证测试不会访问供应商。
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        network = patch.object(module.requests.sessions.Session, "request")
        self.request = network.start()
        self.addCleanup(network.stop)

    def test_missing_key_blocks_policy_and_upload_before_network(self):
        processor = module.ImageProcessor()
        self.assertIsNone(processor.api_key)
        with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY 未设置"):
            processor.get_upload_policy()
        # 文件实际存在，验证阻止上传的原因确实是缺少凭据。
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.png"
            path.write_bytes(b"offline-test-file")
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY 未设置"):
                processor.upload(str(path))
        self.request.assert_not_called()

    def test_environment_key_is_used_when_argument_is_omitted(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fake-environment-key"}):
            processor = module.ImageProcessor()
        self.request.return_value = Mock(
            status_code=200, json=Mock(return_value={"data": {"policy": "fake-policy"}})
        )
        self.assertEqual(processor.get_upload_policy(), {"policy": "fake-policy"})
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["Authorization"],
            "Bearer fake-environment-key",
        )

    def test_explicit_key_takes_priority_over_environment(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fake-environment-key"}):
            processor = module.ImageProcessor(api_key="fake-explicit-key")
        self.request.return_value = Mock(
            status_code=200, json=Mock(return_value={"data": {}})
        )
        processor.get_upload_policy()
        self.assertEqual(
            self.request.call_args.kwargs["headers"]["Authorization"],
            "Bearer fake-explicit-key",
        )

    def test_empty_argument_keeps_environment_fallback(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "fake-environment-key"}):
            processor = module.ImageProcessor(api_key="")
        self.assertEqual(processor.api_key, "fake-environment-key")
        self.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
