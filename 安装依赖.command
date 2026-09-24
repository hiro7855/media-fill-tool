#!/bin/bash
# ---------------------------------------------------------------------------
# Double-click ONCE to install the Python packages the assistant needs (macOS).
# After it finishes, use 启动媒介助手.command to run the tool.
#
# First run may need: right-click -> Open (Gatekeeper), and
#   chmod +x "安装依赖.command"
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

echo "正在安装依赖,请稍候..."
"$MFPY" -m pip install --upgrade pip
"$MFPY" -m pip install -r requirements.txt
code=$?
if [ "$code" -ne 0 ]; then
  echo
  echo "安装失败。请检查网络后重新双击本文件。"
  echo "按回车键关闭本窗口。"
  read -r _
  exit 1
fi

echo
echo "完成。现在可以双击「启动媒介助手.command」启动工具。"
echo "按回车键关闭本窗口。"
read -r _
