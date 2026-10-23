#!/usr/bin/env bash
# AI 사용량 위젯 실행 스크립트 (Ubuntu / Debian 계열)
#   사용법:  bash run_widget.sh
#   PyQt6가 없으면 설치하고, 위젯을 터미널과 분리해서 띄운다.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1

PY=/usr/bin/python3        # conda/venv가 켜져 있어도 apt로 설치한 PyQt6를 찾도록 시스템 파이썬으로 고정
# 로그와 PID는 사용자별 폴더에 둔다. /tmp 에 두면 한 컴퓨터의 다른 계정과 파일이 겹친다.
STATE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ai-usage-widget"
LOG="$STATE_DIR/widget.log"
PIDFILE="$STATE_DIR/widget.pid"
SUDO=sudo
[ "$(id -u)" -eq 0 ] && SUDO=
mkdir -p "$STATE_DIR" || exit 1

if [ ! -f ai_usage_widget.py ]; then
    echo "[!] ai_usage_widget.py 가 이 폴더에 없습니다. 저장소 폴더에서 실행하세요."
    exit 1
fi

has_pyqt() { "$PY" -c "import PyQt6.QtWidgets" >/dev/null 2>&1; }

if ! has_pyqt && ! command -v apt-get >/dev/null 2>&1; then
    echo "[!] PyQt6가 없고, 자동 설치는 apt(Ubuntu/Debian)에서만 합니다."
    echo "    배포판 패키지(예: Fedora python3-pyqt6) 또는 '$PY -m pip install --user PyQt6' 로 설치한 뒤 다시 실행하세요."
    exit 1
fi

if ! has_pyqt; then
    echo "PyQt6가 없어 설치합니다. sudo 비밀번호를 물을 수 있습니다."
    $SUDO apt-get update -qq
    if ! $SUDO apt-get install -y python3-pyqt6; then
        echo "apt 패키지로 설치되지 않아 pip로 설치합니다."
        # pip 버전의 Qt(6.5 이상)는 xcb 플러그인을 띄울 때 libxcb-cursor0 이 필요하다.
        $SUDO apt-get install -y python3-pip libxcb-cursor0 || exit 1
        "$PY" -m pip install --user PyQt6 || exit 1
    fi
fi

if ! has_pyqt; then
    echo "[!] PyQt6를 불러오지 못했습니다:"
    "$PY" -c "import PyQt6.QtWidgets"
    exit 1
fi

# 중복 실행 방지: 이전에 띄운 PID가 아직 살아 있고 그게 정말 이 위젯인지 확인
if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null \
       && tr '\0' ' ' < "/proc/$OLD/cmdline" 2>/dev/null | grep -q "ai_usage_widget.py"; then
        echo "위젯이 이미 실행 중입니다 (PID $OLD)."
        exit 0
    fi
fi

nohup "$PY" ai_usage_widget.py >"$LOG" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"
sleep 2
if kill -0 "$PID" 2>/dev/null; then
    echo "위젯을 실행했습니다 (PID $PID). 이 터미널은 닫아도 됩니다."
    echo "종료: 위젯의 x 버튼 또는 우클릭 > 종료"
else
    echo "[!] 실행 직후 종료되었습니다. 로그($LOG):"
    cat "$LOG"
    exit 1
fi
