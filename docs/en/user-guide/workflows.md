# Workflow Customization

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **Legacy reference**: The original instructions, interfaces or examples below are retained for compatibility and history. They do not describe current FrameWeave web features or establish FrameWeave generation results. Use the [current overview](../index.md) and [configuration guide](../getting-started/configuration.md).

How to customize ComfyUI workflows to achieve specific functionality.

---

## Workflow Introduction

Pixelle-Video is built on the ComfyUI architecture and supports custom workflows.

---

## Workflow Types

### TTS Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

Used for Text-to-Speech, supporting various TTS engines:
- Edge-TTS
- Index-TTS (supports voice cloning)
- Other ComfyUI-compatible TTS nodes

### Image Generation Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

Used for generating static images as video backgrounds:
- FLUX series models
- Stable Diffusion series models
- Other image generation models

### Video Generation Workflows

Located in `workflows/selfhost/` or `workflows/runninghub/`

**New Feature**: Supports AI video generation to create dynamic video content.

**Preset Workflows**:
- `runninghub/video_wan2.1_fusionx.json`: Cloud workflow (recommended)
  - Based on WAN 2.1 model
  - No local setup required, accessed via RunningHub API
  - Supports Text-to-Video generation
  
- `selfhost/video_wan2.1_fusionx.json`: Local workflow
  - Requires local ComfyUI environment
  - Requires installation of corresponding video generation nodes
  - Suitable for users with local GPU

**Use Cases**:
- Works with `video_*.html` templates
- Automatically generates dynamic video backgrounds based on scripts
- Enhances visual expressiveness and viewing experience

---

## Custom Workflows

1. Design your workflow in ComfyUI
2. Export as JSON file
3. Place in `workflows/` directory
4. Select and use in Web interface

---

## More Information

Detailed workflow customization guide coming soon.

