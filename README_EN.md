<!-- Describe current features; distinguish integrated APIs, offline checks and live generation results. -->
<h1 align="center">FrameWeave · 镜织</h1>

<p align="center"><b>Weave ideas, scripts and media into a complete video.</b></p>
<p align="center">AI video workspace · Five creation tools · Long-video planning · Dynamic model configuration · Chinese first</p>
<p align="center"><a href="README.md">简体中文</a> | <b>English</b> · <a href="#quick-start">Quick start</a> · <a href="#models-and-api-configuration">Model configuration</a> · <a href="docs/frameweave-faq.en.md">FAQ</a> · <a href="CHANGELOG.md">Changelog</a></p>

**FrameWeave** is a local video creation workspace for content creators, AI educators and individual developers. Start with a topic to generate a script and visuals, or upload your own images, recorded footage and screen recordings. AI helps interpret the material and organize narration; the application then handles speech, template layouts, background music and video composition.

Quick creation, digital presenters, image-to-video, custom media and motion transfer share one interface. Each tool uses a step-by-step form, and settings are grouped by purpose, so you can start with a short test and move on to a video with multiple chapters.

![FrameWeave: white workspace and a three-step creation flow](docs/assets/frameweave-creation-steps.jpg)

## What you can make

| Goal | Suggested tool | What to prepare |
| --- | --- | --- |
| AI tutorials, explainers and commentary | Quick creation | A topic or a complete script |
| Product reviews, footage narration and screen-recording tutorials | Custom media | Images or videos, creative direction and a target duration |
| Presenter-style talking clips | Digital presenters | A character image, narration text and a compatible API |
| Add motion to an image | Image-to-video | A first-frame image and a motion/camera prompt |
| Character motion references and video editing | Motion transfer | A character image, reference video and a compatible video-editing API |

## Features

| Feature | What it does |
| --- | --- |
| Five creation tools | Topic-based generation, presenter clips, image animation, composition from your media and reference-based motion transfer |
| Consistent three-step flow | Content and assets → visuals and settings → preview and generation, with Previous/Next navigation |
| Long-video planning | Quick creation and Custom media support 5 / 8 / 10-minute targets, with chapter-based narration and scenes |
| Dynamic model catalogs | Load model IDs from your service, save them for the relevant tools, or explicitly maintain a manual catalog |
| Visual asset analysis | OpenAI-compatible vision APIs and DashScope; video frames are sampled locally before analysis |
| Narration and background music | Edge TTS voices, speech rate and previews, plus BGM selection and volume |
| Visual templates | Portrait, landscape and other text/image layouts, with parameters for your branding |
| History | Browse and filter generation records; preview and download videos from creation pages |
| Grouped settings | Separate text models, image/video providers, and networking/debugging, with explanations of their uses |
| Chinese and English UI | Chinese by default, an English switch at the top right, white surfaces and consistent forms |

### Quick creation: from a topic to a video

1. Choose **AI creation** and enter a topic, content direction and an optional title. Choose **Write your own** when you have a complete script.
2. Choose a short or long video, then set the template, image/video model, narration voice, speech rate and background music.
3. Review the settings on the final step, submit generation and view the result.

AI creation plans the script. Manual-script mode keeps your text and splits it into scenes; long-script mode also divides oversized passages. Image templates present generated illustrations, while video templates request a clip for each scene. Batch creation accepts multiple topics, one per line, and generates a short video for each; it does not preserve supplied full scripts in batch mode.

### Digital presenters: character images and narration

Use a character image and narration text, select an Edge TTS voice, and choose an API that supports character images and reference audio. The application synthesizes reference speech from text; this page does not accept an uploaded voice recording. Product mode also accepts a product image and can generate narration from a product title. The current request uses the first character image and, in product mode, the first product image.

