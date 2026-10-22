"""单工作线程队列；保留云任务中断记录，不猜测供应商是否已经收费。"""

from __future__ import annotations

import asyncio
import re

from .store import StoreConflict


def public_error(error: Exception) -> str:
    # 供应商 SDK 有时把请求头放进异常，返回浏览器前统一遮蔽常见密钥形式。
    message = str(error)
    message = re.sub(r"(?i)bearer\s+[^\s,'\"]+", "Bearer [已隐藏]", message)
    message = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[已隐藏密钥]", message)
    message = re.sub(
        r"(?i)(api[_-]?key|access[_-]?token|authorization)([=:\s]+)[^\s,;&'\"]+",
        r"\1\2[已隐藏]",
        message,
    )
    return message[:1600] or "任务执行失败，请检查模型配置和输入素材。"


class JobWorker:
    def __init__(self, store, engine):
        self.store = store
        self.engine = engine
        self._wake = asyncio.Event()
        self._runner = None
        self._execution = None
        self._job_id = None
        self._stopping = False

    async def start(self):
        self.store.interrupt_running()
        self._stopping = False
        self._runner = asyncio.create_task(self._loop(), name="frameweave-single-worker")
        self._wake.set()

    def notify(self):
        self._wake.set()

    async def stop(self):
        self._stopping = True
        if self._job_id:
            self.store.update_job(
                self._job_id,
                status="interrupted",
                stage="服务关闭，未自动重复提交",
                error="执行被中断。云端请求可能仍在处理，请确认供应商状态。",
            )
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass

    async def cancel(self, job_id):
        job = self.store.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            raise StoreConflict("任务已结束，无法取消")
        # 不取消正在等待的 SDK 线程：它可能还会返回收费结果。保留结果但不应用，
        # 也不启动并发替代任务，确保这个进程始终只有一项实际生成操作。
        stage = (
            "已停止应用结果；云端计算可能仍在继续" if job["status"] == "running" else "已取消排队"
        )
        if job["operation"] == "render" and job["status"] == "running":
            stage = "已取消本地合成"
        result = self.store.update_job(job_id, status="cancelled", stage=stage)
        if job_id == self._job_id and job["operation"] == "render" and self._execution:
            # 本地 FFmpeg 可确切终止；云生成保持等待，避免丢失已经收费的结果。
            self._execution.cancel()
        return result

    async def _loop(self):
        while not self._stopping:
            queued = [job for job in reversed(self.store.list_jobs()) if job["status"] == "queued"]
            if not queued:
                self._wake.clear()
                await self._wake.wait()
                continue
            job = queued[0]
            self._job_id = job["id"]
            self.store.update_job(job["id"], status="running", stage="开始执行")

            async def progress(percent, stage):
                self.store.update_job(
                    job["id"], progress=max(0, min(99, int(percent))), stage=str(stage)[:300]
                )

            try:
                self._execution = asyncio.create_task(
                    self.engine.run_job(
                        job, self.store.job_snapshot(job["id"]), self.store, progress
                    ),
                    name=f"frameweave-job-{job['id']}",
                )
                result = await self._execution
                self.store.finish_job(job["id"], result)
            except asyncio.CancelledError:
                if self._stopping:
                    raise
                # 取消单个本地任务后继续队列，不取消整个后台工作器。
            except Exception as error:
                self.store.update_job(
                    job["id"], status="failed", stage="执行失败", error=public_error(error)
                )
            finally:
                self._job_id = None
                self._execution = None
