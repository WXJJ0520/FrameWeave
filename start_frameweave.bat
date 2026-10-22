@echo off
chcp 65001 >nul 2>&1
setlocal
rem 镜织启动脚本：使用脚本所在目录，避免从其他目录启动时找不到配置。
cd /d "%~dp0"

rem 不自动下载依赖；统一入口会复用或隐藏启动原有 Streamlit 创作服务。
if not exist "studio\dist\index.html" (
    echo [错误] 请先运行 npm --prefix studio ci 和 npm --prefix studio run build。
    exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 FFmpeg，请将其 bin 目录加入 PATH。
    exit /b 1
)
where ffprobe >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 ffprobe，请检查 FFmpeg 安装。
    exit /b 1
)

rem 自定义端口与 Python 入口保持一致，仅在当前脚本作用域设置默认值。
if not defined FRAMEWEAVE_PORT set "FRAMEWEAVE_PORT=8765"
echo 镜织 FrameWeave：http://127.0.0.1:%FRAMEWEAVE_PORT%
echo 完整创作、数字人与系统配置将自动就绪，无需另开终端。
echo 在当前终端运行，按 Ctrl+C 停止。
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m frameweave
    exit /b
)

echo [错误] 未找到 Python 虚拟环境，请先安装 uv 并运行 uv sync。
exit /b 1
