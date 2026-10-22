#!/usr/bin/env bash
# 镜织启动脚本：统一入口自动管理原有创作服务，保持当前终端前台运行。
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# 先检查构建产物，不在用户不知情时下载依赖或构建前端。
if [[ ! -f studio/dist/index.html ]]; then
  printf '%s\n' '[错误] 请先运行 npm --prefix studio ci 和 npm --prefix studio run build。' >&2
  exit 1
fi
for tool in ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf '[错误] 未找到 %s，请安装 FFmpeg 并加入 PATH。\n' "$tool" >&2
    exit 1
  fi
done

printf '镜织 FrameWeave：http://127.0.0.1:%s\n' "${FRAMEWEAVE_PORT:-8765}"
printf '%s\n' '完整创作、数字人与系统配置将自动就绪，无需另开终端。'
printf '%s\n' '在当前终端运行，按 Ctrl+C 停止。'
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python -m frameweave
fi
printf '%s\n' '[错误] 未找到 Python 虚拟环境，请先安装 uv 并运行 uv sync。' >&2
exit 1
