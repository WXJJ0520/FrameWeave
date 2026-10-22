# 安装镜织 FrameWeave

<!-- 使用当前仓库与锁文件安装，不把上游整合包作为镜织发行包。 -->

镜织支持 Windows、macOS 和 Linux。本地工作台负责交互、模板渲染与音视频合成，AI 能力通过服务接口调用，无需部署本地生成模型或准备 GPU。

## 准备环境

| 组件 | 要求与用途 |
| --- | --- |
| Python | 3.11 或更高版本 |
| uv | 按 `uv.lock` 安装依赖 |
| Node.js、npm | Node.js 22 或更新的受支持版本，现有 CI 使用 22 |
| FFmpeg、ffprobe | 两者加入 `PATH`，用于媒体处理与时长检测 |
| Chromium | 通过 Playwright 安装，渲染模板 |
| 网络 | 安装依赖、查询模型、调用 AI 与 Edge TTS |

确认 `uv --version`、`node --version`、`npm --version`、`ffmpeg -version` 和 `ffprobe -version` 可执行。Linux 需中文字体，例如 `fonts-noto-cjk`。

构建出现 `crypto.getRandomValues is not a function` 时，先检查当前 Node 版本。`PATH` 可能仍优先选中旧 Node。切换到已安装的受支持版本，例如 nvm 用户执行 `nvm use 22`；必要时重开终端，再确认 Node 与 npm 版本后构建。这个错误不属于 API 连接问题。

## 获取代码

在 [镜织 GitHub 仓库](https://github.com/WXJJ0520/FrameWeave) 使用 **Code** 按钮下载 ZIP，或执行：

```bash
# 克隆公开源码，后续命令在项目根目录执行。
git clone https://github.com/WXJJ0520/FrameWeave.git
cd FrameWeave
```

项目根目录包含 `pyproject.toml`、`uv.lock`、`studio/` 和 `frameweave/`。

内部 Python 包名 `pixelle-video` / `pixelle_video` 保留用于兼容，工作台入口为 `frameweave`；无需改写包名，也不要把其他项目整合包当成镜织安装包。

## 安装依赖与前端

```bash
# 按锁文件创建独立 Python 环境。
uv sync --frozen

# 安装模板渲染需要的浏览器。
uv run --frozen playwright install chromium

# 按前端锁文件安装并构建。
npm --prefix studio ci
npm --prefix studio run build
```

Linux 缺少浏览器系统依赖时使用：

```bash
uv run --frozen playwright install --with-deps chromium
```

Windows 中文日志乱码时，可在 PowerShell 设置后启动：

```powershell
# 只影响当前终端；源文件和配置文件使用 UTF-8。
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

## 启动工作台

```bash
uv run --frozen python -m frameweave
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。安装完成后，Windows 也可运行 `start_frameweave.bat`，macOS / Linux 可运行 `bash start_frameweave.sh`。

启动器管理 `8501` 创作服务：可验证属于当前仓库时复用，空闲时启动新子服务。日常只需打开 `8765`。`Ctrl+C` 退出时清理本次创建的子服务，保留此前已有服务。

主端口通过 `FRAMEWEAVE_PORT` 修改，不能使用 `8501`。PowerShell 示例：

```powershell
$env:FRAMEWEAVE_PORT = '8766'
uv run --frozen python -m frameweave
```

macOS / Linux：`FRAMEWEAVE_PORT=8766 uv run --frozen python -m frameweave`。

## 检查安装

1. 工作台打开，五个创作入口、作品记录和系统配置可见。
2. `ffmpeg -version` 与 `ffprobe -version` 正常返回。
3. 模板渲染没有“找不到 Chromium 可执行文件”错误。
4. 进入系统配置，准备填写所用服务；启动页面本身不提交生成任务。

前端未构建时重跑前端安装与构建命令。`8501` 被占用或无法确认归属时，先确认程序用途，再在对应旧终端正常退出，不按端口杀进程。

安装成功不等于真实模型可用。下一步按 [配置说明](configuration.md) 加载保存目录，再按 [快速开始](quick-start.md) 验证创作流程。

## 更新已有安装

保留 `config.yaml`、素材和成片。更新代码后重跑 `uv sync --frozen`、Chromium 安装与前端构建，正常停止旧服务后统一启动。

配置不存在时使用默认值，首次在页面保存后写入 `config.yaml`。默认只监听本机，面向单用户使用。

代码使用 [Apache-2.0](../../../LICENSE)，版权与第三方说明见 [NOTICE](../../../NOTICE)。

基于并参考 [Pixelle-Video](https://github.com/ATH-MaaS/Pixelle-Video)，感谢原作者和社区。
