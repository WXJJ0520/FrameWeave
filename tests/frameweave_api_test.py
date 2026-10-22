"""API 使用真实存储与图像检查、隔离生成引擎，验证上传和脱敏导出。"""

import asyncio
import io
import json
import time
import zipfile
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from frameweave.app import create_app
from frameweave.engine import create_demo_assets, inspect_media


@pytest.fixture
def client(tmp_path):
    async def run_job(job, snapshot, store, progress):
        await progress(20, "离线测试引擎")
        await asyncio.sleep(0.02)
        image = store.work_dir(job["id"]) / "generated.png"
        Image.new("RGB", (32, 32)).save(image)
        item = store.register_asset(snapshot["id"], image, "image")
        return {"asset_id": item["id"]}

    engine = SimpleNamespace(
        run_job=run_job, inspect_media=inspect_media, create_demo_assets=create_demo_assets
    )
    with TestClient(create_app(tmp_path / "data", engine)) as value:
        yield value


def test_create_edit_demo_and_conflict(client):
    response = client.post("/api/projects", json={"title": "中文测试", "recipe_id": "tutorial"})
    assert response.status_code == 201
    project = response.json()
    assert len(project["scenes"]) == 3
    assert all(
        item["source"] == "demo"
        for item in client.get(f"/api/projects/{project['id']}/assets").json()
    )
    updated = client.patch(
        f"/api/projects/{project['id']}", json={"revision": project["revision"], "title": "新标题"}
    )
    assert updated.status_code == 200
    assert (
        client.patch(
            f"/api/projects/{project['id']}",
            json={"revision": project["revision"], "title": "过期"},
        ).status_code
        == 409
    )
    assert client.get("/api/projects/missing").status_code == 404
    assert client.get("/api/nonexistent").status_code == 404


def test_upload_checks_content_and_export_omits_internal_paths(client):
    project = client.post("/api/projects", json={}).json()
    endpoint = f"/api/projects/{project['id']}/assets"
    invalid = client.post(endpoint, content=b"not a real png", headers={"X-Filename": "fake.png"})
    assert invalid.status_code == 415
    assert (
        client.post(endpoint, content=b"content", headers={"X-Filename": "CON.png"}).status_code
        == 400
    )
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="PNG")
    response = client.post(
        endpoint, content=buffer.getvalue(), headers={"X-Filename": quote("本地图片.png")}
    )
    assert response.status_code == 201
    item = response.json()
    assert "path" not in item and item["filename"] == "本地图片.png"
    assert client.get(item["url"]).status_code == 200
    archive = client.get(f"/api/projects/{project['id']}/export")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
        manifest = json.loads(package.read("project.json"))
        assert "path" not in manifest["assets"][0]
        assert manifest["assets"][0]["file"].startswith("assets/")
        assert not any("config" in name or "sqlite" in name for name in package.namelist())
        assert str(client.app.state.store.root) not in package.read("project.json").decode("utf-8")


def test_job_whitelist_and_worker(client):
    project = client.post("/api/projects", json={"recipe_id": "tutorial"}).json()
    endpoint = f"/api/projects/{project['id']}/jobs"
    scene = project["scenes"][0]
    invalid = client.post(
        endpoint,
        json={
            "operation": "generate_media",
            "scene_id": scene["id"],
            "params": {"workflow": "api/xai/test", "api_key": "must-not-save"},
        },
    )
    assert invalid.status_code == 422
    response = client.post(
        endpoint,
        json={
            "operation": "generate_media",
            "scene_id": scene["id"],
            "params": {"workflow": "api/xai/test", "media_type": "image"},
        },
    )
    assert response.status_code == 202
    job_id = response.json()["id"]
    for _ in range(50):
        job = next(item for item in client.get("/api/jobs").json() if item["id"] == job_id)
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded" and job["result_applied"] is True
    assert "snapshot" not in job


def test_upload_limit_and_external_origin(client, monkeypatch):
    project = client.post("/api/projects", json={}).json()
    monkeypatch.setattr("frameweave.app.MAX_UPLOAD_BYTES", 8)
    response = client.post(
        f"/api/projects/{project['id']}/assets",
        content=b"0123456789",
        headers={"X-Filename": "a.png"},
    )
    assert response.status_code == 413
    assert (
        client.post("/api/projects", json={}, headers={"Origin": "https://example.org"}).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/projects/{project['id']}", json={"revision": 1, "width": 721}
        ).status_code
        == 422
    )
