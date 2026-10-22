# FrameWeave FAQ

<!-- Current web behavior; legacy workflow tutorials are separate references. -->

## Which tool should I start with?

Use **Quick creation** for a topic or complete script, and **Custom media** for recorded footage, screen recordings or images. Digital presenters, Image-to-video and Motion transfer cover character narration, single-image animation and reference-action editing.

## Do I need credentials for every provider?

No. Use “Find settings by feature” to configure only the services you need. Text models handle scripts, titles and prompts. Media providers handle visual generation and supported vision analysis. OpenAI media credentials do not automatically inherit the text model's key.

## Why is the model list empty after I enter a key?

Enter the Base URL and key, **load models from the endpoint and save**. Catalogs are bound to the URL, credentials and enabled proxy settings. Reload after changing the connection. Providers without a catalog endpoint can use an explicitly maintained list of model IDs.

Creation pages also filter for implemented capabilities. Text-only, moderation or audio models are not interchangeable with vision models. A text-to-video model is not automatically a presenter or motion-transfer model. A successful catalog query does not verify generation access.

## Can I use a relay API?

Yes, when it implements the required protocol. The URL and key should belong to the same service. OpenAI-compatible text endpoints do not automatically support image or video requests. Grok, Muse and DashScope still require their implemented submission, status and result protocols. Muse refers to a separately deployed third-party muse2api service, not an official public Meta model API.

## Do I need ComfyUI or RunningHub?

The current web workspace uses direct model APIs and does not need these workflow services. Old documentation and configuration fields remain for compatibility and historical reference. FFmpeg, Chromium, templates and media preprocessing still run locally.

## Does speech work offline or support voice cloning?

Speech uses **online Edge TTS** with voice, speed and preview controls. It needs internet access and no model API key. Workflow-based voice cloning is not exposed in the current speech interface. Voice inputs for presenters depend on the selected video API; voice reference does not guarantee exact audio driving or word-for-word lip sync.

## How long can presenter videos be? Can Grok or Muse replace them?

Presenter videos follow the selected model's single-clip duration limits, not the 5–10-minute flow. Current Wan reference-voice support does not guarantee exact speech or precise lip sync. Current Grok / Muse integrations support text-to-video and first-frame image-to-video, not presenters or motion transfer.

## How do I create a 5–10-minute video?

Choose a **5 / 8 / 10-minute** target in Quick creation or Custom media. FrameWeave plans chapters and scenes, then creates narration and visuals and composes the result. Actual duration depends on the script, voice and speed and is measured afterward. Per-request model limits remain unchanged; automatic resume of an entire failed long-video job is not implemented.

## How does Custom media understand videos?

It supports OpenAI-compatible vision APIs and DashScope. Videos are sampled locally into at most **8 / 16 / 32 frames** with timestamps; the full video is not uploaded for analysis. Sampling may miss brief actions and does not transcribe original audio. Evenly spaced footage excerpts used during composition are not semantic shot localization.

The current per-video upload limit is **1 GB**. Vision input images are limited to **32 MB / 64 million pixels** and are preprocessed. Output uses generated narration and selected background music rather than the source audio.

## Will switching pages lose my inputs?

Step navigation and switching between already-open tools retain session inputs. Reloading, closing a page, restarting the service or reloading to apply a language change may clear them. Session drafts are not permanent projects; keep important scripts separately.

## How do testing, saving and generating differ?

Testing queries the service with current inputs. Saving persists configuration. Generating submits a creation task. Image and video previews also call the selected model, and speech previews require internet access; the final generation button is not the only service call.

After saving, first use Previous/Next or another interaction on the creation page to rerender it with updated configuration. Reload the whole page only if still necessary, keeping important scripts separately because reloading may clear session drafts. A successful connection or catalog query does not establish correct generation permissions, balance, protocol or model inputs.

## Where are results? Should I regenerate after an error?

Preview and download the output on the creation page, or find its record in History. If generation succeeded but record saving or display failed, look for the existing result before resubmitting. See [troubleshooting](troubleshooting.md) for other failures.

## Reference and thanks

FrameWeave builds on [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video). Thanks to its contributors. The project retains Apache-2.0; see the repository's `LICENSE` and `NOTICE`.
