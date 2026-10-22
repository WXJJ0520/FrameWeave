"""SQLite 项目与任务存储；原 Pixelle JSON 历史不会被覆盖。"""

from __future__ import annotations

import json
import math
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier() -> str:
    return uuid.uuid4().hex


class StoreNotFound(Exception):
    pass


class StoreConflict(Exception):
    pass


class StoreValidation(Exception):
    pass


class Store:
    """每次操作独立连接；写事务以 revision 检查与快照写入作为同一原子操作。"""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "frameweave.sqlite3"
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS versions (
                    project_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(project_id, revision)
                );
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, document TEXT NOT NULL,
                    snapshot TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            # sqlite 的连接上下文只负责事务，不会关闭文件句柄。
            connection.close()

    @staticmethod
    def _project(conn, project_id):
        row = conn.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise StoreNotFound("项目不存在")
        return json.loads(row["document"])

    @staticmethod
    def _write_project(conn, project):
        encoded = json.dumps(project, ensure_ascii=False)
        conn.execute(
            "INSERT OR REPLACE INTO projects VALUES (?, ?, ?)",
            (project["id"], encoded, project["updated_at"]),
        )
        conn.execute(
            "INSERT INTO versions VALUES (?, ?, ?, ?)",
            (project["id"], project["revision"], encoded, project["updated_at"]),
        )

    def create_project(self, title="未命名项目", scenes=None, **fields):
        stamp = now()
        project = {
            "id": identifier(),
            "title": title,
            "width": 720,
            "height": 1280,
            "fps": 24,
            "language": "zh-CN",
            "created_at": stamp,
            "updated_at": stamp,
            "revision": 1,
            "scenes": scenes or [],
            "final_asset_id": None,
            "rendered_revision": None,
        }
        project.update(
            {
                key: value
                for key, value in fields.items()
                if key in {"width", "height", "fps", "language"}
            }
        )
        with self._connect() as conn:
            self._write_project(conn, project)
        return project

    def list_projects(self):
        with self._connect() as conn:
            return [
                json.loads(row[0])
                for row in conn.execute("SELECT document FROM projects ORDER BY updated_at DESC")
            ]

    def get_project(self, project_id):
        with self._connect() as conn:
            return self._project(conn, project_id)

    def _validate_scenes(self, conn, project_id, scenes):
        seen = set()
        for scene in scenes:
            if scene["id"] in seen:
                raise StoreValidation("镜头 ID 不能重复")
            seen.add(scene["id"])
            for field, allowed in (
                ("media_asset_id", {"image", "video"}),
                ("audio_asset_id", {"audio"}),
                ("presenter_asset_id", {"image", "video"}),
            ):
                asset_id = scene.get(field)
                if not asset_id:
                    continue
                row = conn.execute(
                    "SELECT document FROM assets WHERE id=? AND project_id=?",
                    (asset_id, project_id),
                ).fetchone()
                if row is None or json.loads(row[0])["kind"] not in allowed:
                    raise StoreValidation("镜头引用的素材不存在、类型不匹配或属于其他项目")

    def update_project(self, project_id, revision, changes):
        allowed = {"title", "width", "height", "fps", "language", "scenes"}
        if set(changes) - allowed:
            raise StoreValidation("项目包含不支持的字段")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            project = self._project(conn, project_id)
            if project["revision"] != revision:
                raise StoreConflict("项目已更新，请重新载入后再保存；当前编辑内容尚未覆盖服务端")
            if "scenes" in changes:
                self._validate_scenes(conn, project_id, changes["scenes"])
            project.update(changes)
            project.update(revision=revision + 1, updated_at=now())
            self._write_project(conn, project)
        return project

    def list_versions(self, project_id):
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT revision, created_at, document FROM versions WHERE project_id=? ORDER BY revision DESC",
                (project_id,),
            )
            return [
                {"revision": row[0], "created_at": row[1], "title": json.loads(row[2])["title"]}
                for row in rows
            ]

    def restore_project(self, project_id, revision, expected_revision, scene_id=None):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._project(conn, project_id)
            if current["revision"] != expected_revision:
                raise StoreConflict("项目已更新，请重新载入再恢复")
            row = conn.execute(
                "SELECT document FROM versions WHERE project_id=? AND revision=?",
                (project_id, revision),
            ).fetchone()
            if row is None:
                raise StoreNotFound("历史版本不存在")
            historical = json.loads(row[0])
            if scene_id:
                old_scene = next(
                    (scene for scene in historical["scenes"] if scene["id"] == scene_id), None
                )
                position = next(
                    (i for i, scene in enumerate(current["scenes"]) if scene["id"] == scene_id),
                    None,
                )
                if old_scene is None or position is None:
                    raise StoreNotFound("当前或历史版本中不存在该镜头")
                current["scenes"][position] = old_scene
            else:
                current = historical
            current.update(revision=expected_revision + 1, updated_at=now())
            # 恢复产生新版本；只有恢复完整合成内容时才可沿用旧成片。
            if not scene_id and historical.get("rendered_revision") == revision:
                current["rendered_revision"] = current["revision"]
            self._validate_scenes(conn, project_id, current["scenes"])
            self._write_project(conn, current)
        return current

    def register_asset(self, project_id, path, kind, source="generated"):
        self.get_project(project_id)
        original = Path(path).resolve()
        if not original.is_file() or kind not in {"image", "video", "audio"}:
            raise StoreValidation("无效素材文件")
        asset_id = identifier()
        suffix = original.suffix.lower()
        if len(suffix) > 12 or not suffix.replace(".", "").isalnum():
            suffix = ".bin"
        destination = self.root / "assets" / project_id / f"{asset_id}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, destination)
        asset = {
            "id": asset_id,
            "project_id": project_id,
            "kind": kind,
            "filename": original.name,
            "url": f"/api/assets/{asset_id}",
            "source": source,
            "path": str(destination),
            "created_at": now(),
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO assets VALUES (?, ?, ?)",
                (asset_id, project_id, json.dumps(asset, ensure_ascii=False)),
            )
        return asset

    def get_asset(self, asset_id):
        with self._connect() as conn:
            row = conn.execute("SELECT document FROM assets WHERE id=?", (asset_id,)).fetchone()
            if row is None:
                raise StoreNotFound("素材不存在")
            return json.loads(row[0])

    def asset_path(self, asset_id) -> Path:
        path = Path(self.get_asset(asset_id)["path"]).resolve()
        # 只开放素材库文件，数据库中的意外/过期路径也不能用来读取其他目录。
        if not path.is_relative_to(self.root / "assets") or not path.is_file():
            raise StoreNotFound("素材文件不存在")
        return path

    @staticmethod
    def public_asset(asset):
        return {key: value for key, value in asset.items() if key != "path"}

    def list_assets(self, project_id):
        self.get_project(project_id)
        with self._connect() as conn:
            return [
                self.public_asset(json.loads(row[0]))
                for row in conn.execute(
                    "SELECT document FROM assets WHERE project_id=?", (project_id,)
                )
            ]

    def work_dir(self, job_id) -> Path:
        if not job_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in job_id
        ):
            raise StoreValidation("无效任务 ID")
        path = self.root / "work" / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_job(self, project_id, operation, scene_id=None, params=None):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._project(conn, project_id)
            if scene_id and not any(scene["id"] == scene_id for scene in snapshot["scenes"]):
                raise StoreNotFound("镜头不存在")
            if operation == "render" and not snapshot["scenes"]:
                raise StoreValidation("请先添加镜头")
            # 避免双击提交导致同一模型操作产生重复付费任务。
            for row in conn.execute("SELECT document FROM jobs WHERE project_id=?", (project_id,)):
                existing = json.loads(row[0])
                if (
                    existing["status"] in {"queued", "running"}
                    and existing["operation"] == operation
                    and existing.get("scene_id") == scene_id
                ):
                    raise StoreConflict("同类任务正在排队或执行，请等待已有任务完成")
            stamp = now()
            job = {
                "id": identifier(),
                "project_id": project_id,
                "scene_id": scene_id,
                "operation": operation,
                "params": params or {},
                "status": "queued",
                "progress": 0,
                "stage": "等待执行",
                "result_asset_id": None,
                "result_applied": None,
                "error": None,
                "created_at": stamp,
                "updated_at": stamp,
                "project_revision": snapshot["revision"],
            }
            conn.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
                (
                    job["id"],
                    project_id,
                    json.dumps(job, ensure_ascii=False),
                    json.dumps(snapshot, ensure_ascii=False),
                    stamp,
                ),
            )
        return job

    def get_job(self, job_id):
        with self._connect() as conn:
            row = conn.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise StoreNotFound("任务不存在")
            return json.loads(row[0])

    def job_snapshot(self, job_id):
        with self._connect() as conn:
            row = conn.execute("SELECT snapshot FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise StoreNotFound("任务不存在")
            return json.loads(row[0])

    def list_jobs(self, project_id=None):
        with self._connect() as conn:
            if project_id:
                self._project(conn, project_id)
                rows = conn.execute(
                    "SELECT document FROM jobs WHERE project_id=? ORDER BY created_at DESC",
                    (project_id,),
                )
            else:
                rows = conn.execute("SELECT document FROM jobs ORDER BY created_at DESC")
            return [json.loads(row[0]) for row in rows]

    def update_job(self, job_id, **changes):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise StoreNotFound("任务不存在")
            job = json.loads(row[0])
            # 取消后迟到的进度通知不能让任务重新变为运行中。
            if job["status"] == "cancelled" and changes.get("status") != "cancelled":
                return job
            job.update(changes, updated_at=now())
            conn.execute(
                "UPDATE jobs SET document=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), job_id),
            )
        return job

    def interrupt_running(self):
        for job in self.list_jobs():
            if job["status"] == "running":
                self.update_job(
                    job["id"],
                    status="interrupted",
                    stage="服务中断，未自动重复提交",
                    error="上次执行被中断。云端任务可能仍在运行；请确认供应商任务状态后再手动重试。",
                )

    def finish_job(self, job_id, result):
        """结果与项目快照一起提交；编辑后完成的旧任务只保留素材，不覆盖新编辑。"""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT document FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise StoreNotFound("任务不存在")
            job = json.loads(row[0])
            if job["status"] in {"succeeded", "failed", "interrupted"}:
                return job
            asset_id = result["asset_id"]
            asset_row = conn.execute(
                "SELECT document FROM assets WHERE id=? AND project_id=?",
                (asset_id, job["project_id"]),
            ).fetchone()
            if not asset_row:
                raise StoreValidation("生成结果素材未注册")
            asset_kind = json.loads(asset_row[0])["kind"]
            expected_kinds = {
                "render": {"video"},
                "generate_audio": {"audio"},
                "generate_media": {"image", "video"},
            }
            if asset_kind not in expected_kinds[job["operation"]]:
                raise StoreValidation("生成结果素材类型不匹配")
            project = self._project(conn, job["project_id"])
            too_long = job["operation"] != "render" and float(result.get("duration") or 0) > 60
            apply = (
                job["status"] != "cancelled"
                and project["revision"] == job["project_revision"]
                and not too_long
            )
            if apply:
                if job["operation"] == "render":
                    project["final_asset_id"] = asset_id
                    project["rendered_revision"] = project["revision"] + 1
                else:
                    scene = next(
                        scene for scene in project["scenes"] if scene["id"] == job["scene_id"]
                    )
                    scene[
                        "audio_asset_id"
                        if job["operation"] == "generate_audio"
                        else "media_asset_id"
                    ] = asset_id
                    if result.get("duration"):
                        duration = max(1, min(60, math.ceil(float(result["duration"]))))
                        scene["duration"] = (
                            max(scene["duration"], duration)
                            if job["operation"] == "generate_audio"
                            else duration
                        )
                project.update(revision=project["revision"] + 1, updated_at=now())
                self._write_project(conn, project)
            job.update(result_asset_id=asset_id, result_applied=apply, updated_at=now())
            if job["status"] != "cancelled":
                job.update(
                    status="succeeded",
                    progress=100,
                    stage="已完成" if apply else "素材已生成；项目已修改，未覆盖当前编辑",
                )
                if too_long:
                    job["stage"] = "素材超过单镜 60 秒上限，已保留素材；请拆分镜头后使用"
            conn.execute(
                "UPDATE jobs SET document=? WHERE id=?",
                (json.dumps(job, ensure_ascii=False), job_id),
            )
        return job
