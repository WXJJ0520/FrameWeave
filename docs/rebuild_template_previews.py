"""离线重建镜织内置模板缩略图，不加载应用配置、不访问模型或外部图片。"""

import asyncio
import json
import runpy
import sys
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_frame_generator():
    """只加载原模板渲染器，避开包入口的全局服务及真实配置初始化。"""
    packages = {}
    for name in ("pixelle_video", "pixelle_video.utils"):
        package = types.ModuleType(name)
        package.__path__ = [str(ROOT / name.replace(".", "/"))]
        packages[name] = package
    with patch.dict(sys.modules, packages):
        namespace = runpy.run_path(str(ROOT / "pixelle_video/services/frame_html.py"))
    return namespace["HTMLFrameGenerator"]


async def rebuild_previews():
    """只写专属 frameweave 目录；原图库与用户模板不受影响。"""
    frame_generator = load_frame_generator()

    class OfflineBrowser:
        def __init__(self, browser):
            self.browser = browser

        async def new_page(self, **kwargs):
            # 图库只需半尺寸预览，保持模板排版比例并减少页面同时加载的图片体积。
            kwargs["device_scale_factor"] = 0.5
            page = await self.browser.new_page(**kwargs)
            # 模板可能引用在线字体；离线预览使用系统字体，保证不会访问远端。
            await page.route("http://**/*", lambda route: route.abort())
            await page.route("https://**/*", lambda route: route.abort())
            return page

    class OfflineFrameGenerator(frame_generator):
        @classmethod
        async def _ensure_browser(cls):
            return OfflineBrowser(await super()._ensure_browser())

    preview_root = ROOT / "docs/images/frameweave"
    image_path = str(ROOT / "resources/example.png")
    samples = {
        "zh_CN": (
            "让想法成为故事",
            "从一个想法出发，用镜织 FrameWeave 编写脚本、制作画面与配音，创作属于你的视频。",
        ),
        "en_US": (
            "Turn ideas into stories",
            "Bring your ideas to life with FrameWeave. Create scripts, visuals, and narration for your next video.",
        ),
    }
    generated = []
    try:
        for template in sorted((ROOT / "templates").rglob("*.html")):
            generator = OfflineFrameGenerator(str(template))
            for language, (title, text) in samples.items():
                suffix = "" if language == "zh_CN" else "_en"
                output = preview_root / template.parent.name / f"{template.stem}{suffix}.png"
                await generator.generate_frame(
                    title=title, text=text, image=image_path,
                    ext={"index": 1}, output_path=str(output),
                )
                generated.append(output.relative_to(ROOT).as_posix())
    finally:
        await OfflineFrameGenerator.close_browser()
    manifest = {"brand": "镜织 FrameWeave", "templates": len(generated) // 2, "previews": generated}
    (preview_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Generated {len(generated)} local FrameWeave previews")


if __name__ == "__main__":
    asyncio.run(rebuild_previews())
