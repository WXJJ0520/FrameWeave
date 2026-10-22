"""项目持久化、乐观锁、素材隔离与任务结果冲突测试；全部使用临时目录。"""

import asyncio
from types import SimpleNamespace

import pytest
from PIL import Image

from frameweave.jobs import JobWorker
from frameweave.store import Store, StoreConflict, StoreNotFound, StoreValidation


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def scene(scene_id="scene-1", **values):
    result = {
        "id": scene_id,
        "title": "镜头",
        "narration": "中文旁白",
        "prompt": "一只猫",
        "duration": 4,
        "media_asset_id": None,
        "audio_asset_id": None,
        "presenter_asset_id": None,
        "layout": "full",
    }
    return dict(result, **values)


def asset(store, project, tmp_path, kind="image"):
    path = tmp_path / "示例.png"
    Image.new("RGB", (32, 32)).save(path)
    return store.register_asset(project["id"], path, kind)


def test_edit_lock_versions_and_restart(store):
    project = store.create_project("中文项目", [scene()])
    newer = store.update_project(project["id"], 1, {"title": "新标题"})
    assert newer["revision"] == 2
    with pytest.raises(StoreConflict):
        store.update_project(project["id"], 1, {"title": "旧标签页"})
    reopened = Store(store.root)
    assert reopened.get_project(project["id"])["title"] == "新标题"
    restored = reopened.restore_project(project["id"], 1, 2)
    assert restored["title"] == "中文项目" and restored["revision"] == 3
    assert len(reopened.list_versions(project["id"])) == 3


def test_single_scene_restore_preserves_other_edits(store):
    project = store.create_project(scenes=[scene("one"), scene("two")])
    edited = [scene("one", narration="变化一"), scene("two", narration="变化二")]
    store.update_project(project["id"], 1, {"scenes": edited})
    restored = store.restore_project(project["id"], 1, 2, "one")
    assert restored["scenes"][0]["narration"] == "中文旁白"
    assert restored["scenes"][1]["narration"] == "变化二"


def test_cross_project_and_wrong_kind_assets_rejected(store, tmp_path):
    first = store.create_project()
    second = store.create_project()
    image = asset(store, first, tmp_path)
    with pytest.raises(StoreValidation):
        store.update_project(second["id"], 1, {"scenes": [scene(media_asset_id=image["id"])]})
    with pytest.raises(StoreValidation):
        store.update_project(first["id"], 1, {"scenes": [scene(audio_asset_id=image["id"])]})
    assert "path" not in store.list_assets(first["id"])[0]
    with pytest.raises(StoreNotFound):
        store.asset_path("missing")
    with pytest.raises(StoreValidation):
        store.work_dir("../../outside")


def test_snapshot_result_does_not_overwrite_new_edit(store, tmp_path):
    project = store.create_project(scenes=[scene()])
    job = store.create_job(project["id"], "generate_media", "scene-1")
    store.update_project(project["id"], 1, {"title": "已经编辑"})
    output = asset(store, project, tmp_path)
    finished = store.finish_job(job["id"], {"asset_id": output["id"]})
    assert finished["result_applied"] is False
    assert store.get_project(project["id"])["title"] == "已经编辑"
    assert store.get_project(project["id"])["scenes"][0]["media_asset_id"] is None
    assert store.job_snapshot(job["id"])["revision"] == 1


def test_success_applies_asset_and_makes_version(store, tmp_path):
    project = store.create_project(scenes=[scene()])
    job = store.create_job(project["id"], "generate_audio", "scene-1")
    output = asset(store, project, tmp_path, "audio")
    finished = store.finish_job(job["id"], {"asset_id": output["id"], "duration": 5.2})
    current = store.get_project(project["id"])
    assert finished["result_applied"] is True
    assert current["revision"] == 2 and current["scenes"][0]["duration"] == 6


def test_restart_interrupts_running_only_and_blocks_duplicate(store):
    project = store.create_project(scenes=[scene()])
    running = store.create_job(project["id"], "generate_audio", "scene-1")
    with pytest.raises(StoreConflict):
        store.create_job(project["id"], "generate_audio", "scene-1")
    store.update_job(running["id"], status="running")
    queued = store.create_job(project["id"], "render")
    store.interrupt_running()
    assert store.get_job(running["id"])["status"] == "interrupted"
    assert store.get_job(queued["id"])["status"] == "queued"


def test_cancelled_job_keeps_late_asset_without_applying(store, tmp_path):
    project = store.create_project(scenes=[scene()])
    job = store.create_job(project["id"], "generate_media", "scene-1")
    store.update_job(job["id"], status="cancelled")
    store.update_job(job["id"], progress=90, stage="迟到回调")
    output = asset(store, project, tmp_path)
    finished = store.finish_job(job["id"], {"asset_id": output["id"]})
    assert finished["status"] == "cancelled" and finished["result_applied"] is False
    assert finished["result_asset_id"] == output["id"]
    assert store.get_project(project["id"])["revision"] == 1


@pytest.mark.asyncio
async def test_cancel_local_render_continues_next_job(store, tmp_path):
    project = store.create_project(scenes=[scene()])
    render_started = asyncio.Event()
    render_cancelled = asyncio.Event()
    second_completed = asyncio.Event()

    async def run_job(job, snapshot, current_store, progress):
        if job["operation"] == "render":
            render_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                render_cancelled.set()
                raise
        output = asset(current_store, project, tmp_path, "audio")
        second_completed.set()
        return {"asset_id": output["id"]}

    worker = JobWorker(store, SimpleNamespace(run_job=run_job))
    first = store.create_job(project["id"], "render")
    second = store.create_job(project["id"], "generate_audio", "scene-1")
    await worker.start()
    try:
        await asyncio.wait_for(render_started.wait(), timeout=2)
        cancelled = await worker.cancel(first["id"])
        await asyncio.wait_for(second_completed.wait(), timeout=2)
        await asyncio.sleep(0)
        assert cancelled["stage"] == "已取消本地合成"
        assert render_cancelled.is_set()
        assert store.get_job(first["id"])["status"] == "cancelled"
        assert store.get_job(second["id"])["status"] == "succeeded"
    finally:
        await worker.stop()
