"""端到端离线验收：API、SQLite、真实 FFmpeg 和可下载项目包一起验证。"""

import io
import json
import shutil
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from frameweave.app import create_app
from frameweave.engine import inspect_media


def wait_for_job(client, project_id):
    """轮询真实后台作业，设截止时间避免测试无限等待。"""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get("/api/jobs", params={"project_id": project_id}).json()[0]
        if job["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.05)
    pytest.fail("真实合成任务在 30 秒内未完成")


def test_demo_edit_render_restore_export_and_restart(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("需要 FFmpeg 执行端到端合成验收")
    data = tmp_path / "data"
    with TestClient(create_app(data_dir=data)) as client:
        response = client.post(
            "/api/projects", json={"title": "中文工作流回归", "recipe_id": "tutorial"}
        )
        assert response.status_code == 201
        project = response.json()
        project_id = project["id"]
        scenes = project["scenes"]
        for scene in scenes:
            scene["duration"] = 1
        scenes = list(reversed(scenes))
        response = client.patch(
            f"/api/projects/{project_id}",
            json={
                "revision": project["revision"],
                "width": 320,
                "height": 240,
                "fps": 24,
                "scenes": scenes,
            },
        )
        assert response.status_code == 200
        saved = response.json()
        response = client.post(f"/api/projects/{project_id}/jobs", json={"operation": "render"})
        assert response.status_code == 202
        job = wait_for_job(client, project_id)
        assert job["status"] == "succeeded", job.get("error")
        assert job["result_applied"]
        rendered = client.get(f"/api/projects/{project_id}").json()
        assert rendered["rendered_revision"] == rendered["revision"]
        response = client.get(f"/api/assets/{rendered['final_asset_id']}")
        assert response.status_code == 200
        video = tmp_path / "actual-export.mp4"
        video.write_bytes(response.content)
        assert abs(inspect_media(video)["duration"] - 3) < 0.2

        exported = client.get(f"/api/projects/{project_id}/export")
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            document = archive.read("project.json").decode("utf-8")
            package = json.loads(document)
            assert package["project"]["title"] == "中文工作流回归"
            assert str(data) not in document
            assert all(
                not name.startswith(("/", "\\")) and ".." not in name for name in archive.namelist()
            )
            assert all(item["file"] in archive.namelist() for item in package["assets"])
        restored = client.post(
            f"/api/projects/{project_id}/restore",
            json={
                "revision": saved["revision"],
                "expected_revision": rendered["revision"],
            },
        )
        assert restored.status_code == 200
        final_revision = restored.json()["revision"]

    # 新服务实例仍能找到保存的项目、历史版本和成品素材，不依赖进程内字典。
    with TestClient(create_app(data_dir=data)) as restarted:
        project = restarted.get(f"/api/projects/{project_id}").json()
        assert project["revision"] == final_revision
        assert project["scenes"][0]["id"] == scenes[0]["id"]
        assert restarted.get(f"/api/assets/{rendered['final_asset_id']}").status_code == 200
        assert len(restarted.get(f"/api/projects/{project_id}/versions").json()) >= 4
