# FrameWeave troubleshooting

<!-- Locate the failing stage before interpreting status codes or catalog results. -->

Identify whether the failure occurred during startup, model discovery, asset analysis, speech, video generation or composition. A status code alone does not establish a single cause; check the service used by that stage.

## The workspace does not open

| Symptom | What to check |
| --- | --- |
| Missing frontend or build output | Run `npm --prefix studio ci` and `npm --prefix studio run build` in the project root |
| Build reports `crypto.getRandomValues is not a function` | Check the active runtime with `node --version` and use the documented Node.js 22; old Node 16 does not meet the current build requirements |
| Port 8765 is occupied | Inspect the existing service or choose another main port with `FRAMEWEAVE_PORT`; it must differ from 8501 |
| Port 8501 is occupied or ownership is unclear | Preserve the process and check whether it belongs to this checkout; normally exit its original terminal before using the unified launcher |
| Embedded creator page cannot connect | Open local port 8501 separately, confirm the creator service is running, then reload the tool |
| Missing Python dependencies | Use `uv sync --frozen` in the project environment instead of mixing Python environments |

Start with `uv run python -m frameweave` and open [127.0.0.1:8765](http://127.0.0.1:8765). ComfyUI and RunningHub workflow services are not required.

## URLs, credentials and model catalogs

- **401 / 403**: check the selected provider's credentials, account access, relay authentication and model permissions. Do not substitute a key from an unrelated group.
- **404**: verify the Base URL and implemented routes. Do not append `/v1` indiscriminately to providers using different protocols.
- **502 / 503 / 504**: inspect relay or proxy upstream availability. These codes alone do not establish an invalid key.
- **Connection or read timeout**: check the URL, network and selected proxy. For generation, distinguish submission, task waiting and result retrieval.
- **Empty or invalid catalog**: reload and save after changing the URL, key or proxy. Use explicit manual maintenance when discovery is unsupported.

A successful catalog query does not verify generation access. A model returned by the endpoint may still lack an implemented presenter or video adapter; do not assume all task types are interchangeable.

## Custom media reports missing settings or model selection

Configure the vision provider under Image & video → OpenAI / DashScope, load and save its catalog, then choose the provider and an explicit vision model in Custom media. If the connection is configured but its catalog is missing, use “Load and save” in step 2; the step 3 prompt can take you back to model selection. Vision settings do not automatically inherit the text model key.

After saving, first use Previous/Next or another page interaction to rerender with updated settings. If a full reload is still needed, preserve important scripts first; reloading may clear session drafts.

The selected model must accept images. Raising the video sample limit to 8 / 16 / 32 frames increases coverage but does not guarantee brief-action detection or audio transcription. The upload limit is 1 GB per video; reduce vision images exceeding 32 MB or 64 million pixels.

## Speech fails or Edge TTS returns 403

Edge TTS is an online service even though the request starts locally. Update the project's locked dependencies, restart the runtime normally, and preview the selected voice separately. This stage does not use Grok or OpenAI keys.

If the service continues to reject or time out, retain the stage and status information and check connectivity and service availability. The current web interface does not fall back to legacy TTS workflows.

## Presenter or video generation fails

1. Confirm support for the supplied character image, audio or reference video. Grok / Muse do not replace presenter or motion-transfer capabilities.
2. Check the model's duration, aspect ratio, resolution and media format limits.
3. If a task was submitted but no valid video was returned, inspect its provider-side status using the task ID before resubmitting.
4. If only History persistence or display failed, check the already-generated output first.

Reference voice does not guarantee exact lip sync. Text generation or model discovery through a relay does not establish that the relay implements the selected video protocol.

## Templates, subtitles or composition fail

- Run `ffmpeg -version` and `ffprobe -version` in the application's runtime environment and confirm both are on `PATH`.
- Install the renderer with `uv run playwright install chromium`; Linux may also need the system packages described in [installation](getting-started/installation.md).
- Install fonts covering the required characters, such as `fonts-noto-cjk` for Chinese, then restart affected processes normally.
- Check output write access, free disk space and source-file availability.

## Long-video duration differs or media repeats

Minutes are a planning budget rather than an exact duration guarantee. Check speech speed, the supplied script length and the measured duration. Insufficient assets may repeat, short footage may loop, and Quick creation clips may hold their final frame. Custom media uses time-based excerpts rather than sentence-level semantic localization.

Failed long videos do not currently resume automatically. Check the services with a short video before increasing scene count.

## What information helps a bug report?

Record the tool, failing stage, status, selected model, application version or commit, and minimal reproduction steps. Remove keys, authenticated URLs and private media before sharing logs. Do not present a FrameWeave-specific failure as a confirmed upstream defect.

## Reference and thanks

FrameWeave builds on [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video). Thanks to its contributors. The project retains Apache-2.0; see the repository's `LICENSE` and `NOTICE`.
