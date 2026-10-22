# FrameWeave models and API settings

<!-- 字段用途及目录来源以当前实现为准，不以型号名称推断能力。 -->

Open **System settings** in the top-right corner. Settings are grouped into **Text models**, **Image & video**, and **Network & debugging**. **Find settings by feature** maps features to the fields they use. Configure only the services you need.

## Choose settings by purpose

| Task | Settings location | Meaning |
| --- | --- | --- |
| Scripts, chapters, titles, asset narration and visual prompts | Text models | OpenAI-compatible text API, independent of media credentials |
| GPT images and OpenAI-compatible visual analysis | Image & video → OpenAI | Image generation and asset understanding share this media configuration |
| DashScope images, video and visual analysis | Image & video → DashScope | Presenters and motion transfer also require an adapted model with the relevant capabilities |
| Grok video | Image & video → Grok | Quick Create clips and image-to-video; not asset analysis |
| Muse video | Image & video → Muse | Your own muse2api service |
| Seedream images and Seedance video | Image & video → Volcengine | ARK credentials; currently a manual model catalog |
| Kling video | Image & video → Kling | Access Key and Secret Key; currently a manual catalog |
| Narration audio | Voice settings in each creator | Edge TTS needs internet access, but no API key |

Using one relay does not merge configuration. Text, OpenAI media, Grok and Muse each retain their own URL and credentials. The text catalog does not substitute for the asset vision catalog.

## Configure a text model

1. Select a service preset or a custom service, then enter its Base URL and API key.
2. A preset helps fill the service URL; it is not proof of models available to your account.
3. Click **Load models from API**, then choose an appropriate text model in catalog mode.
4. For relay aliases or an endpoint without model discovery, use the separate **custom model** input. It is not inserted into the dropdown as an API result.
5. Click **Save settings** at the bottom.

The service must implement compatible chat requests. Identical model names do not establish identical relay behavior. Existing custom IDs are preserved; refreshing the catalog does not silently replace them with a different model.

## Configure image, video and vision services

Under **Image & video**, open the relevant provider and enter its API base URL and credentials. Use the provider's required version prefix. Do not enter specific endpoints such as `/models`, `/images/generations` or `/videos/generations` as the base URL.

| Provider | Catalog method | Notes |
| --- | --- | --- |
| OpenAI | Load from API | Compatible relays must implement the relevant protocol |
| DashScope | Load from API | Native catalog and supported compatible paths; preserve the service's required prefix |
| Grok / xAI | Load from API | Catalog success does not verify video task endpoints |
| Muse | Load from API | Use your muse2api service URL and key |
| Volcengine / ARK | Manual | Catalog discovery is not currently integrated |
| Kling | Manual | Catalog discovery is not currently integrated; both credentials are required |

After loading, click **Save settings** before other creators can use the catalog. For a manual list, enter one real model ID per line, click **Apply manual catalog**, then save. The interface labels it as manual and unverified. Legacy `vision_models` are preserved as historical data, not automatically promoted to an active catalog.

Image and video selectors show the **intersection of the saved catalog and implemented capabilities**. An unknown ID does not implement its submission, polling and download protocol. Presenter and motion tools further check their required inputs.

## Analyze custom media

OpenAI-compatible vision APIs and DashScope / Qwen are supported. Choose a model accepting **image input**; a text-only, speech or image-generation model does not become a vision model simply by appearing in a catalog.

1. Save the URL, key and catalog under OpenAI or DashScope.
2. In **Custom media, step 2**, choose the provider and vision model.
3. If credentials are saved but the catalog is missing, click **Load and save model list**, then explicitly select a vision model.

This creator-page button queries model names and saves only that provider's catalog. It does not upload media or generate content. Unlike the settings-page load button, it saves immediately after successful discovery.

If step 3 reports a missing catalog, return to step 2. If it reports no selected model, explicitly select one. An empty list requires checking the endpoint, access or an explicitly maintained manual catalog; no fixed model fallback is used.

## Proxy and connection checks

Set the shared media proxy under **Network & debugging → Local proxy**, then enable it for each relevant provider. Providers without that switch enabled do not use this setting. It is not a global proxy control for text models.

For a locally running application, `127.0.0.1` means your own computer, not a remote relay server. The URL, credentials and network route must belong together.

**Test connection** checks current inputs without saving or generating. A successful query does not validate image-input support, paid generation or video downloads.

## Saving and invalidation

- Configuration is saved to `config.yaml` in the project root; the first save creates it if missing.
- Catalogs contain a source, timestamp and connection fingerprint. Changing the URL, credentials or enabled proxy requires reloading or explicitly applying a manual catalog.
- Failed or empty settings-page reloads clear current candidates. Saving does not keep an older catalog or fall back to built-in IDs.
- A failed direct load from Custom media does not write a new catalog. Success is reported only after discovery and local saving both complete.
- The creator refreshes its service configuration on its next interaction; change steps before considering a full page reload.
- An idle settings page synchronizes a newer saved catalog from the same connection. Unsaved local catalog changes are preserved with a conflict message.

Keep credentials out of public issues and commits. The application is intended for a single local user.

Next: [Quick start](quick-start.md). Code is licensed under [Apache-2.0](../../../LICENSE); copyright and third-party notices are in [NOTICE](../../../NOTICE).

Based on and informed by [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video), with thanks to its authors and community.
