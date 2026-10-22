# Architecture

<!-- Preserve historical content and attribution; current usage is documented separately. -->

> **Legacy reference**: The original instructions, interfaces or examples below are retained for compatibility and history. They do not describe current FrameWeave web features or establish FrameWeave generation results. Use the [current overview](../index.md) and [configuration guide](../getting-started/configuration.md).

Technical architecture overview of Pixelle-Video.

---

## Core Architecture

Pixelle-Video uses a layered architecture design:

- **Web Layer**: Streamlit Web interface
- **Service Layer**: Core business logic
- **ComfyUI Layer**: Image and TTS generation

---

## Main Components

### PixelleVideoCore

Core service class coordinating all sub-services.

### LLM Service

Responsible for calling large language models to generate scripts.

### Image Service

Responsible for calling ComfyUI to generate images.

### TTS Service

Responsible for calling ComfyUI to generate speech.

### Video Generator

Responsible for composing the final video.

---

## Tech Stack

- **Backend**: Python 3.10+, AsyncIO
- **Web**: Streamlit
- **AI**: OpenAI API, ComfyUI
- **Configuration**: YAML
- **Tools**: uv (package management)

---

## More Information

Detailed architecture documentation coming soon.

