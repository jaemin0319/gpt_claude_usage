#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code statusLine 브리지
=============================
Claude Code는 5시간/주간 한도(rate_limits)를 statusLine 명령에게 stdin으로만 넘겨 준다.
이 스크립트를 statusLine으로 걸어 두면, 넘어온 값을 파일로 남기고(위젯이 그 파일을 읽는다)
터미널에는 짧은 상태 줄을 출력한다.

설치:  bash install_claude_bridge.sh
수동 설정은 ~/.claude/settings.json 의 statusLine.command 를 이 파일로 지정하면 된다.

메모
- rate_limits는 claude.ai Pro/Max 구독 계정에만, 그리고 세션의 첫 응답 이후에 들어온다.
- 창이 리셋되면 Claude Code가 해당 창을 빼고 보내므로, 이 파일에서도 같이 지운다.
- 여러 세션이 동시에 떠 있으면 같은 창(resets_at이 같은 것) 중 큰 값을 남긴다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

STATE_FILE = os.path.expanduser("~/.claude/statusline-state.json")
PREV_FILE = os.path.expanduser("~/.claude/usage-bridge-prev.txt")   # 원래 쓰던 statusLine 명령
WINDOWS = ("five_hour", "seven_day")


def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_state(limits: dict) -> None:
    """같은 창이면 더 큰 사용률을 남기고, 원자적으로 파일을 바꾼다."""
    merged = dict((read_json(STATE_FILE).get("rate_limits") or {}))
    now = time.time()
    for key in WINDOWS:
        new = limits.get(key)
        if not isinstance(new, dict) or new.get("used_percentage") is None:
            # 값이 없는 이유는 둘 중 하나: 창이 리셋됐거나, 세션의 첫 응답이 아직 안 왔거나.
            # 앞의 경우만 지운다. 그래야 새 세션을 열었다고 멀쩡한 값이 날아가지 않는다.
            old = merged.get(key)
            if isinstance(old, dict):
                resets = old.get("resets_at")
                if isinstance(resets, (int, float)) and resets <= now:
                    merged.pop(key, None)
            continue
        entry = {"used_percentage": float(new["used_percentage"]), "resets_at": new.get("resets_at")}
        old = merged.get(key)
        same_window = isinstance(old, dict) and old.get("resets_at") == entry["resets_at"]
        if same_window and float(old.get("used_percentage") or 0) > entry["used_percentage"]:
            continue                         # 다른 세션이 더 높은 값을 이미 남겼다
        merged[key] = entry

    payload = {"updated_at": int(time.time()), "rate_limits": merged}
    folder = os.path.dirname(STATE_FILE)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".statusline-state-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, STATE_FILE)          # 반쯤 쓰인 파일을 위젯이 읽는 일이 없도록
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def status_line(data: dict, limits: dict) -> str:
    parts = ["[%s]" % ((data.get("model") or {}).get("display_name") or "Claude")]
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {float(ctx):.0f}%")
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        win = limits.get(key) or {}
        if win.get("used_percentage") is not None:
            parts.append(f"{label} {float(win['used_percentage']):.0f}%")
    return " | ".join(parts)


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    limits = data.get("rate_limits") or {}

    if isinstance(limits, dict) and limits:  # rate_limits가 통째로 없으면 파일을 건드리지 않는다
        try:
            write_state(limits)
        except Exception:                    # 파일을 못 써도 상태 줄은 계속 나와야 한다
            pass

    prev = ""
    if os.path.exists(PREV_FILE):
        try:
            with open(PREV_FILE, encoding="utf-8") as f:
                prev = f.read().strip()
        except OSError:
            prev = ""
    if prev:                                 # 쓰던 statusLine이 있으면 그대로 이어서 실행
        try:
            done = subprocess.run(prev, shell=True, input=raw, capture_output=True,
                                  text=True, timeout=10)
            sys.stdout.write(done.stdout)
            return 0
        except Exception:
            pass

    print(status_line(data, limits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
