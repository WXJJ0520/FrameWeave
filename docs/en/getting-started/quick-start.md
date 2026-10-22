# FrameWeave quick start

<!-- 按当前五类创作及逐步交互说明，不承诺固定生成耗时。 -->

Complete [Installation](installation.md) and [Configuration](configuration.md), then start from the project root:

```bash
uv run --frozen python -m frameweave
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Chinese is the default; switch to English at the top right. Each creation tool follows **prepare content → configure output → preview and generate**, using Previous and Next buttons.

## Create a first short video

### Step 1: Prepare content

Open **Quick create** and choose AI writing or your own script:

- **AI writing**: describe the topic, audience, requirements and optional title. For example, “Explain AI hallucinations with three everyday examples, for someone using AI for the first time.”
- **Your own script**: provide complete narration. The application preserves your text and splits longer passages as needed for scenes.

Use a small scene count for a first test. Batch mode treats each line as a separate topic for a short video; it is not a bulk import for complete scripts.

### Step 2: Set visuals and narration

1. Choose a template and visual type; check the layout and media dimensions determined by the template.
2. Choose an image or video API model. If no model is listed, load and save the relevant provider catalog in settings.
3. Configure the visual style, prompt prefix and parameters the adapter exposes.
4. Choose an Edge TTS voice and speed. Preview a short passage; optionally choose music and its volume.
5. Where available, edit template fields such as author, signature and brand for your channel.

Image templates generate illustrations; video templates generate short clips. Template fields control layout and do not change a model's native output limits. Duration, resolution and aspect-ratio controls vary by adapter.

### Step 3: Confirm and generate

Check the content, models and output settings, then generate. The pipeline processes the script, synthesizes narration, prepares visuals, renders templates and composes the final video. Time depends on scene count, provider queues and network conditions; no fixed completion time is promised.

Preview and download the result on the current page. Use **Creation history** to find records. Output files are under `output/`. Successful model discovery or connection testing alone does not validate the complete generation pipeline.

## Narrate your own footage

Open **Custom media**:

1. Upload images, recorded footage or screen recordings; enter a title and content direction.
2. Select OpenAI / a compatible service or DashScope for analysis, and explicitly choose an image-input model. If credentials are saved but the catalog is missing, click **Load and save model list**.
3. Choose a short target of 15–120 seconds or a long target of 5 / 8 / 10 minutes, plus narration and music.
4. Select a sampling limit of 8 / 16 / 32 frames. More frames increase request size and can still miss brief actions.
5. Review assets and budgets in the final step before generating.

Original images and footage are used by default. Enabling image animation adds image-to-video requests for matched images. Videos can be up to 1 GB per file with the locked dependencies; visual-analysis images are limited to 32 MB / 64 megapixels. Videos are sampled locally rather than uploaded in full for analysis.

## Make a 5–10 minute video

Quick Create and Custom media offer long-video targets. Choose 5, 8 or 10 minutes and a narration language, then review chapter, scene, script and asset budgets. Content is handled by chapter, narration and visuals by scene, and the results are composed into one video.

The target is an estimate; actual duration is measured afterward. A supplied script is not expanded or repeated just to fill time. Video models still produce their supported short clips. Limited footage may be reused or looped; evenly spaced clips do not provide precise semantic localization. Original audio is not transcribed or retained in the final composition, which uses generated narration and background music.

Verify a short workflow before increasing scene count. Automatic resume after a failed long-video run is not implemented.

## Use the other creation tools

| Tool | Inputs | Current behavior |
| --- | --- | --- |
| Digital presenter | Character image, narration text, voice and model | Synthesizes reference speech, then calls an integrated image-and-reference-audio API; no direct narration-audio upload |
| Image to video | Image, motion and camera prompt | Uses the first uploaded image and the model's single-request duration |
| Motion transfer | Character image, reference motion video and prompt | Uses the first character image and first reference video; requires a compatible video-editing adapter |

Wan reference speech does not guarantee exact script reproduction or precise lip sync. Ordinary Grok / Muse video generation does not substitute for presenter or motion-transfer capabilities.

## Drafts and troubleshooting

Changing steps and switching between visited tools keeps current session input. Refreshing, closing the page or restarting the service may discard drafts. After saving settings, change steps to refresh configuration before reloading the page.

- Empty model selector: verify the correct provider catalog is saved and supports the current tool.
- Custom media blocked at step 3: return to step 2, load the vision catalog and explicitly select a model.
- Narration failure: preview a short Edge TTS passage and check the network and installed dependencies.
- Template rendering failure: check Playwright Chromium, FFmpeg and fonts.

Code is licensed under [Apache-2.0](../../../LICENSE); copyright and third-party notices are in [NOTICE](../../../NOTICE).

Based on and informed by [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video), with thanks to its authors and community.
