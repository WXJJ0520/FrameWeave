# 镜织 FrameWeave v0.1 开发契约

<!-- Preserve the historical source and attribution. -->

> **历史实验契约**：下文记录早期项目与分镜实验接口，对应入口已经退出当前工作台；保留用于代码追溯，不是当前产品功能承诺。当前能力见[文档首页](zh/index.md)。

本文件记录新工作台内部接口；旧 Streamlit 与 Pixelle API 保持兼容。新增代码采用 UTF-8 和中文注释。

## 数据

- Project: `id, title, width, height, fps, language(zh-CN/en), created_at, updated_at, revision, scenes[], final_asset_id?, rendered_revision?`。
- Scene: `id, title, narration, prompt, duration(1..60), media_asset_id?, audio_asset_id?, presenter_asset_id?, layout(full/pip)`。
- Asset: `id, project_id, kind(image/video/audio), filename, url, source(upload/demo/generated/render)`；内部 `path` 绝不通过 API 返回。
- Job: `id, project_id, scene_id?, operation(render/generate_media/generate_audio), params, status(queued/running/succeeded/failed/interrupted/cancelled), progress(0..100), stage, result_asset_id?, error?, created_at, updated_at, result_applied?`。
- 项目更新使用 revision 乐观锁，冲突返回 409；所有用户保存和生成结果应用均保留版本快照。

## HTTP /api

- GET `/health` -> `{status, product, version, ffmpeg_available}`
- GET `/projects` -> `Project[]`
- POST `/projects` body `{title?, recipe_id?}` -> `Project`；配方 `blank/tutorial/knight-cat/comparison`，示例素材须明确标注本地示意图。
- GET `/projects/{id}` -> `Project`
- PATCH `/projects/{id}` body `{revision, title?, width?, height?, fps?, language?, scenes?}` -> `Project`
- GET `/projects/{id}/assets` -> `Asset[]`
- POST `/projects/{id}/assets` 原始二进制上传，`X-Filename` 为 encodeURIComponent 文件名、`Content-Type` 为文件 MIME -> `Asset`
- GET `/assets/{asset_id}` -> 经过注册的素材文件，不允许任意文件路径。
- GET `/projects/{id}/versions` -> `[{revision, created_at, title}]`
- POST `/projects/{id}/restore` body `{revision:历史版本, expected_revision:当前版本, scene_id?:单镜恢复}` -> `Project`
- GET `/projects/{id}/export` -> ZIP（project.json、assets/，排除密钥/绝对路径/任务日志）。
- GET `/recipes` -> `[{id,name,description}]`
- GET `/models` -> `[{id,label,kind}]`，从已有 API 模型注册表读取；失败返回空数组，不阻止离线使用。
- GET `/jobs?project_id=...` -> `Job[]`
- POST `/projects/{id}/jobs` body `{operation, scene_id?, params?}` -> `Job`（202）；生成视频参数 params `{workflow, media_type, duration?}`，音频 `{voice?}`。
- POST `/jobs/{id}/cancel` -> `Job`；已开始的云生成不承诺中止供应商计算。

## 后端与引擎边界

`frameweave.engine.run_job(job, project_snapshot, store, progress)` 为 async，返回 `{asset_id, duration?}`。`progress(percent, stage)` 为 async，必须在合成各阶段调用。

Store 提供：`get_asset(id)` 内部完整记录，`asset_path(id) -> Path`，`register_asset(project_id, path, kind, source='generated') -> dict`（复制到项目素材库），`work_dir(job_id) -> Path`。

`frameweave.engine.create_demo_assets(store, project_id, recipe_id)` 返回三个 scene 字典（本地 Pillow 示意图，无外部请求）。`frameweave.engine.inspect_media(path)` 返回 `{kind, duration?, width?, height?}` 或抛 ValueError；上传需验证实际文件。

作业保存提交时的项目快照。完成时仅在项目 revision 未变化时自动应用生成结果；变化则保留结果素材并设置 result_applied=false。重启将 running 标记 interrupted，不自动重新付费提交。queued 可继续执行。取消不能删除已上传/已完成素材。

## 运行

后端入口 `python -m frameweave`，默认 `127.0.0.1:8765`；数据默认 `data/frameweave`，支持 `FRAMEWEAVE_DATA_DIR`；静态前端 `studio/dist` 挂载在 `/`。开发前端 Vite 代理 `/api` 到 8765。
