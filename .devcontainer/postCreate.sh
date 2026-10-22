#!/usr/bin/env bash
set -uo pipefail

echo "[devcontainer] Running postCreate tasks..."

# 按脚本位置定位仓库，克隆目录改名后仍可执行。
FRAMEWEAVE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FRAMEWEAVE_ROOT" || exit 1

# ============================================================================
# System Dependencies Installation
# ============================================================================

export DEBIAN_FRONTEND=noninteractive

# Remove problematic Yarn repository if it exists
echo "[devcontainer] Removing problematic repositories..."
sudo rm -f /etc/apt/sources.list.d/yarn.sources 2>/dev/null || true
sudo rm -f /etc/apt/sources.list.d/yarn.list 2>/dev/null || true

# Update package lists
echo "[devcontainer] Updating package lists..."
sudo apt-get update -y || {
  echo "[devcontainer] Warning: apt-get update had issues, continuing anyway..."
  true
}

# Install system packages needed by the project
echo "[devcontainer] Installing system packages..."
sudo apt-get install -y --no-install-recommends \
  ffmpeg \
  fontconfig \
  fonts-liberation \
  fonts-noto-cjk \
  wget \
  xdg-utils \
  ca-certificates || true

# Verify installation
echo "[devcontainer] Verifying system packages..."
echo "[devcontainer] Chinese fonts (sample):"
fc-list :lang=zh | head -n 10 || true

# ============================================================================
# Python Dependencies Installation
# ============================================================================

# Install uv package manager
echo "[devcontainer] Installing uv package manager..."
pip install uv --quiet

# Install Python dependencies with uv
echo "[devcontainer] Installing Python dependencies with uv..."
uv sync --frozen

# Install Playwright browser (Chromium for HTML template rendering)
echo "[devcontainer] Installing Playwright Chromium browser..."
uv run playwright install --with-deps chromium || true

echo "[devcontainer] postCreate complete. Streamlit will start automatically via postStart.sh"
