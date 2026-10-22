# FrameWeave · 镜织

<!-- Describe the current product here; legacy workflow documents have their own reference section. -->

**Turn ideas, scripts and media into a complete video.**

FrameWeave is a local video creation workspace for creators, AI educators and individual developers. Start with a topic to generate scripts and visuals, or upload recordings and images for AI-assisted understanding and narration. The workspace brings together speech, templates, background music and video composition.

![FrameWeave white workspace and three-step creation flow](../assets/frameweave-creation-steps.jpg)

## Choose a creation tool

| Tool | What it does | What to prepare |
| --- | --- | --- |
| Quick creation | Create short videos or chapter-based 5 / 8 / 10-minute videos from a topic or full script | A topic or script, text and visual model APIs |
| Digital presenters | Combine the first character image with speech synthesized from text | A character image, narration text and an API supporting reference voice |
| Image-to-video | Animate a first-frame image with a prompt | An image, motion instructions and a compatible API |
| Custom media | Understand media, write narration, match assets and compose a video | Recorded footage, screen recordings or images, plus content instructions |
| Motion transfer | Combine a character image with a reference action video | Both inputs and an integrated video-editing API |
| History | Browse and filter existing tasks and results | Generated records |
| Settings | Manage provider URLs, credentials, model catalogs and proxies by purpose | The services you actually use |

All five creation tools share three steps: **content and assets → visuals and settings → preview and generation**. Chinese is the default, with an English switch in the upper-right corner. Step navigation and switching between open tools retain session inputs; reloading or closing a page may clear drafts.

## From short clips to longer videos

Quick creation and Custom media support **5 / 8 / 10-minute** targets. FrameWeave estimates chapters, scenes and script length, organizes narration, generates visuals or matches existing media, then assembles one output. A supplied script is preserved without padding or repetition to reach a duration.

Custom media uses original images and footage by default. Enabling image animation adds video API calls for matched images. Video understanding samples up to 8 / 16 / 32 frames locally and supports OpenAI-compatible vision APIs and DashScope. It does not transcribe original audio or guarantee detection of a brief action.

Long videos combine multiple scenes rather than extending a model's per-request limit. Duration is a planning target and the final file is measured. Automatic resume of an entire failed long-video job is not implemented.

## Get started

1. Follow [installation](getting-started/installation.md) to prepare Python, uv, Node.js, FFmpeg and Chromium.
2. Configure the services you need and load/save their catalogs in [model settings](getting-started/configuration.md).
3. Follow [your first video](getting-started/quick-start.md), using a small scene count to check your services.
4. Read the [workspace guide](user-guide/web-ui.md), [FAQ](faq.md) or [troubleshooting](troubleshooting.md).

Run from the project root:

```bash
# Start the local workspace and its creator-page service.
uv run python -m frameweave
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). FrameWeave is intended for single-user local use. Provider calls may incur charges; starting the application does not submit generation requests.

## How model availability works

Load model names from the configured endpoint and save the catalog. Providers without a catalog endpoint can use explicitly maintained lists. Image, video, presenter and motion-transfer options are also filtered against implemented input and task protocols. **A returned model ID does not establish support for every task.**

Speech uses online Edge TTS without a model API key. Reference-voice support does not guarantee precise lip sync or word-for-word speech; this applies to the current Wan integration. Current Grok / Muse integrations handle text-to-video and first-frame image-to-video, not presenters or motion transfer.

## Reference and thanks

FrameWeave builds on [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video). Thanks to its contributors. The project retains Apache-2.0; see the repository's `LICENSE` and `NOTICE` for copyright and third-party notices.
