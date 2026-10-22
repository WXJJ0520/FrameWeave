# API 概览

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **历史兼容参考**：下文保留原项目的操作、接口或示例记录，不代表镜织当前 Web 功能或实测结果。当前用法以[镜织文档首页](../index.md)、[配置指南](../getting-started/configuration.md)为准。

Pixelle-Video 提供 Python SDK 和 HTTP REST API 两种方式。

---

## Python SDK

### PixelleVideoCore

主要服务类，提供视频生成功能。

```python
from pixelle_video.service import PixelleVideoCore

pixelle = PixelleVideoCore()
await pixelle.initialize()
```

### generate_video()

生成视频的主要方法。

**参数**:

- `text` (str): 主题或完整文案
- `mode` (str): 生成模式 ("generate" 或 "fixed")
- `n_scenes` (int): 分镜数量
- `title` (str, optional): 视频标题
- `tts_workflow` (str): TTS 工作流
- `media_workflow` (str): 媒体生成工作流（图像或视频）
- `frame_template` (str): 视频模板
- `template_params` (dict, optional): 模板自定义参数
- `bgm_path` (str, optional): BGM 文件路径
- `bgm_volume` (float): BGM 音量 (0.0-1.0)

**返回**: `VideoResult` 对象

---

## HTTP REST API

启动 API 服务器：

```bash
uv run uvicorn api.app:app --host 0.0.0.0 --port 8000
```

### 视频生成 - 同步

`POST /api/video/generate/sync`

同步生成视频，等待完成后返回结果。适合小视频（< 30 秒）。

**请求体**:

```json
{
  "text": "为什么要养成阅读习惯",
  "mode": "generate",
  "n_scenes": 5,
  "frame_template": "1080x1920/image_default.html",
  "template_params": {
    "accent_color": "#3498db",
    "background": "https://example.com/custom-bg.jpg"
  },
  "title": "阅读的力量"
}
```

**响应**:

```json
{
  "success": true,
  "message": "Success",
  "video_url": "http://localhost:8000/api/files/xxx/final.mp4",
  "duration": 45.5,
  "file_size": 12345678
}
```

### 视频生成 - 异步

`POST /api/video/generate/async`

异步生成视频，立即返回任务 ID。适合大视频。

**响应**:

```json
{
  "success": true,
  "message": "Task created successfully",
  "task_id": "abc123"
}
```

### 查询任务状态

`GET /api/tasks/{task_id}`

**响应**:

```json
{
  "task_id": "abc123",
  "status": "completed",
  "result": {
    "video_url": "http://localhost:8000/api/files/xxx/final.mp4",
    "duration": 45.5,
    "file_size": 12345678
  }
}
```

---

## 请求参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | 是 | 主题或完整文案 |
| `mode` | string | 否 | `"generate"` (AI 生成) 或 `"fixed"` (固定文案) |
| `n_scenes` | int | 否 | 分镜数量 (1-20)，仅 generate 模式有效 |
| `title` | string | 否 | 视频标题（不填则自动生成） |
| `frame_template` | string | 否 | 模板路径，如 `1080x1920/image_default.html` |
| `template_params` | object | 否 | 模板自定义参数（颜色、背景等） |
| `media_workflow` | string | 否 | 媒体工作流（图像或视频生成） |
| `tts_workflow` | string | 否 | TTS 工作流 |
| `ref_audio` | string | 否 | 声音克隆参考音频路径 |
| `prompt_prefix` | string | 否 | 图像风格前缀 |
| `bgm_path` | string | 否 | BGM 文件路径 |
| `bgm_volume` | float | 否 | BGM 音量 (0.0-1.0，默认 0.3) |

---

## 更多信息

API 文档也可通过 Swagger UI 访问：`http://localhost:8000/docs`

