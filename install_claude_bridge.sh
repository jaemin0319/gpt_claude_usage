#!/usr/bin/env bash
# Claude Code가 5시간/주간 한도 값을 파일로 남기도록 statusLine을 설정한다.
#   사용법: bash install_claude_bridge.sh
# 되돌리기: bash install_claude_bridge.sh --uninstall
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1

CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
BRIDGE="$CLAUDE_DIR/claude_usage_bridge.py"
PREV="$CLAUDE_DIR/usage-bridge-prev.txt"
PY=/usr/bin/python3

if [ "${1:-}" = "--uninstall" ]; then
    "$PY" - "$SETTINGS" "$PREV" <<'PYEOF'
import json, os, sys
settings, prev_file = sys.argv[1], sys.argv[2]
try:
    with open(settings, encoding="utf-8") as f:
        data = json.load(f)
except (OSError, ValueError):
    print("설정 파일이 없어 되돌릴 것이 없습니다."); raise SystemExit(0)
prev = ""
if os.path.exists(prev_file):
    prev = open(prev_file, encoding="utf-8").read().strip()
if prev:
    data["statusLine"] = {"type": "command", "command": prev}
    print("원래 쓰던 statusLine으로 되돌렸습니다.")
else:
    data.pop("statusLine", None)
    print("statusLine 설정을 지웠습니다.")
with open(settings, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
if os.path.exists(prev_file):
    os.remove(prev_file)
PYEOF
    exit 0
fi

if [ ! -f claude_usage_bridge.py ]; then
    echo "[!] claude_usage_bridge.py 가 이 폴더에 없습니다. 두 파일을 같은 폴더에 두세요."
    exit 1
fi

mkdir -p "$CLAUDE_DIR" || exit 1
cp claude_usage_bridge.py "$BRIDGE" || exit 1
chmod +x "$BRIDGE"

"$PY" - "$SETTINGS" "$BRIDGE" "$PREV" "$PY" <<'PYEOF' || exit 1
import json, os, shutil, sys
settings, bridge, prev_file, py = sys.argv[1:5]
command = f"{py} {bridge}"

data = {}
if os.path.exists(settings):
    try:
        with open(settings, encoding="utf-8") as f:
            data = json.load(f)
    except ValueError:
        print("[!] settings.json 을 읽지 못했습니다(JSON 형식 오류). 직접 고친 뒤 다시 실행하세요.")
        raise SystemExit(1)
    shutil.copy(settings, settings + ".bak")
    print(f"기존 설정을 {os.path.basename(settings)}.bak 로 백업했습니다.")

old = (data.get("statusLine") or {}).get("command", "")
if old and "claude_usage_bridge.py" not in old:
    with open(prev_file, "w", encoding="utf-8") as f:
        f.write(old)
    print("쓰던 statusLine이 있어 그대로 이어서 실행하도록 저장했습니다.")

data["statusLine"] = {"type": "command", "command": command}
os.makedirs(os.path.dirname(settings), exist_ok=True)
with open(settings, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print("statusLine 설정을 마쳤습니다.")
PYEOF

# 가짜 입력으로 한 번 돌려 본다. HOME을 임시 폴더로 바꿔서 진짜 상태 파일은 건드리지 않는다.
TMPHOME=$(mktemp -d)
if echo '{"model":{"display_name":"Opus"},"context_window":{"used_percentage":25},"rate_limits":{"five_hour":{"used_percentage":12,"resets_at":0}}}' \
    | HOME="$TMPHOME" "$PY" "$BRIDGE" >/dev/null 2>&1 && [ -f "$TMPHOME/.claude/statusline-state.json" ]; then
    echo "브리지 동작 확인 완료."
else
    echo "[!] 브리지 실행에 실패했습니다. 아래 명령의 오류를 확인하세요:"
    echo "    echo '{}' | $PY $BRIDGE"
fi
rm -rf "$TMPHOME"

cat <<'MSG'

이제 Claude Code를 실행해서 아무 질문이나 한 번 보내세요.
첫 응답이 오면 ~/.claude/statusline-state.json 이 만들어지고, 위젯이 그 값을 읽습니다.
(한도 값은 claude.ai Pro/Max 구독 계정에만 내려옵니다. API 키로 쓰는 경우에는 오지 않습니다.)
MSG
