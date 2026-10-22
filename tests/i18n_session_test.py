"""语言上下文回归：不同 iframe 脚本线程与异步任务不会覆盖彼此的语言。"""

import asyncio
import runpy
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

ROOT = Path(__file__).resolve().parents[1]


class I18nSessionTest(unittest.TestCase):
    def setUp(self):
        # 独立加载真实模块和词条，不读取应用配置、不启动服务或请求网络。
        self.i18n = runpy.run_path(str(ROOT / "web/i18n/__init__.py"))
        self.default_language = self.i18n["get_language"]()

    def read_state(self):
        """把语言代码、展示名与翻译一起检查，避免只修 getter 却遗漏 tr。"""
        return (
            self.i18n["get_language"](),
            self.i18n["get_language_name"](),
            self.i18n["tr"]("btn.generate"),
        )

    def expected_state(self, code):
        locale = self.i18n["_locales"][code]
        return code, locale["language_name"], locale["t"]["btn.generate"]

    def test_parallel_script_threads_keep_their_own_language(self):
        """复现旧全局变量的覆盖顺序：两个线程均设置完语言后才开始读取。"""
        ready = Barrier(2, timeout=5)

        def render(code):
            self.i18n["set_language"](code)
            ready.wait()
            return self.read_state()

        with ThreadPoolExecutor(max_workers=2) as pool:
            chinese = pool.submit(render, "zh_CN")
            english = pool.submit(render, "en_US")
            self.assertEqual(chinese.result(timeout=5), self.expected_state("zh_CN"))
            self.assertEqual(english.result(timeout=5), self.expected_state("en_US"))
        self.assertEqual(self.i18n["get_language"](), self.default_language)

    def test_async_tasks_are_isolated_and_keep_parent_context(self):
        """并发任务继承父上下文，但任务内切换语言不会影响兄弟任务或父任务。"""
        self.i18n["set_language"]("zh_CN")

        async def render(code):
            self.i18n["set_language"](code)
            # 让另一个任务先运行 set_language，确保测试覆盖真实交错执行。
            await asyncio.sleep(0)
            return self.read_state()

        async def run_tasks():
            results = await asyncio.gather(render("zh_CN"), render("en_US"))
            self.assertEqual(self.read_state(), self.expected_state("zh_CN"))
            return results

        self.assertEqual(
            asyncio.run(run_tasks()),
            [self.expected_state("zh_CN"), self.expected_state("en_US")],
        )
        self.assertEqual(self.read_state(), self.expected_state("zh_CN"))

    def test_cli_fallback_unknown_language_and_explicit_name_stay_compatible(self):
        """没有设置的线程仍用原默认语言，未知语言也不覆盖已选语言。"""
        self.i18n["set_language"]("en_US")
        self.i18n["set_language"]("not-a-supported-language")
        self.assertEqual(self.read_state(), self.expected_state("en_US"))
        self.assertEqual(
            self.i18n["get_language_name"]("zh_CN"),
            self.i18n["_locales"]["zh_CN"]["language_name"],
        )
        self.assertEqual(self.i18n["tr"]("missing.key", fallback="保留回退"), "保留回退")
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(
                pool.submit(self.i18n["get_language"]).result(timeout=5),
                self.default_language,
            )


if __name__ == "__main__":
    unittest.main()
