# FrameWeave frequently asked questions

<!-- 区分目录查询、配置保存与真实生成，不混用测试结论。 -->

## What do I need for a first run?

Install Python 3.11+, uv, Node.js 22 or a newer supported version, npm, FFmpeg and ffprobe. Follow [Installation](en/getting-started/installation.md) for locked dependencies, Playwright Chromium and the frontend build. Run `uv run --frozen python -m frameweave` and open the [local workspace](http://127.0.0.1:8765).

The workspace runs locally, while scripts, visual analysis and generated media use your configured APIs. Edge TTS also needs internet access. A local GPU is not required.

## Which credentials should I configure?

| Task | Location in settings |
| --- | --- |
| Scripts, chapters, titles and asset narration | Text models |
| GPT images and OpenAI-compatible visual analysis | Image & video → OpenAI |
| DashScope images, video, vision and integrated presenter / video-editing capabilities | Image & video → DashScope |
| Grok or Muse video | Image & video → Grok / Muse |
| Seedream images and Seedance video | Image & video → Volcengine |
| Kling video | Image & video → Kling |
| Edge TTS narration | Choose a voice and speed in the creator; no API key |

Text and OpenAI media settings are independent, even when they use the same relay. Muse uses your own muse2api URL and service key. Configure only the services you need.

## How are connection tests, loading, saving and generation different?

- **Test connection** checks current inputs without saving or generating.
- **Load models from API** in settings reads the catalog; you still need to save at the bottom.
- **Save settings** persists the URL, credentials and catalog.
- **Load and save model list** in Custom media queries and directly saves the selected vision provider, using its saved configuration.
- **Generate** submits script, analysis, narration or video tasks according to the selected workflow.

A successful query does not establish vision support, generation access or a sufficient balance.

## Why does Custom media ask for a model after I entered a key?

Configured credentials and a saved model catalog are separate states. In **Custom media, step 2**, choose OpenAI or DashScope, click **Load and save model list**, then explicitly select a model that accepts images. The text-model catalog does not replace the vision catalog.

If discovery returns zero models, check that the service offers a catalog endpoint. Otherwise choose **Manual list** in settings, enter actual model IDs, apply the list and save. Manual sources remain clearly labeled rather than appearing as successful API discovery.

## Why is a returned model missing from an image or video selector?

Text and vision selectors read their respective catalogs. Image, video, presenter and motion tools also require an adapter for the relevant inputs, submission, polling and download protocol. Only integrated models with the required capabilities are shown.

ARK and Kling currently use manual catalogs because discovery is not integrated. Entering an unknown video ID does not implement its protocol. Legacy `vision_models` are retained as historical entries, not an active catalog.

## How do I set the Base URL and proxy?

Use the service's API base URL, not a generation path or `/models` endpoint. The URL and credentials must belong to the same service. Text compatibility alone does not imply image or video support.

Set the shared media proxy under **Network & debugging → Local proxy**, then enable it for each relevant provider. Disabled providers do not use that setting. It is not a global proxy switch for text models. With a local application, `127.0.0.1` means your own computer, not a remote relay server.

Changing the URL, credentials or enabled proxy requires loading and saving a new catalog.

## How do presenters differ from image-to-video?

The presenter tool takes a character image and narration text, creates reference speech, then calls an integrated API supporting both images and reference audio. Direct narration-audio upload is not currently available. Wan reference speech guides voice and delivery without guaranteeing exact words or precise lip sync.

Image-to-video creates movement from a first-frame image and prompt. Current Grok / Muse integrations serve video tasks, not presenter or motion-transfer replacements. Motion transfer requires character and reference-video inputs with a video-editing adapter.

## Is a 5–10 minute video generated in one request?

Quick Create and Custom media offer 5 / 8 / 10 minute targets. They plan chapters, narration and scenes, then synthesize audio and generate or reuse visuals per scene before composing the final video. Target duration is a budget; actual duration is measured afterward.

Custom media uses evenly spaced segments and may reuse or loop limited footage. It does not precisely locate actions by narration. Source audio is neither transcribed nor mixed into the output, which uses generated narration and background music. Automatic resume after failure is not implemented.

## Which vision providers and file sizes are supported?

Both **OpenAI / compatible vision APIs** and **DashScope / Qwen** are supported. Choose an image-input model from the respective catalog.

With the locked dependencies, each video can be up to **1 GB**. Images for visual analysis are limited to **32 MB / 64 megapixels** and are resized before sending. Videos are sampled locally into up to **8 / 16 / 32 frames** with timestamps, rather than uploaded in full for analysis. More frames increase request size and may still miss brief actions.

Original media is used by default. Enabling image animation adds video API requests for matched images.

## Why does Edge TTS return 403?

Edge TTS is an online narration service and does not use OpenAI or Grok generation keys. The project pins `edge-tts==7.3.1`. After updating, run `uv sync --frozen` and restart the existing service normally.

If it still fails, check the network, system time and remote service status. Correct dependencies cannot guarantee service availability. Preview a short passage to distinguish narration failures from video failures.

## Why does building report crypto.getRandomValues is not a function?

Check `node --version` and `npm --version`. An older Node executable, such as Node 16, may still be selected by `PATH`. Use Node.js 22 or a newer supported version; nvm users can select an installed version with `nvm use 22`. Reopen the terminal if needed, check versions again and rerun the frontend build. This error is unrelated to API credentials.

## Why is the interface old, or a port occupied?

Use `8765` for the workspace; `8501` hosts the embedded creator. Rebuild the frontend after UI changes and restart after launcher changes.

The launcher reuses only a creator on `8501` that it can verify belongs to this checkout. Older services launched with relative script paths may not be attributable. Exit their original terminal normally before starting FrameWeave; do not kill unknown processes.

## Are drafts permanent? Does saving configuration clear media?

Creators use updated configuration on their next interaction; changing steps triggers an update. Step navigation and switching between visited tools preserve current session input and upload caches.

Refreshes, closing the page and service restarts can still discard drafts; they are not persistent project files. Preview and download generated videos in the creator, and find records under Creation history. Settings are in `config.yaml`; generated files are in `output/`.

See [Configuration](en/getting-started/configuration.md) and [Quick start](en/getting-started/quick-start.md). Code is licensed under [Apache-2.0](../LICENSE); copyright and third-party notices are in [NOTICE](../NOTICE).

Based on and informed by [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video), with thanks to its authors and community.
