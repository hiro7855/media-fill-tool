#!/bin/bash
# ---------------------------------------------------------------------------
# Double-click to start the Media Assistant local web app (macOS).
# A browser tab opens automatically at http://127.0.0.1:8765/.
# Closing this Terminal window stops the service.
#
# First run may need: right-click -> Open (Gatekeeper), and
#   chmod +x "启动媒介助手.command"
# All real logic lives in src/webapp.py, shared with Windows.
# ---------------------------------------------------------------------------
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# Pick an interpreter; require printed sentinel, not just exit code.
MFPY=""
if python3 -c "print('MFPYOK')" 2>/dev/null | grep -q MFPYOK; then
  MFPY="python3"
elif python -c "print('MFPYOK')" 2>/dev/null | grep -q MFPYOK; then
  MFPY="python"
fi

if [ -z "$MFPY" ]; then
  echo
  echo "未找到 Python 3。请到 https://www.python.org/downloads/ 安装后重试。"
  echo "按回车键关闭本窗口。"
  read -r _
  exit 1
fi

"$MFPY" src/webapp.py --serve
code=$?
if [ "$code" -ne 0 ]; then
  echo
  echo "服务异常退出。若提示缺少模块(如 flask),请先安装依赖:"
  echo "    python3 -m pip install flask requests pillow openpyxl pyyaml"
  echo "然后重新双击本文件。按回车键关闭本窗口。"
  read -r _
  exit 1
fi
