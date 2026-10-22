# FrameWeave workspace guide

<!-- Current three-step pages; distinguish session drafts, persisted settings and generation requests. -->

FrameWeave opens to Quick creation. Navigation also offers Digital presenters, Image-to-video, Custom media, Motion transfer, History and Settings. Chinese is the default; switch to English in the upper-right corner.

## Create in three steps

| Step | What to do | When a service is called |
| --- | --- | --- |
| Content and assets | Enter a topic or script; upload the images or videos required by the tool | Uploading assets does not automatically submit video generation |
| Visuals and settings | Select models, duration, aspect ratio, templates, speech and music as available | Explicit speech or model preview buttons call the relevant service |
| Preview and generation | Review inputs and estimates, generate, then inspect progress and output | Generation starts only after an explicit submission |

Use Previous/Next at the bottom. Return to earlier steps to edit inputs, then review the final summary before submitting. Generated output and recent batch statistics remain accessible within the current session.

## Five creation tools

### Quick creation

- **AI creation**: enter a topic and optional title; the text model organizes narration and visual prompts.
- **Your own script**: use the full supplied script, splitting long paragraphs without padding or repetition.
- **Visuals**: image templates use generated images; video templates generate multiple clips; static templates need no generated visuals.
- **Speech and music**: select an Edge TTS voice, speed and background music. Speech previews make separate online requests.
- **Long videos**: choose 5 / 8 / 10 minutes and review chapter, scene and script estimates. Batch creation is a separate flow.

### Digital presenters

Upload a character image and enter narration text. Online Edge TTS synthesizes speech, and the video request uses the first character image with that voice reference. Controls follow the integrated API capabilities. Direct narration-audio upload is not currently exposed. Voice reference does not guarantee word-for-word speech or precise lip sync; model clip limits still apply.

### Image-to-video

Upload a first-frame image and describe motion, camera movement and style. Select a model and the duration, aspect ratio or resolution it supports. Controls vary by provider.

### Custom media

Upload images, recordings or screen captures, then enter a title and content instructions. In step 2, select OpenAI-compatible vision or DashScope, choose an explicit vision model, and set duration and speech. Short targets range from 15–120 seconds; long targets are 5 / 8 / 10 minutes.

Videos are sampled locally into up to 8 / 16 / 32 frames, without source-audio transcription. Original media is used by default; image animation calls a video API only when enabled. Long videos use evenly spaced excerpts and may reuse or loop insufficient footage. This is not precise semantic action localization.

### Motion transfer

Upload a character image and reference action video, describe the edit, then select an integrated video-editing API. Ordinary text-to-video and first-frame image-to-video models do not automatically support this tool.

## Settings by purpose

| Group | Purpose |
| --- | --- |
| Text models | Scripts, chapters, asset narration, titles and visual prompts |
| Image and video | Visual generation, presenters, motion transfer and asset vision analysis |
| Network and debugging | Shared proxy, provider proxy switches and diagnostics |

Use “Find settings by feature” before configuring providers. A URL, key and model should refer to the same service; media settings do not automatically borrow the text model key.

Load models from the endpoint and save. If the service has no catalog endpoint, use explicit manual maintenance. Changing the URL, credentials or enabled proxy invalidates the catalog. Creation options also depend on implemented capabilities. See [configuration](../getting-started/configuration.md).

Connection checks query current inputs, saving persists configuration, and generation submits a task. Image/video previews also call models, and speech previews need internet access. After saving, first use Previous/Next or another creation-page interaction to rerender it. Reload the whole page only if necessary and preserve important scripts first, because reloading may clear drafts.

## Preview, downloads and History

Progress reports the current stage. Completed output can be previewed, downloaded and found in History. Errors identify the known stage where possible. If generation succeeded but record saving failed, inspect the existing result before resubmitting.

History is separate from session drafts. Switching between open tools and steps retains current inputs; reloading, closing, restarting or reloading to apply language changes may clear drafts. Keep important scripts and source files separately.

## Duration and cost expectations

Long-video duration is a planning target; the completed output is measured. More scenes generally mean more time and provider calls. Automatic resume of an entire failed long-video job is not implemented. Connection checks, offline tests and catalog queries do not replace real generation validation.

See [troubleshooting](../troubleshooting.md) or the [FAQ](../faq.md) when needed.

## Reference and thanks

FrameWeave builds on [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video). Thanks to its contributors. The project retains Apache-2.0; see the repository's `LICENSE` and `NOTICE`.
