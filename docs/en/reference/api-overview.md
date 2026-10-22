# API Overview

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **Legacy reference**: The original instructions, interfaces or examples below are retained for compatibility and history. They do not describe current FrameWeave web features or establish FrameWeave generation results. Use the [current overview](../index.md) and [configuration guide](../getting-started/configuration.md).

Pixelle-Video provides both Python SDK and HTTP REST API.

---

## Python SDK

### PixelleVideoCore

Main service class providing video generation functionality.

```python
from pixelle_video.service import PixelleVideoCore

pixelle = PixelleVideoCore()
await pixelle.initialize()
```

### generate_video()

Primary method for generating videos.

**Parameters**:

- `text` (str): Topic or complete script
- `mode` (str): Generation mode ("generate" or "fixed")
- `n_scenes` (int): Number of scenes
- `title` (str, optional): Video title
- `tts_workflow` (str): TTS workflow
- `media_workflow` (str): Media generation workflow (image or video)
- `frame_template` (str): Video template
- `template_params` (dict, optional): Custom template parameters
- `bgm_path` (str, optional): BGM file path
- `bgm_volume` (float): BGM volume (0.0-1.0)

**Returns**: `VideoResult` object

---

## HTTP REST API

Start the API server:

```bash
uv run uvicorn api.app:app --host 0.0.0.0 --port 8000
```

### Video Generation - Synchronous

`POST /api/video/generate/sync`

Generate video synchronously, waits until completion. Suitable for small videos (< 30 seconds).

**Request Body**:

```json
{
  "text": "Why you should develop a reading habit",
  "mode": "generate",
  "n_scenes": 5,
  "frame_template": "1080x1920/image_default.html",
  "template_params": {
    "accent_color": "#3498db",
    "background": "https://example.com/custom-bg.jpg"
  },
  "title": "The Power of Reading"
}
```

**Response**:

```json
{
  "success": true,
  "message": "Success",
  "video_url": "http://localhost:8000/api/files/xxx/final.mp4",
  "duration": 45.5,
  "file_size": 12345678
}
```

### Video Generation - Asynchronous

`POST /api/video/generate/async`

Generate video asynchronously, returns task ID immediately. Suitable for large videos.

**Response**:

```json
{
  "success": true,
  "message": "Task created successfully",
  "task_id": "abc123"
}
```

### Query Task Status

`GET /api/tasks/{task_id}`

**Response**:

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

## Request Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | string | Yes | Topic or complete script |
| `mode` | string | No | `"generate"` (AI generates) or `"fixed"` (use text as-is) |
| `n_scenes` | int | No | Number of scenes (1-20), only used in generate mode |
| `title` | string | No | Video title (auto-generated if not provided) |
| `frame_template` | string | No | Template path, e.g., `1080x1920/image_default.html` |
| `template_params` | object | No | Custom template parameters (colors, backgrounds, etc.) |
| `media_workflow` | string | No | Media workflow (image or video generation) |
| `tts_workflow` | string | No | TTS workflow |
| `ref_audio` | string | No | Reference audio path for voice cloning |
| `prompt_prefix` | string | No | Image style prefix |
| `bgm_path` | string | No | BGM file path |
| `bgm_volume` | float | No | BGM volume (0.0-1.0, default 0.3) |

---

## More Information

API documentation is also available via Swagger UI: `http://localhost:8000/docs`