The selector reflects integrated capabilities. Failure feedback identifies known stages such as script preparation, speech synthesis, video generation and history saving. Reference-voice support is not precise lip synchronization: the current Wan integration uses audio as a voice and delivery reference and does not guarantee word-for-word reproduction. Presenter clips follow the model's per-request duration limit; this is not a 5–10-minute video entry point.

### Image-to-video: bring an image to life

Upload an image, describe the subject's movement, camera motion and visual style, then select a supported duration, aspect ratio or resolution. The current request uses the first uploaded image. Available controls depend on the adapter; an API returning a model ID does not automatically add unimplemented features.

Use this tool for tutorial inserts, product shots or animated character footage. The selected model and service determine the final clip duration and output specifications.

### Custom media: tell a story with your own footage

1. Upload images, recorded footage or screen recordings, then enter a title and content direction or narration requirements.
2. Choose a vision service and model, target duration, narration, background music and whether to animate image assets.
3. Review the material and settings, then generate: **analyze assets → write narration → match media → synthesize speech and compose**.

Short-video targets range from 15 to 120 seconds; long-video targets are 5, 8 or 10 minutes. Each uploaded video may be up to 1 GB. Images used for vision analysis are limited to 32 MB and 64 megapixels and are preprocessed before transmission. Video analysis samples up to 8, 16 or 32 evenly spaced frames and includes their sampling times in the vision request.

By default, composition uses uploaded images and videos. Enabling image animation adds image-to-video API calls for matched images. Previews are collapsed and paginated, and step navigation reuses assets cached in the current session.

### Motion transfer: combine a character with reference motion

Provide a character image and a reference video, choose an integrated video-editing model, then set the prompt and available parameters. The current request uses the first uploaded image and the first uploaded video. Models are filtered for reference-video editing support; ordinary text-to-video or image-to-video models do not automatically qualify for motion transfer.

### Settings, templates and results

- **Find settings by purpose:** use the feature-to-settings guide and configure only the services your tool needs.
- **Load models from your service:** creation pages use the saved catalog for the current connection. Reload after changing the URL, credentials or enabled proxy settings.
- **Customize templates:** built-in author, signature and brand defaults use FrameWeave. Replace them with your channel or account name; existing custom values are preserved.
- **View and download results:** videos appear on their creation pages, and history helps locate previous tasks. Digital-presenter feedback distinguishes history-saving errors from generation errors.
- **Keep inputs during a session:** moving between steps or already-open tools preserves editing state. Refreshing, closing the page or restarting the service may clear the draft; session state is not a persistent project file.

## Creating a 5–10-minute video

<!-- Multiple scenes form a long video; provider clip limits still apply. -->
Select a long-video target in **Quick creation** or **Custom media**. The application estimates chapters, scenes and a narration budget, writes or splits the script, produces each scene's narration and visuals, and assembles the final video.

~~~text
Topic / complete script / your media
                  ↓
Chapter planning or script splitting and validation
                  ↓
Scene narration + generated visuals / matched assets
                  ↓
Template rendering, background music and composition
                  ↓
Video preview, download and measured duration
~~~

| Long-video option | Visual source | Suitable for |
| --- | --- | --- |
| Quick creation + image template | A generated image for each scene | Explainers, illustrated tutorials and commentary |
| Quick creation + video template | Multiple generated short clips | Stories, scene demonstrations and visual explanations |
| Custom media | Uploaded images and videos | Recorded reviews, practical tutorials and footage narration |

For Chinese narration at a speech rate of 1.0, five minutes plans approximately 38 scenes and 1,080 characters; ten minutes plans around 75 scenes and 2,160 characters. These are planning estimates, and changing the speech rate changes the script budget. After composition, the application measures the actual duration and its difference from the target.

A few limits apply:

- The target is not a single model request and does not guarantee an exact runtime. Manual-script mode does not extend or repeat your text to meet the target.
- Quick creation may hold the final frame when a clip is shorter than its narration. Custom media may reuse assets or loop footage when there is insufficient material.
- Custom media long videos take evenly spaced excerpts from footage. They do not precisely locate an action described by a sentence.
- Asset analysis does not recognize the original audio track. Composition uses generated narration and background music rather than source audio.
- More scenes generally mean more requests and longer processing. Automatic end-to-end resume after a long-video failure is not implemented.

