#!/usr/bin/env bash
# AI 사용량 위젯 설치 스크립트 (Ubuntu / Debian 계열)
#   사용법: bash setup.sh
# 하는 일: PyQt6 설치 -> Claude statusLine 브리지 설치(선택) -> 앱 메뉴 등록 -> 위젯 실행
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
HERE=$(pwd)
PY=/usr/bin/python3        # conda/venv가 켜져 있어도 시스템 파이썬을 쓴다
SUDO=sudo
[ "$(id -u)" -eq 0 ] && SUDO=

say() { printf '\n== %s ==\n' "$1"; }

for f in ai_usage_widget.py claude_usage_bridge.py install_claude_bridge.sh run_widget.sh; do
    [ -f "$f" ] || { echo "[!] $f 가 없습니다. 저장소 폴더에서 실행하세요."; exit 1; }
done

say "1/4  PyQt6 확인"
if "$PY" -c "import PyQt6.QtWidgets" >/dev/null 2>&1; then
    echo "이미 설치돼 있습니다."
elif ! command -v apt-get >/dev/null 2>&1; then
    echo "[!] 자동 설치는 apt(Ubuntu/Debian)에서만 합니다."
    echo "    배포판 패키지(예: Fedora python3-pyqt6) 또는 '$PY -m pip install --user PyQt6' 로 설치한 뒤 다시 실행하세요."
    exit 1
else
    echo "설치합니다. sudo 비밀번호를 물을 수 있습니다."
    $SUDO apt-get update -qq
    if ! $SUDO apt-get install -y python3-pyqt6; then
        $SUDO apt-get install -y python3-pip libxcb-cursor0 || exit 1
        "$PY" -m pip install --user PyQt6 || exit 1
    fi
    "$PY" -c "import PyQt6.QtWidgets" >/dev/null 2>&1 || { echo "[!] PyQt6 설치에 실패했습니다."; exit 1; }
fi

say "2/4  Claude 연동"
echo "Claude Code가 한도 값을 파일로 남기도록 statusLine 브리지를 설치할 수 있습니다."
echo "(계정 직접 조회가 막혔을 때 쓰는 예비 경로입니다. 설치해 두면 더 안정적입니다.)"
printf "설치할까요? [Y/n] "
read -r answer 2>/dev/null < /dev/tty || answer=Y
case "${answer:-Y}" in
    [Nn]*) echo "건너뜁니다. 나중에 bash install_claude_bridge.sh 로 설치할 수 있습니다." ;;
    *)     bash install_claude_bridge.sh ;;
esac

say "3/4  아이콘 만들기"
APPS="$HOME/.local/share/applications"
DESK=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
mkdir -p "$APPS" "$DESK"
# run_widget.sh 를 거쳐 띄워야 아이콘을 두 번 눌러도 위젯이 하나만 뜨고 로그가 남는다.
# 경로에 공백이 있어도 되도록 따옴표로 감싼다.
cat > "$APPS/ai-usage-widget.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=AI 사용량 위젯
Comment=Claude / GPT 사용량 모니터
Exec=/bin/bash "$HERE/run_widget.sh"
Path=$HERE
Icon=$HERE/icon.png
Terminal=false
Categories=Utility;
DESKTOP
chmod +x "$APPS/ai-usage-widget.desktop"
update-desktop-database "$APPS" >/dev/null 2>&1
cp "$APPS/ai-usage-widget.desktop" "$DESK/" 2>/dev/null &&
    chmod +x "$DESK/ai-usage-widget.desktop" &&
    gio set "$DESK/ai-usage-widget.desktop" metadata::trusted true 2>/dev/null
echo "앱 목록과 바탕화면에 'AI 사용량 위젯' 아이콘을 만들었습니다."
echo "(바탕화면 아이콘을 처음 누르면 실행을 허용할지 물을 수 있습니다.)"

printf "\n로그인할 때 자동으로 띄울까요? [y/N] "
read -r auto 2>/dev/null < /dev/tty || auto=N
case "${auto:-N}" in
    [Yy]*) mkdir -p "$HOME/.config/autostart" &&
           { cat "$APPS/ai-usage-widget.desktop"
             echo "X-GNOME-Autostart-enabled=true"
             echo "X-GNOME-Autostart-Delay=5"     # 로그인 직후 패널과 네트워크가 자리 잡을 시간
           } > "$HOME/.config/autostart/ai-usage-widget.desktop" &&
           echo "자동 시작을 켰습니다. (끄려면 ~/.config/autostart/ai-usage-widget.desktop 삭제)" ;;
    *)     echo "건너뜁니다." ;;
esac

say "4/4  실행"
bash run_widget.sh

cat << 'MSG'

--- 값이 안 보이면 ---
Claude : claude 로 로그인돼 있어야 합니다 (Pro/Max 구독 계정만 한도 값이 내려옵니다).
GPT    : codex 로 로그인돼 있어야 합니다.
점검   : bash check.sh
로그   : cat ~/.cache/ai-usage-widget/widget.log
MSG
