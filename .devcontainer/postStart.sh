#!/usr/bin/env bash
set -euo pipefail

echo "[devcontainer] postStart: launching Pixelle-Video Web UI in background..."
# 按脚本位置定位仓库，克隆目录改名后仍可执行。
FRAMEWEAVE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FRAMEWEAVE_ROOT" || exit 1

# Set Streamlit config for headless mode and proper port binding
export STREAMLIT_SERVER_PORT=8501
export STREAMLIT_SERVER_ADDRESS=0.0.0.0
export STREAMLIT_SERVER_HEADLESS=true
export STREAMLIT_LOGGER_LEVEL=info
export UV_LINK_MODE=copy

# Start the web UI in background so the forwarded port is ready
nohup bash start_web.sh > /tmp/pixelle_streamlit.log 2>&1 &
WEB_PID=$!
echo "[devcontainer] Streamlit started with PID $WEB_PID (logs: /tmp/pixelle_streamlit.log)"

# Wait briefly for startup and show success message
sleep 3
if ps -p $WEB_PID > /dev/null 2>&1; then
    echo ""
    echo "✅ Pixelle-Video Web UI is launching on port 8501"
    echo "🌐 The URL will be available shortly (usually within 5-10 seconds)"
    echo ""
else
    echo ""
    echo "⚠️ Warning: Process may have exited. Check logs with: tail -f /tmp/pixelle_streamlit.log"
    echo ""
fi

echo "Common commands:"
echo "1. View logs:"
echo "   tail -f /tmp/pixelle_streamlit.log"
echo "2. Stop service:"
echo "   pkill -f 'streamlit run web/app.py'"
echo "3. Restart service:"
echo "   pkill -f 'streamlit run web/app.py' && nohup bash start_web.sh > /tmp/pixelle_streamlit.log 2>&1 &"
echo "4. Check port usage:"
echo "   lsof -i:8501"
echo "5. View processes:"
echo "   ps aux | grep streamlit"
echo ""
echo "For more help, see README or run 'ps aux | grep streamlit'."