## Quick start

### Requirements

| Dependency | Purpose |
| --- | --- |
| Python 3.11+ and uv | Backend, creation pipelines and dependency management |
| Node.js 22 and npm | Build the React workspace; matches the current CI version |
| FFmpeg / ffprobe | Audio/video processing and duration measurement; add them to <code>PATH</code> |
| Playwright Chromium | Render HTML visual templates to images |
| Accessible model APIs | Configure the services needed for scripts, asset analysis, images or videos |

### Install

Clone the FrameWeave repository and install its dependencies:

~~~bash
# 获取镜织源码并进入项目目录。
git clone https://github.com/WXJJ0520/FrameWeave.git
cd FrameWeave

# Install the locked Python dependencies.
uv sync --frozen

# Install the browser used to render templates.
uv run playwright install chromium

# Install and build the workspace frontend.
npm --prefix studio ci
npm --prefix studio run build
~~~

On Linux, use <code>uv run playwright install --with-deps chromium</code> if Chromium system libraries are missing, and install a Chinese font such as <code>fonts-noto-cjk</code>. Confirm that both <code>ffmpeg -version</code> and <code>ffprobe -version</code> work.

### Start

~~~bash
# Run from the repository root.
uv run python -m frameweave
~~~

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. After installing dependencies and building the frontend, you can also use <code>start_frameweave.bat</code> on Windows or <code>bash start_frameweave.sh</code> on macOS/Linux.

The launcher checks and starts the creation service: <code>8765</code> serves the workspace, while <code>8501</code> serves embedded creation pages. It only reuses an existing creation process when it can verify that it belongs to this repository. It does not terminate other programs using the required ports. On exit, it cleans up only the child service it started.

