# Install FrameWeave

<!-- 使用当前仓库与锁文件安装，不把上游整合包作为镜织发行包。 -->

FrameWeave runs on Windows, macOS and Linux. The local workspace handles the interface, template rendering and media composition. AI features call configured service APIs; a local GPU or local generation models are not required.

## Requirements

| Component | Requirement and purpose |
| --- | --- |
| Python | 3.11 or newer |
| uv | Install Python dependencies from `uv.lock` |
| Node.js and npm | Node.js 22, or a newer supported version; current CI uses 22 |
| FFmpeg and ffprobe | Both commands must be on `PATH` for media processing and duration checks |
| Chromium | Install through Playwright for HTML template rendering |
| Network access | Dependency installation, model discovery, AI requests and Edge TTS |

Check `uv --version`, `node --version`, `npm --version`, `ffmpeg -version` and `ffprobe -version`. Linux also needs fonts for the languages you render; `fonts-noto-cjk` is one distribution package for Chinese text.

If frontend building reports `crypto.getRandomValues is not a function`, check Node first. An old Node executable may still be first on `PATH`. Switch to an installed supported version, for example `nvm use 22` for nvm users, reopen the terminal if needed, and check both Node and npm again. This is a build-environment issue, not an API error.

## Get the source

Download a ZIP using **Code** on the [FrameWeave GitHub repository](https://github.com/WXJJ0520/FrameWeave), or run:

```bash
# 克隆公开源码，后续命令在项目根目录执行。
git clone https://github.com/WXJJ0520/FrameWeave.git
cd FrameWeave
```

The root contains `pyproject.toml`, `uv.lock`, `studio/` and `frameweave/`.

The internal Python distribution and package retain `pixelle-video` / `pixelle_video` for compatibility. The workspace entry point is `frameweave`; you do not need to rename Python packages.

## Install dependencies and build

Run from the project root:

```bash
# 按锁文件创建独立 Python 环境。
uv sync --frozen

# 安装模板渲染使用的浏览器。
uv run --frozen playwright install chromium

# 按前端锁文件安装并构建。
npm --prefix studio ci
npm --prefix studio run build
```

On Linux, install Chromium's system dependencies when needed:

```bash
uv run --frozen playwright install --with-deps chromium
```

For readable Chinese logs in Windows PowerShell:

```powershell
# 仅影响当前终端，源文件与配置文件保存为 UTF-8。
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

## Start the workspace

```bash
uv run --frozen python -m frameweave
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). After installation and building, you can also run `start_frameweave.bat` on Windows or `bash start_frameweave.sh` on macOS / Linux.

The launcher manages the creator service on `8501`: it reuses a verified service from this checkout, or starts a new child when the port is free. Use `8765` for everyday work. On `Ctrl+C`, it stops only a child it created, leaving a pre-existing service running.

Change the workspace port through `FRAMEWEAVE_PORT`; it cannot be `8501`. PowerShell:

```powershell
$env:FRAMEWEAVE_PORT = '8766'
uv run --frozen python -m frameweave
```

macOS / Linux: `FRAMEWEAVE_PORT=8766 uv run --frozen python -m frameweave`.

## Verify the installation

1. The workspace opens with five creation tools, creation history and settings.
2. Both `ffmpeg -version` and `ffprobe -version` return successfully.
3. Template rendering does not report a missing Chromium executable.
4. Open settings to configure the services you need. Starting the workspace does not submit generation requests.

If the frontend has not been built, repeat its install and build commands. If `8501` is occupied or ownership cannot be established, identify the existing application and exit its original terminal normally. Do not terminate an unknown process by port.

A working installation does not establish that a real model is usable. Continue with [Configuration](configuration.md), then [Quick start](quick-start.md).

## Update an existing installation

Keep your `config.yaml`, source media and generated results. After updating the code, repeat `uv sync --frozen`, Chromium installation and the frontend build. Exit the previous services normally and start the unified workspace again.

Missing configuration uses defaults; saving from the interface creates `config.yaml`. The workspace binds to the local machine and is intended for one user.

Code is licensed under [Apache-2.0](../../../LICENSE); copyright and third-party notices are in [NOTICE](../../../NOTICE).

Based on and informed by [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video), with thanks to its authors and community.
