"""镜织合成回归：使用临时素材与真实 FFmpeg，不调用任何外部模型。"""

import shutil
import subprocess
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from frameweave.engine import create_demo_assets, inspect_media, run_job


class AssetStore:
    """以临时素材库验证引擎接口，避免读写用户真实项目。"""

    def __init__(self, root):
        self.root = root
        self.assets = {}

    def register_asset(self, project_id, path, kind, source="generated"):
        asset_id = uuid.uuid4().hex
        asset = {
            "id": asset_id,
            "project_id": project_id,
            "path": str(path),
            "kind": kind,
            "source": source,
        }
        self.assets[asset_id] = asset
        return asset

    def get_asset(self, asset_id):
        return self.assets.get(asset_id)

    def get_project(self, project_id):
        return {"id": project_id, "width": 720, "height": 1280}

    def asset_path(self, asset_id):
        return Path(self.assets[asset_id]["path"])

    def work_dir(self, job_id):
        path = self.root / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path


@pytest.fixture
def store(tmp_path):
    return AssetStore(tmp_path)


def test_demo_is_local_and_preserves_chinese(store):
    scenes = create_demo_assets(store, "project", "tutorial")
    assert len(scenes) == 3
    assert "具体问题" in scenes[0]["narration"]
    assert all(store.get_asset(s["media_asset_id"])["source"] == "demo" for s in scenes)
    assert all(
        inspect_media(store.asset_path(s["media_asset_id"]))["kind"] == "image" for s in scenes
    )


def test_upload_validation_rejects_disguised_file_and_playlist(tmp_path):
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"this is not an image")
    with pytest.raises(ValueError):
        inspect_media(fake)
    playlist = tmp_path / "remote.m3u8"
    playlist.write_text("https://example.invalid/private.mp4", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持"):
        inspect_media(playlist)


@pytest.mark.asyncio
async def test_real_mixed_scene_render_and_pip_audio(store, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("需要安装 FFmpeg 才能执行真实合成测试")
    image = tmp_path / "portrait.png"
    Image.new("RGB", (180, 320), "#385c46").save(image)
    visual = store.register_asset("project", image, "image")
    video = tmp_path / "presenter.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=orange:s=120x160:r=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )
    presenter = store.register_asset("project", video, "video")
    project = {
        "id": "project",
        "width": 320,
        "height": 180,
        "fps": 24,
        "scenes": [
            {
                "id": "one",
                "narration": "字幕中文测试",
                "duration": 1,
                "media_asset_id": visual["id"],
                "layout": "full",
            },
            {
                "id": "two",
                "narration": "画中画与视频原音",
                "duration": 1,
                "media_asset_id": visual["id"],
                "presenter_asset_id": presenter["id"],
                "layout": "pip",
            },
        ],
    }
    updates = []

    async def progress(value, label):
        updates.append((value, label))

    result = await run_job({"id": "render-test", "operation": "render"}, project, store, progress)
    output = store.asset_path(result["asset_id"])
    info = inspect_media(output)
    assert info["width"] == 320 and info["height"] == 180 and info["has_audio"]
    assert abs(info["duration"] - 2) < 0.2
    assert [item[0] for item in updates] == sorted(item[0] for item in updates)
    # 第二镜有真实声音，确保画中画的原音没有被全片静音覆盖。
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "1.1",
            "-i",
            str(output),
            "-t",
            "0.3",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    assert any(raw)


@pytest.mark.asyncio
async def test_missing_visual_and_cross_project_asset_are_rejected(store, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("需要 FFmpeg")
    path = tmp_path / "image.png"
    Image.new("RGB", (50, 50)).save(path)
    asset = store.register_asset("other-project", path, "image")
    project = {
        "id": "project",
        "width": 320,
        "height": 180,
        "fps": 24,
        "scenes": [{"id": "s", "duration": 1, "media_asset_id": asset["id"]}],
    }

    async def progress(*args):
        pass

    with pytest.raises(ValueError, match="不属于"):
        await run_job({"id": "bad", "operation": "render"}, project, store, progress)


@pytest.mark.asyncio
async def test_generation_uses_snapshot_and_keeps_existing_media(store, tmp_path, monkeypatch):
    calls = []
    reloads = []
    module = ModuleType("pixelle_video.service")
    config_module = ModuleType("pixelle_video.config")
    config_module.config_manager = SimpleNamespace(reload=lambda: reloads.append(True))

    class FakeCore:
        async def __aenter__(self):
            assert len(reloads) == len(calls) + 1  # 每次生成都先读取另一进程保存的最新配置。
            return self

        async def __aexit__(self, *args):
            return None

        async def media(self, **kwargs):
            calls.append(kwargs)
            Image.new("RGB", (320, 180), "#123456").save(kwargs["output_path"])

    module.PixelleVideoCore = FakeCore
    monkeypatch.setitem(__import__("sys").modules, "pixelle_video.service", module)
    monkeypatch.setitem(__import__("sys").modules, "pixelle_video.config", config_module)
    scenes = create_demo_assets(store, "project", "tutorial")
    old_asset = scenes[0]["media_asset_id"]
    scenes[0]["prompt"] = "a small clock on a desk"
    project = {"id": "project", "width": 320, "height": 180, "scenes": scenes}

    async def progress(*args):
        pass

    result = await run_job(
        {
            "id": "gen",
            "operation": "generate_media",
            "scene_id": scenes[0]["id"],
            "params": {"workflow": "api/openai/gpt-image-2", "media_type": "image"},
        },
        project,
        store,
        progress,
    )
    assert len(calls) == 1 and calls[0]["image_path"] is None
    assert calls[0]["prompt_safety_retries"] == 0
    assert result["asset_id"] != old_asset
    assert store.asset_path(old_asset).exists()
    assert scenes[0]["media_asset_id"] == old_asset  # 引擎不能绕过存储层乐观锁修改快照。
    await run_job(
        {
            "id": "reference",
            "operation": "generate_media",
            "scene_id": scenes[0]["id"],
            "params": {
                "workflow": "api/openai/gpt-image-2",
                "media_type": "image",
                "use_reference": True,
            },
        },
        project,
        store,
        progress,
    )
    assert calls[1]["image_paths"] == [str(store.asset_path(old_asset))]


@pytest.mark.asyncio
async def test_generation_error_never_exposes_provider_key(store, monkeypatch):
    module = ModuleType("pixelle_video.service")
    config_module = ModuleType("pixelle_video.config")
    config_module.config_manager = SimpleNamespace(reload=lambda: None)

    class BrokenCore:
        async def __aenter__(self):
            raise RuntimeError("Authorization: Bearer sk-private; https://host/?token=private")

        async def __aexit__(self, *args):
            pass

    module.PixelleVideoCore = BrokenCore
    monkeypatch.setitem(__import__("sys").modules, "pixelle_video.service", module)
    monkeypatch.setitem(__import__("sys").modules, "pixelle_video.config", config_module)

    async def progress(*args):
        pass

    with pytest.raises(ValueError) as error:
        await run_job(
            {"id": "failed", "operation": "generate_audio", "scene_id": "one"},
            {"id": "p", "scenes": [{"id": "one", "narration": "你好"}]},
            store,
            progress,
        )
    assert "private" not in str(error.value)
    assert "核实上游任务" in str(error.value)