Set <code>FRAMEWEAVE_PORT</code> to change the workspace port. The creation service continues to use <code>8501</code>, and the ports must differ. Open **[http://127.0.0.1:8501](http://127.0.0.1:8501)** directly when troubleshooting creation pages. See the [local Windows guide](本地运行说明.md) for details.

## Models and API configuration

### What each settings group controls

| Settings location | Purpose | Notes |
| --- | --- | --- |
| Text models | Topic scripts, chapters, asset narration, titles and visual prompts | OpenAI-compatible text API, with its own URL, key and model |
| Images and video → OpenAI | Integrated image models and Custom media vision analysis | Vision and image generation share this provider's settings; text-model credentials are not reused automatically |
| Images and video → DashScope | Wan / HappyHorse videos, image generation and asset analysis | Filtered by model abilities; specific models support presenter or motion-transfer inputs |
| Images and video → Volcengine / ARK | Seedream images and Seedance videos | The catalog currently requires explicit manual maintenance |
| Images and video → Kling | Integrated Kling video models | Access Key / Secret Key authentication; the catalog currently requires manual maintenance |
| Images and video → xAI / Grok | Grok text-to-video and first-frame image-to-video | The service must implement the adapter's video protocol |
| Images and video → Meta Muse | Video generation through your own muse2api service | Use its URL and independent key; this is not Meta's official public model API |
| Voice selection | Edge TTS voices, speech rate and previews | Requires internet access, without the model keys listed above |
| Networking and debugging | Provider proxies and diagnostic options | Base URL is the service endpoint; the proxy address controls network forwarding |

### Load a model catalog

1. Enter the provider's **Base URL** and credentials. If needed, enter the shared proxy address and enable that provider's proxy switch.
2. Click **Load models from API**. For services without catalog querying, explicitly select **Manual maintenance** and apply model IDs.
3. Save the configuration. Select the actual text model and choose the relevant model in each creation page.
4. Reload and save the catalog when adding model IDs or changing the connection.

The catalog is tied to the current URL, credentials and enabled proxy configuration and survives a restart. Text and vision selectors read the saved catalog; image, video and presenter selectors additionally intersect it with implemented adapter capabilities. **A listed model ID does not mean every input type or creation tool supports it.**

### A key alone is not enough

Credentials, the model catalog and the current selection are separate. Custom media requires a configured vision service, a saved catalog and an explicit selection of a model that accepts images.

If the vision service is saved but its catalog is empty, go to **Custom media → Visuals and narration** and click **Load and save model list** without re-entering the key. The final step distinguishes missing configuration, a missing catalog and an unselected model and offers a return button to model settings.

Connection tests perform read-only checks, catalog loading retrieves model IDs, and saving writes local configuration. Generation submits a creative request; model and voice preview buttons also call the corresponding services. Model APIs may charge for use, and actual permissions, protocol support and output quality depend on the service.

More details: [dynamic model catalogs](docs/dynamic-model-catalog.md) · [Grok / Muse integration](docs/grok-muse-video.md) · [FAQ](docs/frameweave-faq.en.md).

## Templates and customization

Templates live in <code>templates/</code>, organized by frame dimensions. Select one and fill in its title, author, brand, slogan or other available parameters. The exact fields depend on the template. The default brand is FrameWeave; replace it with your account or series name.

When editing HTML/CSS layouts, preserve the template parameter conventions and check Chinese fonts, long-title wrapping and safe margins. Rebuild the built-in previews locally:

~~~bash
# Rebuild previews without calling generation APIs.
uv run python docs/rebuild_template_previews.py
~~~

## Development and project structure

~~~text
studio/                   React + TypeScript workspace, navigation and layout
frameweave/               Local server and unified launcher
web/                      Creation forms, step navigation, settings and history
pixelle_video/pipelines/   Script, asset and video composition pipelines
pixelle_video/services/    Model adapters, vision analysis, speech and composition
templates/                HTML visual templates
tests/                    Configuration, mocked APIs, flows and local composition tests
docs/                     Guides, integration notes and development records
config.example.yaml       Public configuration example
~~~

For frontend development, start the backend, then run <code>npm --prefix studio run dev</code> in another terminal. The local server serves production assets from <code>studio/dist</code>. The Python package and import names remain <code>pixelle-video</code> / <code>pixelle_video</code> for compatibility with existing configuration and modules. Historical experimental modules remain in the repository but are not current workspace entry points.

~~~bash
# Install test tools and run the local suite.
uv sync --frozen --extra dev
uv run python -m pytest tests -q

# Type-check and build the frontend.
npm --prefix studio run build
~~~

The current GitHub Actions workflow checks a FrameWeave core subset and the frontend build. Use the full test command above for creation forms, model catalogs and other regressions. Tests primarily use mocked interfaces and local processing. Integration code and offline checks do not establish successful live model generation; record real-provider validation separately.

## Current limits and feedback

This version is for a single local user and listens on <code>127.0.0.1</code> by default. Model services are called through APIs; template rendering and final composition run locally. The web tools use direct model APIs and do not provide RunningHub or ComfyUI workflow entry points.

Multi-user accounts, persistent project drafts, a freeform editing timeline, precise word-level lip synchronization and automatic end-to-end long-video resume are not provided. When reporting a problem, include the tool, reproduction steps, model ID and a redacted error. Do not submit real credentials, personal media or local configuration.

Documentation: [Chinese guide](docs/zh/index.md) · [English guide](docs/en/index.md) · [development direction](docs/frameweave-roadmap.md) · [changelog](CHANGELOG.md). Dated validation files record a particular check; this README and the current interface define the product's present features.

## References and thanks

FrameWeave is derived from [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video); thank you to its authors and community for the open-source foundation.

The project uses [Apache-2.0](LICENSE) and retains the original copyright and third-party notices in [NOTICE](NOTICE).
