"""FrameWeave 独立本地 API；与旧 Streamlit 服务共存。"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from . import __version__
from .jobs import JobWorker
from .models import CreateJob, CreateProject, RestoreProject, UpdateProject
from .store import Store, StoreConflict, StoreNotFound, StoreValidation

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
RECIPES = [
    {"id": "blank", "name": "空白项目", "description": "从自己的脚本和实拍素材开始。"},
    {
        "id": "tutorial",
        "name": "AI 小白教学",
        "description": "问题、操作、结果三镜结构，附本地生成示意图。",
    },
    {
        "id": "knight-cat",
        "name": "骑士小猫故事",
        "description": "角色、挑战、结局三镜结构，附本地生成示意图。",
    },
    {
        "id": "comparison",
        "name": "前后效果对比",
        "description": "原始效果、处理过程、最终效果三镜结构，附本地生成示意图。",
    },
]


def create_app(data_dir=None, engine_module=None):
    store = Store(
        data_dir or os.environ.get("FRAMEWEAVE_DATA_DIR", str(REPO_ROOT / "data" / "frameweave"))
    )
    engine = engine_module or importlib.import_module("frameweave.engine")
    worker = JobWorker(store, engine)

    @asynccontextmanager
    async def lifespan(app):
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(title="镜织 FrameWeave", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.worker = worker

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        # 本地工具没有账号系统，拒绝其他网站在浏览器内跨站触发生成。
        origin = request.headers.get("origin")
        if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
                return JSONResponse(
                    status_code=403, content={"detail": "仅允许本机工作台发起修改请求"}
                )
        return await call_next(request)

    @app.exception_handler(StoreNotFound)
    async def missing(request, error):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(StoreConflict)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(StoreValidation)
    async def invalid(request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "product": "镜织 FrameWeave",
            "version": __version__,
            "ffmpeg_available": shutil.which("ffmpeg") is not None,
            "ffprobe_available": shutil.which("ffprobe") is not None,
        }

    @app.get("/api/recipes")
    async def recipes():
        return RECIPES

    @app.get("/api/models")
    async def models():
        def load():
            try:
                from pixelle_video.services.api_media import APIProviderMediaService

                workflows = APIProviderMediaService({}).list_workflows()
                return [
                    {"id": item["key"], "label": item["display_name"], "kind": item["media_type"]}
                    for item in workflows
                ]
            except Exception:
                # 缺少云端依赖/配置不影响离线项目编辑；不把配置异常原文送到浏览器。
                return []

        return await asyncio.to_thread(load)

    @app.get("/api/projects")
    async def projects():
        return store.list_projects()

    @app.post("/api/projects", status_code=201)
    async def create_project(body: CreateProject):
        project = store.create_project(body.title)
        if body.recipe_id != "blank":
            scenes = await asyncio.to_thread(
                engine.create_demo_assets, store, project["id"], body.recipe_id
            )
            project = store.update_project(project["id"], project["revision"], {"scenes": scenes})
        return project

    @app.get("/api/projects/{project_id}")
    async def project_detail(project_id: str):
        return store.get_project(project_id)

    @app.patch("/api/projects/{project_id}")
    async def update_project(project_id: str, body: UpdateProject):
        changes = body.model_dump(exclude_unset=True, exclude={"revision"}, exclude_none=True)
        return store.update_project(project_id, body.revision, changes)

    @app.get("/api/projects/{project_id}/versions")
    async def versions(project_id: str):
        return store.list_versions(project_id)

    @app.post("/api/projects/{project_id}/restore")
    async def restore(project_id: str, body: RestoreProject):
        return store.restore_project(
            project_id, body.revision, body.expected_revision, body.scene_id
        )

    @app.get("/api/projects/{project_id}/assets")
    async def assets(project_id: str):
        return store.list_assets(project_id)

    @app.post("/api/projects/{project_id}/assets", status_code=201)
    async def upload(project_id: str, request: Request):
        store.get_project(project_id)
        raw_name = unquote(request.headers.get("x-filename", "upload.bin"))
        filename = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip(". ")
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if (
            not filename
            or len(filename) > 200
            or any(ord(char) < 32 for char in filename)
            or any(char in filename for char in '<>:"|?*')
            or filename.split(".", 1)[0].upper() in reserved
        ):
            raise HTTPException(400, "无效文件名")
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "单个素材不能超过 200 MB")
            except ValueError:
                raise HTTPException(400, "无效文件大小")
        # 流式写入限制总量，不能只相信扩展名、MIME 或 Content-Length。
        temp_root = store.root / "uploads"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="upload-", dir=temp_root) as temporary:
            path = Path(temporary) / filename
            size = 0
            with path.open("wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "单个素材不能超过 200 MB")
                    output.write(chunk)
            if not size:
                raise HTTPException(400, "上传文件为空")
            try:
                info = await asyncio.to_thread(engine.inspect_media, path)
            except (ValueError, OSError) as error:
                raise HTTPException(
                    415, "无法识别素材，请上传有效的图片、音频或视频文件"
                ) from error
            asset = await asyncio.to_thread(
                store.register_asset, project_id, path, info["kind"], "upload"
            )
        return store.public_asset(asset)

    @app.get("/api/assets/{asset_id}")
    async def asset_content(asset_id: str):
        asset = store.get_asset(asset_id)
        return FileResponse(
            store.asset_path(asset_id),
            filename=asset["filename"],
            content_disposition_type="inline",
        )

    @app.get("/api/jobs")
    async def jobs(project_id: str | None = None):
        return store.list_jobs(project_id)

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    async def create_job(project_id: str, body: CreateJob):
        job = store.create_job(
            project_id, body.operation, body.scene_id, body.params.model_dump(exclude_none=True)
        )
        worker.notify()
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        return await worker.cancel(job_id)

    @app.get("/api/projects/{project_id}/export")
    async def export(project_id: str):
        project = store.get_project(project_id)
        export_root = store.root / "exports"
        export_root.mkdir(exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix="frameweave-", suffix=".zip", dir=export_root)
        os.close(handle)
        output = Path(temporary)

        def package():
            # 导出仅收集项目与已注册素材；没有运行配置、日志或数据库内部路径。
            entries = []
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for asset in store.list_assets(project_id):
                    path = store.asset_path(asset["id"])
                    relative = f"assets/{asset['id']}{path.suffix}"
                    archive.write(path, relative)
                    entries.append(
                        {
                            "id": asset["id"],
                            "kind": asset["kind"],
                            "source": asset["source"],
                            "filename": asset["filename"],
                            "file": relative,
                        }
                    )
                archive.writestr(
                    "project.json",
                    json.dumps(
                        {
                            "format": "frameweave-project",
                            "version": 1,
                            "project": project,
                            "assets": entries,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                archive.writestr(
                    "README.txt",
                    "镜织 FrameWeave 项目素材包。project.json 保存镜头、旁白和提示词；assets/ 保存素材。\n不含 API 密钥或供应商配置。当前版本不提供 ZIP 自动导入。\n",
                )

        try:
            await asyncio.to_thread(package)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return FileResponse(
            output,
            media_type="application/zip",
            filename=f"frameweave-{project_id[:8]}.zip",
            background=BackgroundTask(output.unlink, missing_ok=True),
        )

    @app.get("/{relative_path:path}", include_in_schema=False)
    async def frontend(relative_path: str):
        if relative_path == "api" or relative_path.startswith("api/"):
            raise HTTPException(404, "API 不存在")
        dist = (REPO_ROOT / "studio" / "dist").resolve()
        target = (dist / relative_path).resolve()
        if target.is_relative_to(dist) and target.is_file():
            return FileResponse(target)
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "前端尚未构建。请在 studio 目录运行 npm install 和 npm run build；API 文档位于 /docs。"
            },
        )

    return app
