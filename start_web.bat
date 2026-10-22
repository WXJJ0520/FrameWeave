@echo off
chcp 65001 >nul 2>&1

echo 🚀 Starting Pixelle-Video Web UI...
echo.

uv run streamlit run web/app.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo   [ERROR] Failed to Start
    echo ========================================
    echo.
    echo It appears you downloaded the SOURCE CODE directly.
    echo.
    echo ========================================
    echo   For Regular Users:
    echo ========================================
    echo Please download the ONE-CLICK PACKAGE from:
    echo https://github.com/AIDC-AI/Pixelle-Video/releases
    echo.
    echo The one-click package includes:
    echo   ✓ Pre-configured Python environment
    echo   ✓ All required dependencies
    echo   ✓ FFmpeg tools
    echo   ✓ Ready to use, no setup needed
    echo.
    echo ========================================
    echo   For Developers:
    echo ========================================
    echo If you intend to develop or modify the code:
    echo   1. Install uv: https://docs.astral.sh/uv/
    echo   2. Run: uv sync
    echo   3. Then run this script again
    echo.
    echo ========================================
    echo.
    pause
)


