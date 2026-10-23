#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 사용량 위젯 (Claude + GPT)
=============================
바탕화면 구석에 띄워 두는 초소형 사용량 모니터.
기본은 5시간 한도만 보여 주고, 아래쪽 화살표 버튼을 누르면 주간 한도가 함께 펼쳐진다.

준비 (실제 값을 읽으려면 한 번만)
    Claude   bash install_claude_bridge.sh   -> Claude Code statusLine에 브리지를 설치
    GPT      Codex CLI로 한 번 이상 작업하면 세션 로그에 사용률이 남는다 (추가 설정 없음)

실행
    Ubuntu   bash run_widget.sh        (PyQt6가 없으면 설치한 뒤 터미널과 분리해서 실행)
             직접 실행: sudo apt install python3-pyqt6 && python3 ai_usage_widget.py
    Windows  pip install PyQt6 && pythonw ai_usage_widget.py

조작
    - 카드 아무 곳이나 왼쪽 버튼으로 끌면 이동
    - 오른쪽 아래 모서리를 끌면 크기 조정 (Ctrl + 휠, ⋯ 메뉴의 "크기"로도 바꿀 수 있다)
    - 화살표 버튼: 주간 한도 펼치기 / 접기
    - − 버튼: 최소화. 5시간 사용률만 남은 작은 막대가 되고, 막대의 □ 버튼으로 다시 펼친다
    - ⋯ 버튼 또는 오른쪽 클릭: Claude / GPT 보기 토글, 새로고침, 최소화, 크기, 색상, 투명도, 항상 위, 종료
    - 색상: 견본에서 카드 색을 고르거나 "직접 고르기…"로 아무 색이나. 글자와 선 색은 바탕에 맞춰 따라 바뀐다
    - 숨긴 서비스는 조회도 하지 않는다
    - Claude 로그인 토큰이 만료되면 `claude -p /usage` 로 스스로 갱신한다 (Claude Code 2.1.278 이상)
    - 위치, 크기, 색상, 투명도, 펼침/최소화 상태, 보이는 서비스는 종료 시 저장되어 다음 실행 때 복원됨

파일 구성 (나중에 모듈로 쪼갤 때 아래 구획 그대로 분리하면 됨)
    [1] 설정                  -> config.py
    [2] 데이터 모델           -> models.py
    [3] Claude 사용량 모듈    -> providers/claude_usage.py
    [4] GPT 사용량 모듈       -> providers/gpt_usage.py
    [5] 백그라운드 워커       -> worker.py
    [6] UI 위젯               -> ui.py
    [7] 진입점                -> main.py
"""
from __future__ import annotations

import glob
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import (
    QEasingCurve, QObject, QPoint, QPointF, QPropertyAnimation, QRectF, QSettings,
    QSize, Qt, QThread, QTimer, pyqtProperty, pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QGuiApplication, QPainter, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractButton, QApplication, QColorDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QVBoxLayout, QWidget, QWidgetAction,
)


# ══════════════════════════════════════════════════════════════════════════════
# [1] 설정
# ══════════════════════════════════════════════════════════════════════════════
APP_VERSION = "2026.10.23.2"     # 업데이트할 때 새 파일인지 구분하는 표식
USE_MOCK = False                 # False: 실제 값 / True: UI 확인용 더미 데이터
REFRESH_INTERVAL_SEC = 30        # 자동 새로고침 주기 (초)
DEFAULT_OPACITY = 0.92           # 창 투명도 초기값 (0.0 ~ 1.0)
WARN_PCT = 70.0                  # 이 사용률부터 주의색
CRITICAL_PCT = 90.0              # 이 사용률부터 경고색

# --- Claude 실제 연동용 ---
# 1순위: Claude Code가 로그인해 둔 OAuth 토큰으로 사용량을 직접 물어본다 (Claude Code가 꺼져 있어도 지금 값).
# 2순위: 실패하면 statusLine 브리지가 남긴 파일을 읽는다 (마지막 대화 시점의 값).
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
CLAUDE_CREDENTIALS_FILE = os.path.join(CLAUDE_CONFIG_DIR, ".credentials.json")
CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_API_MIN_INTERVAL = 120    # 이 엔드포인트는 자주 부르면 429를 돌려주므로 최소 간격을 둔다 (초)
# 전체 주간 한도와 별개로, 특정 모델에만 걸리는 주간 한도를 한 줄 더 보여 준다.
# 계정에 그 한도가 없으면 "값 없음"으로 나온다. (opus, sonnet 등으로 바꿔도 된다)
CLAUDE_SCOPED_WEEKLY = "fable"
CLAUDE_STATE_FILE = os.path.join(CLAUDE_CONFIG_DIR, "statusline-state.json")
# Claude Code의 로그인 토큰은 몇 시간이면 만료되고, Claude Code를 실행할 때만 갱신된다.
# 만료돼 있으면 `claude -p /usage` 를 한 번 실행해 갱신한다. /usage 는 모델을 부르지 않는 로컬 명령이다.
# (2.1.278 미만에서는 갱신한 토큰을 저장하기 전에 끝나 로그인이 풀릴 수 있다고 보고돼 있어 실행하지 않는다)
CLAUDE_AUTO_REFRESH = True
CLAUDE_REFRESH_MIN_VERSION = (2, 1, 278)
CLAUDE_REFRESH_COOLDOWN_SEC = 1800

# --- GPT 실제 연동용 ---
# 1순위: Codex CLI가 로그인해 둔 토큰으로 ChatGPT 백엔드에 현재 한도를 물어본다 (지금 값).
# 2순위: 실패하면 Codex 세션 로그에 마지막으로 기록된 값을 읽는다 (마지막 대화 시점의 값).
CODEX_AUTH_FILE = os.path.expanduser("~/.codex/auth.json")
CODEX_USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/backend-api/codex/usage",
)
CODEX_SESSIONS_DIR = os.path.expanduser("~/.codex/sessions")
CODEX_MAX_FILES = 8              # 최근 파일 몇 개까지 뒤져 볼지
HTTP_TIMEOUT_SEC = 10
# 2순위 경로(브리지 파일, 세션 로그)의 값은 이보다 오래됐으면 쓰지 않는다. 옛 값을 지금 값처럼 보이지 않게.
FALLBACK_MAX_AGE_SEC = 900


# ══════════════════════════════════════════════════════════════════════════════
# [2] 데이터 모델
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Window:
    """한도 창 하나. used_pct가 None이면 '값을 모름'."""
    used_pct: Optional[float] = None
    resets_at: Optional[datetime] = None
    detail: str = ""                         # 곁들일 설명 (없으면 빈 문자열)
    measured_at: Optional[datetime] = None   # 이 값이 실제로 측정된 시각 (CLI가 마지막으로 남긴 때)


@dataclass
class ProviderUsage:
    five_hour: Window
    seven_day: Window
    scoped_week: Optional[Window] = None     # 특정 모델에만 걸리는 주간 한도 (없으면 None)


@dataclass
class Snapshot:
    fetched_at: datetime
    is_mock: bool
    claude: Optional[ProviderUsage] = None
    gpt: Optional[ProviderUsage] = None
    claude_error: Optional[str] = None
    gpt_error: Optional[str] = None


def now_local() -> datetime:
    return datetime.now().astimezone()


def _parse_reset(value) -> Optional[datetime]:
    """epoch 초(숫자)나 ISO 8601 문자열 둘 다 받는다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).astimezone()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# [3] Claude 사용량 모듈
# ══════════════════════════════════════════════════════════════════════════════
class _MockClaude:
    five = 63.0
    week = 38.0
    five_reset: Optional[datetime] = None
    week_reset: Optional[datetime] = None


def _mock_claude_usage() -> ProviderUsage:
    """새로고침할 때마다 사용률이 조금씩 오르고, 100%를 넘기면 새 창으로 리셋되는 더미."""
    time.sleep(random.uniform(0.3, 0.7))     # 네트워크/CLI 지연 흉내 (UI가 안 멈추는지 확인용)
    st, now = _MockClaude, now_local()
    if st.five_reset is None:
        st.five_reset = now + timedelta(hours=2, minutes=14)
        st.week_reset = now + timedelta(days=3, hours=5)
    else:
        st.five += random.uniform(1.5, 6.0)
        st.week += random.uniform(0.2, 0.9)
    if st.five >= 100.0 or now >= st.five_reset:
        st.five = random.uniform(2.0, 8.0)
        st.five_reset = now + timedelta(hours=5)
    if st.week >= 100.0:
        st.week = random.uniform(1.0, 5.0)
        st.week_reset = now + timedelta(days=7)
    return ProviderUsage(
        five_hour=Window(st.five, st.five_reset, measured_at=now),
        seven_day=Window(st.week, st.week_reset, measured_at=now),
    )


_claude_cache = {"at": 0.0, "usage": None}   # 429를 피하려고 마지막 응답을 잠시 들고 있는다


def _claude_token() -> str:
    """Claude Code가 로그인하며 저장해 둔 OAuth 토큰. (이 파일이 곧 '어느 계정인지'에 해당한다.)"""
    try:
        with open(CLAUDE_CREDENTIALS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RuntimeError("Claude Code 로그인 정보가 없습니다. claude 로 로그인해 보세요")
    except (OSError, ValueError) as e:
        raise RuntimeError(f"로그인 정보를 읽지 못했습니다: {e}")

    oauth = data.get("claudeAiOauth") or data
    token = oauth.get("accessToken") or oauth.get("access_token")
    if not token:
        raise RuntimeError("구독 계정 토큰이 없습니다 (API 키 사용 중이면 한도 값이 없습니다)")
    expires = oauth.get("expiresAt") or oauth.get("expires_at")
    if isinstance(expires, (int, float)) and expires / 1000.0 <= time.time():
        raise RuntimeError("토큰이 만료됐습니다. claude 를 한 번 실행하면 갱신됩니다")
    return token


def _claude_windows(data: dict, measured: datetime) -> ProviderUsage:
    """
    두 가지 응답 모양을 모두 받는다.
      예전: {"five_hour": {"utilization": 35.0, "resets_at": "..."}, "seven_day": {...}}
      최근: {"limits": [{"kind": "session", "percent": 35.0, "resets_at": "..."}, ...]}
    """
    five, week = Window(), Window()

    def make(raw: dict) -> Window:
        pct = raw.get("utilization", raw.get("percent"))
        if pct is None:
            return Window()
        return Window(float(pct), _parse_reset(raw.get("resets_at")), measured_at=measured)

    scoped: dict = {}                        # {"opus": Window, "fable": Window, ...}

    for item in (data.get("limits") or []):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "session":
            five = make(item)
        elif kind == "weekly_all":
            week = make(item)
        elif kind == "weekly_scoped":
            name = item.get("scope") or item.get("name") or item.get("model")
            if name:
                scoped[str(name).lower()] = make(item)
    for key, is_week in (("five_hour", False), ("seven_day", True)):
        raw = data.get(key)
        if isinstance(raw, dict):
            win = make(raw)
            if win.used_pct is None:
                continue
            if is_week and week.used_pct is None:
                week = win
            elif not is_week and five.used_pct is None:
                five = win

    # 예전 형식의 모델별 버킷: seven_day_opus, seven_day_sonnet, seven_day_fable ...
    for key, raw in data.items():
        if not key.startswith("seven_day_") or not isinstance(raw, dict):
            continue
        win = make(raw)
        if win.used_pct is not None:
            scoped.setdefault(key[len("seven_day_"):].lower(), win)

    wanted = CLAUDE_SCOPED_WEEKLY.lower()
    match = scoped.get(wanted)
    if match is None:                        # 키 이름이 조금 다를 수 있어 부분 일치도 본다
        for name, win in scoped.items():
            if wanted in name:
                match = win
                break
    return ProviderUsage(five, week, match)


_claude_refresh_state = {"at": 0.0, "note": ""}


def _find_claude_cli() -> Optional[str]:
    # 바탕화면 아이콘으로 실행하면 PATH에 ~/.local/bin 이 없을 수 있어 흔한 설치 위치를 직접 본다.
    for path in (shutil.which("claude"),
                 os.path.expanduser("~/.local/bin/claude"),
                 os.path.expanduser("~/.claude/local/claude"),
                 "/usr/local/bin/claude", "/usr/bin/claude"):
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _refresh_claude_login() -> str:
    """
    `claude -p /usage` 로 Claude Code가 스스로 토큰을 갱신하게 한다.
    성공적으로 실행했으면 빈 문자열, 못 했으면 이유를 돌려준다. 30분에 한 번만 시도한다.
    """
    st = _claude_refresh_state
    if not CLAUDE_AUTO_REFRESH:
        return "자동 갱신이 꺼져 있음"
    if time.time() - st["at"] < CLAUDE_REFRESH_COOLDOWN_SEC:
        return st["note"] or "최근에 갱신을 시도함"
    st["at"] = time.time()

    exe = _find_claude_cli()
    if not exe:
        st["note"] = "claude 명령을 찾지 못함"
        return st["note"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=20, creationflags=flags).stdout
    except Exception as e:
        st["note"] = f"버전 확인 실패: {e}"
        return st["note"]
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    ver = tuple(int(x) for x in m.groups()) if m else None
    if ver is None or ver < CLAUDE_REFRESH_MIN_VERSION:
        have = ".".join(map(str, ver)) if ver else "버전 불명"
        need = ".".join(map(str, CLAUDE_REFRESH_MIN_VERSION))
        st["note"] = f"Claude Code {have}: 자동 갱신은 {need} 이상에서만 (claude update)"
        return st["note"]
    try:
        subprocess.run([exe, "-p", "/usage"], capture_output=True, text=True, timeout=90,
                       stdin=subprocess.DEVNULL, cwd=os.path.expanduser("~"), creationflags=flags)
    except Exception as e:
        st["note"] = f"갱신 실행 실패: {e}"
        return st["note"]
    st["note"] = ""
    return ""


def _refreshed_claude_token(reason: str) -> str:
    note = _refresh_claude_login()
    try:
        return _claude_token()
    except RuntimeError:
        if not note:
            note = _claude_refresh_state["note"] = "갱신을 시도했지만 토큰이 그대로 만료 상태"
        raise RuntimeError(f"로그인 갱신 필요: 터미널에서 claude 를 한 번 실행하세요 ({note or reason})")


def _claude_from_api() -> ProviderUsage:
    cached = _claude_cache["usage"]
    if cached is not None and time.time() - _claude_cache["at"] < CLAUDE_API_MIN_INTERVAL:
        return cached                        # 아직 신선하다: 다시 부르지 않는다

    try:
        token = _claude_token()
    except RuntimeError as e:
        if "만료" not in str(e):
            raise
        token = _refreshed_claude_token(str(e))

    def call(tok: str) -> dict:
        req = urllib.request.Request(CLAUDE_USAGE_URL, headers={
            "Authorization": f"Bearer {tok}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        try:
            data = call(token)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            data = call(_refreshed_claude_token("토큰이 거절됨"))   # 만료 시각 전에 거절된 경우 한 번 더
    except urllib.error.HTTPError as e:
        if e.code == 429 and cached is not None:
            return cached                    # 잠깐 막힌 것뿐이니 직전 값을 그대로 쓴다
        if e.code in (401, 403):
            raise RuntimeError("로그인 갱신 필요: 터미널에서 claude 를 한 번 실행하세요 (토큰이 거절됨)")
        raise RuntimeError(f"HTTP {e.code}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(str(e) or e.__class__.__name__)

    usage = _claude_windows(data, now_local())
    if usage.five_hour.used_pct is None and usage.seven_day.used_pct is None:
        raise RuntimeError("응답에 한도 값이 없습니다 (구독 계정이 아닐 수 있습니다)")
    _claude_cache.update(at=time.time(), usage=usage)
    return usage


def _read_claude_state() -> ProviderUsage:
    """
    브리지가 남긴 파일을 읽는다. 형식:
        {"updated_at": 1784199500,
         "rate_limits": {"five_hour": {"used_percentage": 30.0, "resets_at": 1784203100},
                         "seven_day": {"used_percentage": 9.0,  "resets_at": 1784458700}}}
    """
    try:
        with open(CLAUDE_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(
            "statusLine 브리지가 아직 설치되지 않았습니다. "
            "install_claude_bridge.sh 를 실행한 뒤 Claude Code에서 질문을 한 번 보내세요.")
    except (OSError, ValueError) as e:
        raise RuntimeError(f"상태 파일을 읽지 못했습니다: {e}")

    limits = data.get("rate_limits") or {}
    updated_at = _parse_reset(data.get("updated_at"))

    def win(key: str) -> Window:
        raw = limits.get(key) or {}
        pct = raw.get("used_percentage", raw.get("used_percent"))
        resets_at = _parse_reset(raw.get("resets_at"))
        if pct is None:
            return Window()
        if resets_at is not None and resets_at <= now_local():
            return Window()                  # 창이 이미 리셋됨 = 지금 값은 알 수 없음
        return Window(float(pct), resets_at, measured_at=updated_at)

    five, week = win("five_hour"), win("seven_day")
    if five.used_pct is None and week.used_pct is None:
        raise RuntimeError(
            "상태 파일에 한도 값이 없습니다. Claude Code에서 질문을 한 번 보내면 채워집니다. "
            "(한도 값은 claude.ai Pro/Max 구독 계정에만 내려옵니다.)")
    return ProviderUsage(five, week)


def _is_fresh(usage: ProviderUsage) -> bool:
    times = [w.measured_at for w in (usage.five_hour, usage.seven_day)
             if w.used_pct is not None and w.measured_at is not None]
    return bool(times) and (now_local() - max(times)).total_seconds() <= FALLBACK_MAX_AGE_SEC


def _real_claude_usage() -> ProviderUsage:
    """
    먼저 계정에 직접 물어본다. 실패했을 때 브리지 파일은 최근(15분 이내) 값일 때만 쓴다.
    오래된 값을 보여 주면 지금 값처럼 오해하기 쉬워서, 그럴 바엔 실패 이유를 보여 준다.
    """
    try:
        return _claude_from_api()
    except Exception as api_error:
        try:
            usage = _read_claude_state()
        except Exception:
            raise RuntimeError(str(api_error))
        if _is_fresh(usage):
            return usage
        raise RuntimeError(str(api_error))


def fetch_claude_usage(use_mock: bool = USE_MOCK) -> ProviderUsage:
    return _mock_claude_usage() if use_mock else _real_claude_usage()


# ══════════════════════════════════════════════════════════════════════════════
# [4] GPT 사용량 모듈
# ══════════════════════════════════════════════════════════════════════════════
class _MockGPT:
    five = 41.0
    week = 57.0
    five_reset: Optional[datetime] = None
    week_reset: Optional[datetime] = None


def _mock_gpt_usage() -> ProviderUsage:
    time.sleep(random.uniform(0.2, 0.5))
    st, now = _MockGPT, now_local()
    if st.five_reset is None:
        st.five_reset = now + timedelta(hours=3, minutes=41)
        st.week_reset = now + timedelta(days=5, hours=2)
    else:
        st.five += random.uniform(1.0, 4.0)
        st.week += random.uniform(0.1, 0.6)
    if st.five >= 100.0 or now >= st.five_reset:
        st.five = random.uniform(1.0, 6.0)
        st.five_reset = now + timedelta(hours=5)
    if st.week >= 100.0:
        st.week = random.uniform(1.0, 5.0)
        st.week_reset = now + timedelta(days=7)
    return ProviderUsage(Window(st.five, st.five_reset), Window(st.week, st.week_reset))


def _recent_codex_logs(limit: int = CODEX_MAX_FILES) -> list[str]:
    paths = glob.glob(os.path.join(CODEX_SESSIONS_DIR, "**", "rollout-*.jsonl"), recursive=True)
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return paths[:limit]


def _gpt_from_logs() -> ProviderUsage:
    """
    Codex CLI 세션 로그에서 가장 최근의 rate_limits를 읽는다. 각 줄이 JSON 한 건이고,
    token_count 이벤트가 아래 모양을 담고 있다.
        "rate_limits": {"primary":   {"used_percent": 14.0, "window_minutes": 300,   "resets_at": ...},
                        "secondary": {"used_percent": 19.0, "window_minutes": 10080, "resets_at": ...}}
    창 길이(window_minutes)로 5시간/주간을 가른다. primary/secondary 자리는 고정이 아니다.
    """
    logs = _recent_codex_logs()
    if not logs:
        raise RuntimeError(f"Codex 세션 로그가 없습니다 ({CODEX_SESSIONS_DIR})")

    for path in logs:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        for line in reversed(lines):         # 가장 최근 이벤트부터 거슬러 올라간다
            line = line.strip()
            if not line or "rate_limits" not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            limits = (event.get("payload") or event).get("rate_limits")
            if not isinstance(limits, dict):
                continue
            measured_at = _parse_reset(event.get("timestamp")) or _parse_reset(os.path.getmtime(path))

            five, week = Window(), Window()
            for key in ("primary", "secondary"):
                raw = limits.get(key)
                if not isinstance(raw, dict):
                    continue
                pct = raw.get("used_percent")
                if pct is None:
                    continue
                resets_at = _parse_reset(raw.get("resets_at"))
                if resets_at is not None and resets_at <= now_local():
                    continue                 # 창이 이미 리셋됨 = 지금 값은 알 수 없음
                w = Window(float(pct), resets_at, measured_at=measured_at)
                minutes = raw.get("window_minutes") or 0
                if minutes >= 1440:          # 하루보다 길면 주간 창으로 본다
                    week = w
                else:
                    five = w
            if five.used_pct is not None or week.used_pct is not None:
                return ProviderUsage(five, week)

    raise RuntimeError("세션 로그에서 rate_limits를 찾지 못했습니다")


def _codex_auth() -> tuple[str, str]:
    """Codex CLI가 로그인하며 저장해 둔 토큰을 읽는다. (이 파일이 곧 '어느 계정인지'에 해당한다.)"""
    try:
        with open(CODEX_AUTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Codex 로그인 정보가 없습니다 ({CODEX_AUTH_FILE})")
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Codex 로그인 정보를 읽지 못했습니다: {e}")

    tokens = data.get("tokens") or data
    access = tokens.get("access_token") or tokens.get("accessToken")
    if not access:
        raise RuntimeError("access_token이 없습니다. codex 로 다시 로그인해 보세요")
    account = tokens.get("account_id") or tokens.get("accountId") or data.get("account_id") or ""
    return access, account


def _collect_windows(node, found: Optional[list] = None) -> list:
    """
    응답 어디에 들어 있든 '사용률 + 창 길이'를 가진 객체를 전부 긁어 온다.
    키 이름이 버전마다 조금씩 달라서(used_percent / used_percentage,
    limit_window_seconds / window_minutes, resets_at / reset_at / resets_in_seconds) 넓게 받는다.
    """
    if found is None:
        found = []
    if isinstance(node, list):
        for item in node:
            _collect_windows(item, found)
        return found
    if not isinstance(node, dict):
        return found

    pct = node.get("used_percent", node.get("used_percentage"))
    seconds = node.get("limit_window_seconds", node.get("window_seconds"))
    if seconds is None and node.get("window_minutes") is not None:
        seconds = float(node["window_minutes"]) * 60
    if pct is not None and seconds:
        resets = _parse_reset(node.get("resets_at", node.get("reset_at")))
        if resets is None:
            after = node.get("resets_in_seconds", node.get("reset_after_seconds"))
            if after is not None:
                resets = now_local() + timedelta(seconds=float(after))
        found.append((float(seconds), float(pct), resets))

    for value in node.values():
        _collect_windows(value, found)
    return found


_GPT_OTHER_LIMITS = ("chatpass", "code_review_rate_limit", "additional_rate_limits")


def _gpt_windows(data: dict, measured: datetime) -> ProviderUsage:
    """
    본 한도는 rate_limit.primary_window(5시간) / secondary_window(주간)에 있다.
    같은 응답에 chatpass, code_review_rate_limit 같은 다른 한도도 주간 창을 달고 오므로,
    rate_limit 이 있으면 그것만 보고, 없을 때만 다른 한도를 뺀 나머지에서 찾는다.
    """
    main = data.get("rate_limit")
    source = main if isinstance(main, dict) else {
        k: v for k, v in data.items() if k not in _GPT_OTHER_LIMITS}
    five, week = Window(), Window()
    for seconds, pct, resets in _collect_windows(source):
        win = Window(pct, resets, measured_at=measured)
        if seconds >= 86400:                 # 하루보다 길면 주간 창
            if week.used_pct is None:
                week = win
        elif five.used_pct is None:
            five = win
    return ProviderUsage(five, week)


def _gpt_from_api() -> ProviderUsage:
    access, account = _codex_auth()
    headers = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}
    if account:
        headers["ChatGPT-Account-Id"] = account

    errors = []
    for url in CODEX_USAGE_URLS:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError("로그인 갱신 필요: 터미널에서 codex 를 한 번 실행하세요")
            errors.append(f"HTTP {e.code}")
            continue
        except Exception as e:                # 네트워크 단절, JSON 깨짐 등
            errors.append(str(e) or e.__class__.__name__)
            continue

        usage = _gpt_windows(data, now_local())
        if usage.five_hour.used_pct is not None or usage.seven_day.used_pct is not None:
            return usage
        errors.append("응답에 한도 값이 없음")

    raise RuntimeError("; ".join(errors) or "사용량을 받지 못했습니다")


def _real_gpt_usage() -> ProviderUsage:
    """먼저 계정에 직접 물어본다. 실패했을 때 세션 로그는 최근(15분 이내) 값일 때만 쓴다."""
    try:
        return _gpt_from_api()
    except Exception as api_error:
        try:
            usage = _gpt_from_logs()
        except Exception:
            raise RuntimeError(str(api_error))
        if _is_fresh(usage):
            return usage
        raise RuntimeError(str(api_error))


def fetch_gpt_usage(use_mock: bool = USE_MOCK) -> ProviderUsage:
    return _mock_gpt_usage() if use_mock else _real_gpt_usage()


# ══════════════════════════════════════════════════════════════════════════════
# [5] 백그라운드 워커 (QThread 안에서 동작, UI 스레드를 막지 않음)
# ══════════════════════════════════════════════════════════════════════════════
class UsageWorker(QObject):
    fetch_started = pyqtSignal()
    snapshot_ready = pyqtSignal(object)      # Snapshot

    def __init__(self, interval_sec: int, claude_on: bool = True, gpt_on: bool = True):
        super().__init__()
        self._interval_ms = int(interval_sec * 1000)
        self._timer: Optional[QTimer] = None
        self._claude_on = claude_on
        self._gpt_on = gpt_on

    @pyqtSlot()
    def start(self) -> None:
        # 타이머는 반드시 워커 스레드 안에서 생성해야 그 스레드의 이벤트 루프에서 돈다.
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    @pyqtSlot()
    def refresh(self) -> None:
        self.fetch_started.emit()
        snap = Snapshot(fetched_at=now_local(), is_mock=USE_MOCK)
        # 한쪽이 실패해도 다른 쪽은 그대로 표시되도록 따로 감싼다. 숨긴 서비스는 건너뛴다.
        if self._claude_on:
            try:
                snap.claude = fetch_claude_usage()
            except Exception as e:           # noqa: BLE001
                snap.claude_error = str(e) or e.__class__.__name__
        if self._gpt_on:
            try:
                snap.gpt = fetch_gpt_usage()
            except Exception as e:           # noqa: BLE001
                snap.gpt_error = str(e) or e.__class__.__name__
        snap.fetched_at = now_local()
        self.snapshot_ready.emit(snap)
        if self._timer is not None:
            self._timer.start()              # 수동 새로고침 후에는 주기를 다시 센다

    @pyqtSlot(bool, bool)
    def set_providers(self, claude_on: bool, gpt_on: bool) -> None:
        newly_on = (claude_on and not self._claude_on) or (gpt_on and not self._gpt_on)
        self._claude_on, self._gpt_on = claude_on, gpt_on
        if newly_on and self._timer is not None:
            self.refresh()                   # 다시 켠 서비스는 30초를 기다리지 않고 바로 채운다

    @pyqtSlot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        QThread.currentThread().quit()


# ══════════════════════════════════════════════════════════════════════════════
# [6] UI
# ══════════════════════════════════════════════════════════════════════════════
# 색 토큰 (카드 색을 바꾸면 set_theme 이 다시 정한다)
C_BASE = "#1A1F2E"       # 카드 바탕 (남색 기운의 슬레이트)
C_EDGE = "#2E364D"       # 카드 외곽선, 구분선
C_TRACK = "#2A3145"      # 미터의 빈 칸
C_TEXT = "#E8EBF4"
C_MUTED = "#8C95AD"
C_OK = "#6FD3B1"
C_WARN = "#F0C05A"
C_CRIT = "#F0706A"
_DEFAULT_TOKENS = (C_BASE, C_EDGE, C_TRACK, C_TEXT, C_MUTED, C_OK, C_WARN, C_CRIT)
_LIGHT_STATUS = ("#0E7052", "#8F5E00", "#B8312C")   # 밝은 바탕에서도 글자로 읽히게(대비 4.5 이상) 진하게 한 OK / WARN / CRIT

# 색상 메뉴의 견본. 윗줄은 어두운 바탕, 아랫줄은 밝은 바탕
THEME_DEFAULT = C_BASE
THEME_PRESETS = (
    ("남색 (기본)", "#1A1F2E"), ("먹색", "#1F2023"), ("숲", "#13251F"),
    ("자주", "#2A1722"), ("보라", "#221B35"), ("바다", "#0E2236"),
    ("흰색", "#F7F8FA"), ("미색", "#F6F1E6"), ("민트", "#E4F3EC"),
    ("하늘", "#E5EFFA"), ("라벤더", "#EEE8F8"), ("벚꽃", "#F9E8EE"),
)
PALETTE_COLUMNS = 6


def _mix(a: str, b: str, t: float) -> str:
    """색 a 에서 b 쪽으로 t(0~1)만큼 옮긴 색."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def is_light(color: str) -> bool:
    c = QColor(color)
    return 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF() > 0.5


def set_theme(base: str) -> None:
    """
    카드 바탕색 하나로 나머지 색 토큰을 정한다. 기본 색이면 손으로 맞춘 원래 값을 그대로 쓴다.
    선과 미터 빈 칸은 바탕에서 글자색 쪽으로 조금, 흐린 글자는 절반 남짓 옮긴 색이다.
    """
    global C_BASE, C_EDGE, C_TRACK, C_TEXT, C_MUTED, C_OK, C_WARN, C_CRIT
    if QColor(base) == QColor(THEME_DEFAULT):
        C_BASE, C_EDGE, C_TRACK, C_TEXT, C_MUTED, C_OK, C_WARN, C_CRIT = _DEFAULT_TOKENS
        return
    light = is_light(base)
    C_BASE = QColor(base).name()
    C_TEXT = _mix("#000000", C_BASE, 0.12) if light else _mix("#FFFFFF", C_BASE, 0.1)
    C_MUTED = _mix(C_BASE, C_TEXT, 0.66 if light else 0.58)
    C_EDGE = _mix(C_BASE, C_TEXT, 0.13)
    C_TRACK = _mix(C_BASE, C_TEXT, 0.09)
    C_OK, C_WARN, C_CRIT = _LIGHT_STATUS if light else _DEFAULT_TOKENS[5:]


CARD_WIDTH = 292
CARD_RADIUS = 12

# 크기 조정: 카드 전체(글꼴, 여백, 미터, 버튼)를 같은 비율로 키우거나 줄인다. 단위는 %.
UI_SCALE_MIN = 75
UI_SCALE_MAX = 200
UI_SCALE_STEP = 5                # 이 단위로 끊어서 바꾼다 (바뀔 때마다 카드 안쪽을 새로 만들기 때문)
UI_SCALE_PRESETS = (80, 90, 100, 115, 130, 150)
_ui_scale = 1.0                  # 지금 배율. UsageCard.set_scale 만 바꾼다

# 앞쪽은 Windows, 뒤쪽은 Ubuntu 기본 글꼴. 설치된 첫 번째 글꼴이 쓰인다.
UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Malgun Gothic",
               "Ubuntu", "Noto Sans CJK KR", "DejaVu Sans"]
NUM_FAMILIES = ["Bahnschrift", "Segoe UI", "Ubuntu", "Noto Sans CJK KR", "DejaVu Sans"]   # 숫자 전용


def sp(n: float) -> int:
    """100%일 때의 px 값을 지금 배율에 맞춘 px로 바꾼다."""
    return max(1, round(n * _ui_scale))


def make_font(px: int, weight: QFont.Weight = QFont.Weight.Normal, families=None) -> QFont:
    f = QFont()
    f.setFamilies(families or UI_FAMILIES)
    f.setPixelSize(sp(px))
    f.setWeight(weight)
    return f


def make_label(text: str, px: int, color: str,
               weight: QFont.Weight = QFont.Weight.Normal, families=None) -> QLabel:
    lb = QLabel(text)
    lb.setFont(make_font(px, weight, families))
    lb.setStyleSheet(f"color: {color}; background: transparent;")
    return lb


def status_color(pct: float) -> str:
    if pct >= CRITICAL_PCT:
        return C_CRIT
    if pct >= WARN_PCT:
        return C_WARN
    return C_OK


def fmt_age(measured_at: Optional[datetime], stale_after_sec: int = 180) -> str:
    """CLI가 값을 남긴 지 오래됐을 때만 '몇 분 전 값'이라고 알린다. 아니면 빈 문자열."""
    if measured_at is None:
        return ""
    secs = int((now_local() - measured_at).total_seconds())
    if secs < stale_after_sec:
        return ""
    if secs < 3600:
        return f"{secs // 60}분 전 값"
    if secs < 86400:
        return f"{secs // 3600}시간 전 값"
    return f"{secs // 86400}일 전 값"


def fmt_remaining_time(target: Optional[datetime], suffix: str = " 뒤 리셋") -> str:
    if target is None:
        return ""
    secs = int((target - now_local()).total_seconds())
    if secs <= 60:
        return "곧 리셋"
    d, h, m = secs // 86400, secs % 86400 // 3600, secs % 3600 // 60
    if d:
        return f"{d}일 {h}시간{suffix}" if h else f"{d}일{suffix}"
    return f"{h}시간 {m}분{suffix}" if h else f"{m}분{suffix}"


class SegmentMeter(QWidget):
    """연료계처럼 칸이 나뉜 사용률 미터. 한 칸 = 100 / segments %."""

    def __init__(self, segments: int = 24, height: int = 10, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._segments = segments
        self._value = 0.0
        self._color = QColor(C_OK)
        self.setFixedHeight(sp(height))
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(500)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = max(0.0, min(100.0, float(v)))
        self.update()

    value = pyqtProperty(float, fget=_get_value, fset=_set_value)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_now(self, v: float) -> None:
        """애니메이션 없이 즉시 값을 바꾼다 (값을 모를 때 미터를 비우는 용도)."""
        self._anim.stop()
        self._set_value(v)

    def animate_to(self, v: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(max(0.0, min(100.0, float(v))))
        self._anim.start()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        n, gap, r = self._segments, 2.0 * _ui_scale, 2.0 * _ui_scale
        w = (self.width() - gap * (n - 1)) / n
        h = float(self.height())
        filled = self._value / 100.0 * n
        track = QColor(C_TRACK)
        for i in range(n):
            x = i * (w + gap)
            seg = QRectF(x, 0.0, w, h)
            p.setBrush(track)
            p.drawRoundedRect(seg, r, r)
            frac = max(0.0, min(1.0, filled - i))
            if frac > 0.0:
                p.save()
                p.setClipRect(QRectF(x, 0.0, w * frac, h))
                p.setBrush(self._color)
                p.drawRoundedRect(seg, r, r)
                p.restore()
        p.end()


class IconButton(QAbstractButton):
    """
    직접 그리는 아이콘 버튼 (폰트 글리프에 의존하지 않음).
    kind: 'refresh' | 'close' | 'chevron' | 'more' | 'minimize' | 'expand'
    """

    def __init__(self, kind: str, tooltip: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._kind = kind
        self._angle = 0.0
        self._flip = False               # chevron: True면 위쪽 방향(접기)
        self._hover = False
        self._kbd_focus = False
        self._side = sp(22)
        self.setFixedSize(self._side, self._side)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._spin = QPropertyAnimation(self, b"angle", self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(900)
        self._spin.setLoopCount(-1)

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, a: float) -> None:
        self._angle = a
        self.update()

    angle = pyqtProperty(float, fget=_get_angle, fset=_set_angle)

    def set_spinning(self, on: bool) -> None:
        if on and self._spin.state() != QPropertyAnimation.State.Running:
            self._spin.start()
        elif not on:
            self._spin.stop()
            self._set_angle(0.0)

    def set_flipped(self, on: bool) -> None:
        self._flip = on
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._side, self._side)

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def focusInEvent(self, e) -> None:
        # 포커스 링은 Tab 키로 들어왔을 때만 그린다 (마우스 클릭이나 창 활성화 때는 숨김).
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        self._kbd_focus = False
        super().focusOutEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        k = self.width() / 22.0               # 아래 좌표는 22px 기준. 배율만큼 키워서 그린다

        active = self._hover and self.isEnabled()
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C_TRACK))
            p.drawRoundedRect(box, 6 * k, 6 * k)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(QColor(C_OK), 1.2 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 6 * k, 6 * k)

        if self._kind == "close" and active:
            ink = QColor(C_CRIT)
        elif active or self._spin.state() == QPropertyAnimation.State.Running or (
                self._kind == "chevron" and self._flip):
            ink = QColor(C_TEXT)
        else:
            ink = QColor(C_MUTED)
        pen = QPen(ink, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.scale(k, k)
        if self._kind == "close":
            d = 3.6
            p.drawLine(QPointF(-d, -d), QPointF(d, d))
            p.drawLine(QPointF(-d, d), QPointF(d, -d))
        elif self._kind == "minimize":
            p.drawLine(QPointF(-4.2, 0.0), QPointF(4.2, 0.0))
        elif self._kind == "expand":
            p.drawRoundedRect(QRectF(-4.0, -4.0, 8.0, 8.0), 1.5, 1.5)
        elif self._kind == "more":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ink)
            for dx in (-4.5, 0.0, 4.5):
                p.drawEllipse(QPointF(dx, 0.0), 1.3, 1.3)
        elif self._kind == "chevron":
            w, h = 4.2, 2.4
            s = -1.0 if self._flip else 1.0   # 펼쳐져 있으면 위쪽 화살표
            p.drawLine(QPointF(-w, -h * s), QPointF(0.0, h * s))
            p.drawLine(QPointF(0.0, h * s), QPointF(w, -h * s))
        else:
            p.rotate(self._angle)
            r = 5.2
            # 50° 에서 시계 방향으로 280° -> 위쪽이 트인 원호, 끝점(130°)에 화살촉
            p.drawArc(QRectF(-r, -r, 2 * r, 2 * r), 50 * 16, -280 * 16)
            th = math.radians(130.0)
            tip = QPointF(r * math.cos(th), -r * math.sin(th))
            tx, ty = math.sin(th), math.cos(th)          # 시계 방향 진행의 접선 (화면 좌표)
            for spread in (-0.75, 0.75):
                c, s = math.cos(spread), math.sin(spread)
                bx, by = -(tx * c - ty * s), -(tx * s + ty * c)
                p.drawLine(tip, QPointF(tip.x() + bx * 3.4, tip.y() + by * 3.4))
        p.end()


class WeeklyRow(QWidget):
    """주간 한도 한 줄: 라벨 / 가는 미터 / 사용률 / 리셋까지 남은 시간."""

    def __init__(self, label: str = "주간", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._label = make_label(label, 11, C_MUTED)
        self._label.setMinimumWidth(sp(52))
        self._meter = SegmentMeter(segments=18, height=6)
        self._meter.setMinimumWidth(sp(70))
        self._pct = make_label("", 12, C_TEXT, QFont.Weight.DemiBold, NUM_FAMILIES)
        self._reset = make_label("", 11, C_MUTED)
        self._reset.setMinimumWidth(sp(56))
        self._reset.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sp(8))
        row.addWidget(self._label)
        row.addWidget(self._meter, 1)
        row.addWidget(self._pct)
        row.addWidget(self._reset)

    def set_window(self, win: Window, animate: bool = True) -> None:
        if win.used_pct is None:
            self._meter.set_now(0.0)
            self._pct.setText("–")
            self._pct.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
            self._reset.setText("값 없음")
            self._reset.setToolTip("이 계정에 해당 한도가 없거나 값을 읽지 못했습니다")
            return
        pct = win.used_pct
        self._meter.set_color(status_color(pct))
        if animate:
            self._meter.animate_to(pct)
        else:
            self._meter.set_now(pct)
        self._pct.setText(f"{pct:.0f}%")
        self._pct.setStyleSheet(
            f"color: {C_TEXT if pct < WARN_PCT else status_color(pct)}; background: transparent;")
        stale = fmt_age(win.measured_at)
        self._reset.setText(stale or fmt_remaining_time(win.resets_at, " 뒤"))
        self._reset.setToolTip(
            f"{win.measured_at:%H:%M:%S} 기준 값 · {fmt_remaining_time(win.resets_at)}"
            if win.measured_at else "")


class UsageSection(QWidget):
    """서비스 한 개 분량: 이름 + 5시간 사용률 + 미터 + 잔여량, 그리고 접히는 주간 줄."""

    def __init__(self, name: str, scoped_label: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._name = make_label(name, 13, C_TEXT, QFont.Weight.DemiBold)
        self._caption = make_label("5시간 한도", 11, C_MUTED)
        self._pct = QLabel()
        self._pct.setFont(make_font(21, QFont.Weight.DemiBold, NUM_FAMILIES))
        self._pct.setStyleSheet("background: transparent;")
        self._pct.setTextFormat(Qt.TextFormat.RichText)
        self._meter = SegmentMeter()
        self._left = make_label("", 11, C_TEXT)
        self._right = make_label("", 11, C_MUTED)
        self.weekly = WeeklyRow("주간 전체")
        self.weekly.setVisible(False)
        self.weekly_scoped: Optional[WeeklyRow] = None
        if scoped_label:                     # Claude처럼 모델별 주간 한도가 따로 있는 경우만
            self.weekly_scoped = WeeklyRow(f"주간 {scoped_label}")
            self.weekly_scoped.setVisible(False)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(sp(6))
        head.addWidget(self._name, 0, Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self._caption, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        head.addWidget(self._pct, 0, Qt.AlignmentFlag.AlignBottom)

        detail = QHBoxLayout()
        detail.setContentsMargins(0, 0, 0, 0)
        detail.addWidget(self._left)
        detail.addStretch(1)
        detail.addWidget(self._right)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(sp(5))
        col.addLayout(head)
        col.addWidget(self._meter)
        col.addLayout(detail)
        col.addWidget(self.weekly)
        if self.weekly_scoped is not None:
            col.addWidget(self.weekly_scoped)

        self.set_waiting()

    def _show_pct(self, text: str, color: str) -> None:
        unit = "" if text == "–" else f'<span style="font-size:{sp(12)}px; color:{C_MUTED};">%</span>'
        self._pct.setText(f'<span style="color:{color};">{text}</span>{unit}')

    def set_waiting(self) -> None:
        self._show_pct("–", C_MUTED)
        self._left.setText("불러오는 중…")
        self._left.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
        self._left.setToolTip("")
        self._right.setText("")

    def set_data(self, usage: ProviderUsage, animate: bool = True) -> None:
        five = usage.five_hour
        if five.used_pct is None:
            self._meter.set_now(0.0)
            self._show_pct("–", C_MUTED)
            self._left.setText("5시간 한도 값 없음")
            self._left.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
            self._left.setToolTip("")
            self._right.setText("")
        else:
            pct = five.used_pct
            self._show_pct(f"{pct:.0f}", C_TEXT if pct < WARN_PCT else status_color(pct))
            self._meter.set_color(status_color(pct))
            if animate:
                self._meter.animate_to(pct)
            else:
                self._meter.set_now(pct)
            left = f"{max(0.0, 100.0 - pct):.0f}% 남음"
            if five.detail:
                left += f" ({five.detail})"
            self._left.setText(left)
            self._left.setStyleSheet(f"color: {C_TEXT}; background: transparent;")
            self._left.setToolTip("")
            stale = fmt_age(five.measured_at)
            self._right.setText(stale or fmt_remaining_time(five.resets_at))
            self._right.setToolTip(
                f"{five.measured_at:%H:%M:%S} 기준 값 · {fmt_remaining_time(five.resets_at)}"
                if five.measured_at else "")
        self.weekly.set_window(usage.seven_day, animate)
        if self.weekly_scoped is not None:
            self.weekly_scoped.set_window(usage.scoped_week or Window(), animate)

    def set_error(self, message: str) -> None:
        # 미터와 숫자는 마지막으로 성공한 값을 그대로 두고, 설명 줄에만 실패를 알린다.
        self._left.setText("로그인 갱신 필요" if message.startswith("로그인 갱신 필요") else "불러오지 못함")
        self._left.setStyleSheet(f"color: {C_CRIT}; background: transparent;")
        self._left.setToolTip(message)
        self._right.setText("올려서 원인 보기")


class ResizeGrip(QWidget):
    """카드 오른쪽 아래 모서리의 크기 손잡이. 끌면 카드 전체가 같은 비율로 커지거나 작아진다."""
    pressed = pyqtSignal()
    dragged = pyqtSignal(QPoint)         # 누른 곳에서 얼마나 끌었는지 (화면 좌표)
    released = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._origin: Optional[QPoint] = None
        self._hover = False
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("끌어서 크기 조정 (Ctrl + 휠로도 바꿀 수 있음)")

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        self._origin = e.globalPosition().toPoint()
        self.pressed.emit()
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._origin is not None:
            self.dragged.emit(e.globalPosition().toPoint() - self._origin)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if self._origin is not None and e.button() == Qt.MouseButton.LeftButton:
            self._origin = None
            self.released.emit()
            self.update()
        e.accept()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ink = QColor(C_MUTED)
        if not (self._hover or self._origin is not None):
            ink.setAlphaF(0.5)
        k = self.width() / 14.0               # 아래 좌표는 14px 기준
        pen = QPen(ink, 1.2 * k)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        # 카드의 둥근 모서리 안쪽에 들어가도록 모서리에서 조금 떨어뜨린 빗금 두 줄
        p.drawLine(QPointF(10.0 * k, 4.5 * k), QPointF(4.5 * k, 10.0 * k))
        p.drawLine(QPointF(10.0 * k, 7.5 * k), QPointF(7.5 * k, 10.0 * k))
        p.end()


class StatusDot(QWidget):
    """최소화 막대에서 서비스 이름 앞에 붙는 상태 점 (사용률 색)."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(C_TRACK)
        self.setFixedSize(sp(8), sp(8))

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(QRectF(self.rect()))
        p.end()


class MiniItem(QWidget):
    """최소화 막대의 서비스 한 칸: 상태 점 + 이름 + 5시간 사용률."""

    def __init__(self, name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = name
        self._dot = StatusDot()
        self._name = make_label(name, 11, C_MUTED)
        self._pct = make_label("–", 13, C_MUTED, QFont.Weight.DemiBold, NUM_FAMILIES)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(sp(5))
        row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._name)
        row.addWidget(self._pct)

    def set_state(self, usage: Optional[ProviderUsage], error: Optional[str]) -> None:
        five = usage.five_hour if usage is not None else Window()
        if five.used_pct is None:
            self._pct.setText("–")
            self._pct.setStyleSheet(f"color: {C_MUTED}; background: transparent;")
            self._dot.set_color(C_TRACK)
            tip = "불러오는 중…" if usage is None and not error else "5시간 한도 값 없음"
        else:
            pct = five.used_pct
            self._pct.setText(f"{pct:.0f}%")
            self._pct.setStyleSheet(
                f"color: {C_TEXT if pct < WARN_PCT else status_color(pct)}; background: transparent;")
            self._dot.set_color(status_color(pct))
            remaining = fmt_remaining_time(five.resets_at)
            tip = f"5시간 한도 {pct:.0f}%" + (f" · {remaining}" if remaining else "")
        # 조회가 실패하면 마지막 값은 그대로 두고 이름만 붉게 바꾼다. 이유는 툴팁으로 본다.
        self._name.setStyleSheet(f"color: {C_CRIT if error else C_MUTED}; background: transparent;")
        self.setToolTip(f"{self._title} {tip}" + (f"\n{error}" if error else ""))


class ColorSwatch(QAbstractButton):
    """색상 팔레트의 견본 한 칸. 지금 쓰는 색이면 바깥에 고리를 그린다."""

    def __init__(self, color: str, name: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor(color)
        self._selected = False
        self._hover = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.update()

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._selected or self._hover:
            p.setPen(QPen(QColor(C_TEXT if self._selected else C_MUTED), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))
        outline = QColor(C_MUTED)
        outline.setAlphaF(0.6)                # 메뉴 바탕과 비슷한 색의 견본도 구분되게
        p.setPen(QPen(outline, 1.0))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(self.rect()).adjusted(5.0, 5.0, -5.0, -5.0))
        p.end()


class ColorPalette(QWidget):
    """메뉴 안에 넣는 색 견본 모음. 견본을 누르면 picked(색)을 보낸다."""
    picked = pyqtSignal(str)

    def __init__(self, presets, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._swatches = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 4, 10, 4)
        grid.setSpacing(2)
        for i, (name, color) in enumerate(presets):
            swatch = ColorSwatch(color, name)
            swatch.clicked.connect(lambda _checked=False, v=color: self.picked.emit(v))
            grid.addWidget(swatch, i // PALETTE_COLUMNS, i % PALETTE_COLUMNS)
            self._swatches[QColor(color).name()] = swatch

    def set_current(self, color: str) -> None:
        current = QColor(color).name()
        for key, swatch in self._swatches.items():
            swatch.set_selected(key == current)


class UsageCard(QWidget):
    refresh_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    providers_changed = pyqtSignal(bool, bool)   # (Claude 보기, GPT 보기)

    def __init__(self):
        super().__init__()
        self._settings = QSettings("AIUsageWidget", "Card")
        self._drag_offset: Optional[QPoint] = None
        self._next_refresh: Optional[datetime] = None
        self._weekly_on = False
        self._mini = False
        self._busy = False
        self._is_mock = USE_MOCK
        self._show = {"claude": True, "gpt": True}
        # 마지막으로 받은 값. 크기를 바꿔 카드 안쪽을 새로 만들 때와 최소화 막대를 채울 때 다시 쓴다.
        self._data = {key: {"usage": None, "error": None} for key in ("claude", "gpt")}
        self._status_view = ("불러오는 중…", False, "")   # (글자, 실패 여부, 툴팁). 색은 그릴 때 정한다
        self._scale_pct = 100
        self._grip_start: Optional[tuple] = None
        self._body: Optional[QWidget] = None

        self.setWindowTitle("AI 사용량")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool                       # 작업 표시줄에 아이콘을 만들지 않음
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)   # 둥근 모서리 바깥을 투명하게

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._grip = ResizeGrip(self)                  # 레이아웃 밖에서 오른쪽 아래 모서리에 붙여 둔다
        self._grip.pressed.connect(self._on_grip_pressed)
        self._grip.dragged.connect(self._on_grip_dragged)
        self._grip.released.connect(self._on_grip_released)

        self._build_menu()                             # _build_ui 가 메뉴 체크 상태를 맞추므로 먼저 만든다
        self._build_ui()
        self._restore_settings()
        self._start_worker()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save_settings)

    # ---- 구성 ---------------------------------------------------------------
    def _build_ui(self) -> None:
        """
        지금 배율로 카드 안쪽을 만든다. 크기를 바꿀 때마다 통째로 새로 만들고,
        들고 있던 상태(펼침, 보이는 서비스, 최소화, 마지막 값)를 그대로 다시 채운다.
        """
        self.claude = UsageSection("Claude", scoped_label=CLAUDE_SCOPED_WEEKLY.capitalize())
        self.gpt = UsageSection("GPT")

        rule = QFrame()
        rule.setFixedHeight(sp(1))
        rule.setStyleSheet(f"background: {C_EDGE};")

        self._mock_tag = make_label("더미", 10, C_MUTED)
        self._mock_tag.setStyleSheet(
            f"color: {C_MUTED}; border: 1px solid {C_EDGE}; border-radius: {sp(7)}px; "
            f"padding: {sp(1)}px {sp(6)}px;"
        )
        self._mock_tag.setVisible(self._is_mock)
        self._status = make_label("", 11, C_MUTED)

        self._more_btn = IconButton("more", "보기 설정")
        self._more_btn.clicked.connect(self._open_menu_from_button)
        self._weekly_btn = IconButton("chevron", "주간 한도 보기")
        self._weekly_btn.clicked.connect(lambda: self.set_weekly_visible(not self._weekly_shown()))
        self._refresh_btn = IconButton("refresh", "지금 새로고침")
        self._refresh_btn.clicked.connect(self.request_refresh)
        self._min_btn = IconButton("minimize", "최소화")
        self._min_btn.clicked.connect(lambda: self.set_minimized(True))
        self._close_btn = IconButton("close", "위젯 닫기")
        self._close_btn.clicked.connect(self.close)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(sp(6))
        foot.addWidget(self._mock_tag)
        foot.addWidget(self._status)
        foot.addStretch(1)
        foot.addWidget(self._more_btn)
        foot.addWidget(self._weekly_btn)
        foot.addWidget(self._refresh_btn)
        foot.addWidget(self._min_btn)
        foot.addWidget(self._close_btn)

        full = QWidget()
        col = QVBoxLayout(full)
        col.setContentsMargins(sp(14), sp(12), sp(14), sp(8))
        col.setSpacing(0)
        self._gap = QWidget()                    # 두 섹션 사이 여백: 한쪽을 숨기면 같이 숨긴다
        self._gap.setFixedHeight(sp(14))
        col.addWidget(self.claude)
        col.addWidget(self._gap)
        col.addWidget(self.gpt)
        col.addSpacing(sp(11))
        col.addWidget(rule)
        col.addSpacing(sp(6))
        col.addLayout(foot)

        # 최소화했을 때의 막대: 서비스별 5시간 사용률 + 펼치기 버튼
        self._mini_items = {"claude": MiniItem("Claude"), "gpt": MiniItem("GPT")}
        self._expand_btn = IconButton("expand", "펼치기")
        self._expand_btn.clicked.connect(lambda: self.set_minimized(False))
        mini = QWidget()
        bar = QHBoxLayout(mini)
        bar.setContentsMargins(sp(12), sp(6), sp(6), sp(6))
        bar.setSpacing(sp(12))
        bar.addWidget(self._mini_items["claude"])
        bar.addWidget(self._mini_items["gpt"])
        bar.addWidget(self._expand_btn)

        body = QWidget()
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(full)
        stack.addWidget(mini)
        self._full, self._mini_bar = full, mini

        old, self._body = self._body, body
        if old is not None:
            old.hide()
            self.layout().removeWidget(old)
            old.deleteLater()
        self.layout().addWidget(body)
        body.show()                              # 이미 떠 있는 창에 붙인 위젯은 직접 보여야 크기가 바로 잡힌다
        self._grip.setFixedSize(sp(14), sp(14))
        self._grip.raise_()

        self._set_status(*self._status_view)
        self._set_busy(self._busy)
        for key in self._data:
            self._render(key, animate=False)
        self.set_weekly_visible(self._weekly_on)
        self._sync_provider_ui()
        self._apply_minimized()

    def _build_menu(self) -> None:
        self._menu = QMenu(self)
        act_refresh = QAction("지금 새로고침", self)
        act_refresh.triggered.connect(self.request_refresh)
        self._menu.addAction(act_refresh)
        self._menu.addSeparator()

        self._act_show = {}
        for key, label in (("claude", "Claude 보기"), ("gpt", "GPT 보기")):
            act = QAction(label, self, checkable=True)
            act.setChecked(True)
            act.toggled.connect(lambda on, k=key: self.set_provider_visible(k, on))
            self._act_show[key] = act
            self._menu.addAction(act)

        self._act_weekly = QAction("주간 한도 보기", self, checkable=True)
        self._act_weekly.toggled.connect(self.set_weekly_visible)
        self._menu.addAction(self._act_weekly)

        self._act_mini = QAction("최소화", self, checkable=True)
        self._act_mini.toggled.connect(self.set_minimized)
        self._menu.addAction(self._act_mini)

        self._scale_menu = self._menu.addMenu("크기")
        self._scale_group = QActionGroup(self)
        self._scale_group.setExclusive(True)
        for pct in UI_SCALE_PRESETS:
            act = QAction(f"{pct}%", self, checkable=True)
            act.setData(pct)
            act.triggered.connect(lambda _checked, v=pct: self.set_scale(v))
            self._scale_group.addAction(act)
            self._scale_menu.addAction(act)
        self._scale_menu.addSeparator()
        act_hint = QAction("오른쪽 아래 모서리를 끌거나 Ctrl + 휠로도 바꿀 수 있음", self)
        act_hint.setEnabled(False)
        self._scale_menu.addAction(act_hint)

        self._color_menu = self._menu.addMenu("색상")
        self._palette = ColorPalette(THEME_PRESETS)
        self._palette.picked.connect(self._pick_theme_color)
        act_palette = QWidgetAction(self)
        act_palette.setDefaultWidget(self._palette)
        self._color_menu.addAction(act_palette)
        self._color_menu.addSeparator()
        act_custom = QAction("직접 고르기…", self)
        # 메뉴가 완전히 닫힌 뒤에 대화 상자를 띄운다
        act_custom.triggered.connect(lambda: QTimer.singleShot(0, self._choose_custom_color))
        self._color_menu.addAction(act_custom)
        act_default_color = QAction("기본 색으로", self)
        act_default_color.triggered.connect(lambda: self.set_theme_color(THEME_DEFAULT))
        self._color_menu.addAction(act_default_color)

        self._opacity_menu = self._menu.addMenu("투명도")
        self._opacity_group = QActionGroup(self)
        self._opacity_group.setExclusive(True)
        for pct in (100, 92, 85, 75, 65):
            act = QAction(f"{pct}%", self, checkable=True)
            act.setData(pct / 100.0)
            act.triggered.connect(lambda _checked, v=pct / 100.0: self._apply_opacity(v))
            self._opacity_group.addAction(act)
            self._opacity_menu.addAction(act)

        self._act_top = QAction("항상 위", self, checkable=True)
        self._act_top.setChecked(True)
        self._act_top.toggled.connect(self._apply_always_on_top)
        self._menu.addAction(self._act_top)

        self._menu.addSeparator()
        act_quit = QAction("종료", self)
        act_quit.triggered.connect(self.close)
        self._menu.addAction(act_quit)
        act_ver = QAction(f"버전 {APP_VERSION}", self)
        act_ver.setEnabled(False)
        self._menu.addAction(act_ver)

    def _start_worker(self) -> None:
        self._thread = QThread(self)
        self._worker = UsageWorker(REFRESH_INTERVAL_SEC,       # 부모 없이 생성해야 moveToThread 가능
                                   self._show["claude"], self._show["gpt"])
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self.refresh_requested.connect(self._worker.refresh)   # 스레드가 달라 자동으로 Queued 연결
        self.providers_changed.connect(self._worker.set_providers)
        self.stop_requested.connect(self._worker.stop)
        self._worker.fetch_started.connect(self._on_fetch_started)
        self._worker.snapshot_ready.connect(self._on_snapshot)
        self._thread.start()

    # ---- 주간 한도 펼치기 ------------------------------------------------------
    def _weekly_shown(self) -> bool:
        return self._weekly_on

    def set_weekly_visible(self, on: bool) -> None:
        self._weekly_on = on
        for section in (self.claude, self.gpt):
            section.weekly.setVisible(on)
            if section.weekly_scoped is not None:
                section.weekly_scoped.setVisible(on)
        self._weekly_btn.set_flipped(on)
        self._weekly_btn.setToolTip("주간 한도 접기" if on else "주간 한도 보기")
        if self._act_weekly.isChecked() != on:                 # 메뉴 체크 상태 동기화
            self._act_weekly.setChecked(on)
        self._fit_size()
        self._settings.setValue("weekly_shown", on)

    # ---- 서비스 보기 토글 ------------------------------------------------------
    def set_provider_visible(self, key: str, on: bool) -> None:
        other = "gpt" if key == "claude" else "claude"
        if not on and not self._show[other]:
            self._act_show[key].setChecked(True)   # 둘 다 숨길 수는 없다: 되돌린다
            return
        if self._show[key] == on:
            self._sync_provider_ui()
            return
        self._show[key] = on
        if on:
            self._data[key] = {"usage": None, "error": None}   # 예전 값이 잠깐이라도 보이지 않게
            self._render(key)
        self._sync_provider_ui()
        self._settings.setValue(f"show_{key}", on)
        self.providers_changed.emit(self._show["claude"], self._show["gpt"])

    def _sync_provider_ui(self) -> None:
        self.claude.setVisible(self._show["claude"])
        self.gpt.setVisible(self._show["gpt"])
        self._gap.setVisible(self._show["claude"] and self._show["gpt"])
        for key, item in self._mini_items.items():
            item.setVisible(self._show[key])
        for key, act in self._act_show.items():
            if act.isChecked() != self._show[key]:
                act.blockSignals(True)
                act.setChecked(self._show[key])
                act.blockSignals(False)
            # 남은 하나는 끌 수 없게 해서 카드가 텅 비는 일을 막는다
            other = "gpt" if key == "claude" else "claude"
            act.setEnabled(not (self._show[key] and not self._show[other]))
        self._fit_size()

    def _open_menu_from_button(self) -> None:
        self._menu.exec(self._more_btn.mapToGlobal(QPoint(0, self._more_btn.height() + 2)))

    def _fit_size(self) -> None:
        # 이전에 걸어 둔 고정 크기를 먼저 풀어야 접을 때 sizeHint가 줄어든다.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        # 안쪽 위젯의 레이아웃부터 다시 계산해야 방금 숨기거나 보인 줄이 바로 크기에 반영된다.
        # (findChildren 은 부모를 자식보다 먼저 돌려주므로, 뒤집으면 안쪽부터가 된다.)
        for child in reversed(self.findChildren(QWidget)):
            if child.layout() is not None:
                child.layout().activate()
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        hint = layout.sizeHint()
        self.setFixedSize(hint.width() if self._mini else sp(CARD_WIDTH), hint.height())
        self._grip.move(self.width() - self._grip.width(), self.height() - self._grip.height())

    # ---- 크기 조정 -------------------------------------------------------------
    def set_scale(self, pct: float, keep_corner: bool = True, save: bool = True) -> None:
        """카드 전체 배율(%)을 바꾼다. UI_SCALE_STEP 단위로 끊고, 달라졌을 때만 안쪽을 새로 만든다."""
        global _ui_scale
        pct = int(round(pct / UI_SCALE_STEP)) * UI_SCALE_STEP
        pct = max(UI_SCALE_MIN, min(UI_SCALE_MAX, pct))
        if pct != self._scale_pct:
            self._scale_pct = pct
            _ui_scale = pct / 100.0
            if keep_corner:
                self._keep_corner(self._build_ui)
            else:
                self._build_ui()
        self._scale_menu.setTitle(f"크기 ({pct}%)")
        for act in self._scale_group.actions():
            act.setChecked(act.data() == pct)
        if save:
            self._settings.setValue("scale_pct", pct)

    def wheelEvent(self, e) -> None:
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and dy:
            self.set_scale(self._scale_pct + (UI_SCALE_STEP if dy > 0 else -UI_SCALE_STEP))
            e.accept()
        else:
            super().wheelEvent(e)

    def _on_grip_pressed(self) -> None:
        self._grip_start = (self._scale_pct, self.width(), self.height())

    def _on_grip_dragged(self, delta: QPoint) -> None:
        if self._grip_start is None:
            return
        pct, w, h = self._grip_start
        # 끈 거리를 카드의 대각선 방향으로 투영한다. 가로세로 비율은 그대로 두고 모서리가 손을 따라오게.
        t = (delta.x() * w + delta.y() * h) / float(w * w + h * h)
        self.set_scale(pct * (1.0 + t), keep_corner=False, save=False)

    def _on_grip_released(self) -> None:
        self._grip_start = None
        self._settings.setValue("scale_pct", self._scale_pct)

    def _keep_corner(self, change) -> None:
        """
        change() 로 크기가 바뀌어도 화면 가장자리에 가까운 쪽 모서리는 제자리에 둔다.
        (기본 위치가 오른쪽 위라서, 그냥 두면 커질 때 화면 밖으로 밀려나고 접을 때 엉뚱한 곳으로 간다.)
        """
        before = self.frameGeometry()
        change()
        screen = self.screen()
        if screen is None or not self.isVisible():
            return
        area = screen.availableGeometry()
        x = before.left() if before.center().x() < area.center().x() else before.right() + 1 - self.width()
        y = before.top() if before.center().y() < area.center().y() else before.bottom() + 1 - self.height()
        self.move(x, y)

    # ---- 최소화 ---------------------------------------------------------------
    def set_minimized(self, on: bool) -> None:
        """5시간 사용률만 남긴 작은 막대로 접거나 다시 편다."""
        if on == self._mini:
            return
        self._mini = on
        self._keep_corner(self._apply_minimized)
        self._settings.setValue("minimized", on)

    def _apply_minimized(self) -> None:
        self._full.setVisible(not self._mini)
        self._mini_bar.setVisible(self._mini)
        self._grip.setVisible(not self._mini)
        if self._act_mini.isChecked() != self._mini:           # 메뉴 체크 상태 동기화
            self._act_mini.setChecked(self._mini)
        self._fit_size()

    # ---- 색상 -----------------------------------------------------------------
    def set_theme_color(self, color: str, save: bool = True) -> None:
        """카드 바탕색을 바꾼다. 글자, 선, 미터 빈 칸, 메뉴 색은 바탕색에 맞춰 따라 바뀐다."""
        qc = QColor(color)
        color = qc.name() if qc.isValid() else QColor(THEME_DEFAULT).name()
        if QColor(color) != QColor(C_BASE):
            set_theme(color)
            QApplication.instance().setStyleSheet(app_qss())
            self._build_ui()                      # 스타일시트에 색이 박혀 있어 새로 만든다
            self.update()
        self._palette.set_current(color)
        if save:
            self._settings.setValue("theme_color", color)

    def _pick_theme_color(self, color: str) -> None:
        self._color_menu.hide()                   # 견본은 메뉴 항목이 아니라서 메뉴를 직접 닫는다
        self._menu.hide()
        self.set_theme_color(color)

    def _choose_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(C_BASE), self, "카드 색 고르기")
        if color.isValid():
            self.set_theme_color(color.name())

    # ---- 데이터 반영 ----------------------------------------------------------
    def request_refresh(self) -> None:
        if not self._refresh_btn.isEnabled():     # 이미 가져오는 중
            return
        self._set_busy(True)
        self.refresh_requested.emit()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_btn.setEnabled(not busy)
        self._refresh_btn.set_spinning(busy)
        if busy:
            self._set_status("불러오는 중…", False, self._status_view[2])

    def _set_status(self, text: str, failed: bool = False, tooltip: str = "") -> None:
        self._status_view = (text, failed, tooltip)
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {C_CRIT if failed else C_MUTED}; background: transparent;")
        self._status.setToolTip(tooltip)

    def _render(self, key: str, animate: bool = True) -> None:
        """들고 있는 값을 그 서비스의 카드 칸과 최소화 막대 칸에 옮긴다."""
        section = self.claude if key == "claude" else self.gpt
        usage, error = self._data[key]["usage"], self._data[key]["error"]
        if usage is not None:
            section.set_data(usage, animate)
        else:
            section.set_waiting()
        if error is not None:
            section.set_error(error)
        self._mini_items[key].set_state(usage, error)

    @pyqtSlot()
    def _on_fetch_started(self) -> None:
        self._set_busy(True)

    @pyqtSlot(object)
    def _on_snapshot(self, snap: Snapshot) -> None:
        self._set_busy(False)
        self._is_mock = snap.is_mock
        self._mock_tag.setVisible(snap.is_mock)

        failed = False
        for key, usage, error in (("claude", snap.claude, snap.claude_error),
                                  ("gpt", snap.gpt, snap.gpt_error)):
            if not self._show[key]:
                continue                          # 숨긴 서비스는 건드리지 않는다
            if usage is not None:
                self._data[key] = {"usage": usage, "error": None}
            elif error is not None:
                self._data[key]["error"] = error  # 마지막으로 성공한 값은 그대로 두고 실패만 알린다
                failed = True
            else:
                # usage도 error도 없으면: 방금 켠 서비스라 이번 조회에 안 들어간 것. 다음 조회를 기다린다.
                continue
            self._render(key)
        self._next_refresh = snap.fetched_at + timedelta(seconds=REFRESH_INTERVAL_SEC)
        self._set_status(f"{snap.fetched_at:%H:%M:%S} " + ("일부 실패" if failed else "업데이트"),
                         failed, f"다음 자동 새로고침 {self._next_refresh:%H:%M:%S}")

    # ---- 창 속성 --------------------------------------------------------------
    def _apply_opacity(self, value: float) -> None:
        self.setWindowOpacity(value)
        self._settings.setValue("opacity", value)

    def _apply_always_on_top(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()                               # 플래그를 바꾸면 창이 숨겨지므로 다시 표시
        self._settings.setValue("always_on_top", on)

    def _restore_settings(self) -> None:
        opacity = float(self._settings.value("opacity", DEFAULT_OPACITY))
        opacity = max(0.3, min(1.0, opacity))
        self.setWindowOpacity(opacity)
        for act in self._opacity_group.actions():
            act.setChecked(abs(float(act.data()) - opacity) < 0.005)

        on_top = str(self._settings.value("always_on_top", "true")).lower() != "false"
        if not on_top:
            self._act_top.setChecked(False)       # toggled -> _apply_always_on_top

        try:
            scale = int(self._settings.value("scale_pct", 100))
        except (TypeError, ValueError):
            scale = 100
        self.set_scale(scale, keep_corner=False, save=False)   # 100%가 아니면 그 배율로 다시 만든다
        self.set_theme_color(str(self._settings.value("theme_color", THEME_DEFAULT)), save=False)

        weekly = str(self._settings.value("weekly_shown", "false")).lower() == "true"
        self.set_weekly_visible(weekly)           # 기본값은 접힌 상태

        for key in ("claude", "gpt"):
            self._show[key] = str(self._settings.value(f"show_{key}", "true")).lower() != "false"
        if not (self._show["claude"] or self._show["gpt"]):
            self._show = {"claude": True, "gpt": True}   # 설정 파일이 꼬였으면 둘 다 보이게
        self._sync_provider_ui()

        self._mini = str(self._settings.value("minimized", "false")).lower() == "true"
        self._apply_minimized()

        pos = self._settings.value("pos")
        if isinstance(pos, QPoint) and self._is_on_any_screen(pos):
            self.move(pos)
        else:                                     # 기본 위치: 주 모니터 오른쪽 위
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.right() - self.width() - 24, area.top() + 24)

    def _is_on_any_screen(self, pos: QPoint) -> bool:
        probe = QPoint(pos.x() + self.width() // 2, pos.y() + 20)
        return any(s.availableGeometry().contains(probe) for s in QGuiApplication.screens())

    def _save_settings(self) -> None:
        self._settings.setValue("pos", self.pos())
        self._settings.setValue("opacity", self.windowOpacity())
        self._settings.setValue("weekly_shown", self._weekly_shown())
        self._settings.setValue("show_claude", self._show["claude"])
        self._settings.setValue("show_gpt", self._show["gpt"])
        self._settings.setValue("scale_pct", self._scale_pct)
        self._settings.setValue("minimized", self._mini)
        self._settings.setValue("theme_color", QColor(C_BASE).name())

    # ---- 이벤트 ---------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(C_EDGE), 1.0))
        p.setBrush(QColor(C_BASE))
        radius = sp(CARD_RADIUS)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        p.end()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            # OS에 이동을 맡기면 Windows의 화면 가장자리 처리까지 자연스럽게 따라온다.
            if handle is not None and handle.startSystemMove():
                self._drag_offset = None
            else:
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()

    def mouseReleaseEvent(self, e) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if hasattr(self, "_save_timer"):
            self._save_timer.start()              # 끌기가 끝난 뒤 한 번만 저장

    def contextMenuEvent(self, e) -> None:
        self._menu.exec(e.globalPos())

    def closeEvent(self, e) -> None:
        self._save_settings()
        self.stop_requested.emit()
        if not self._thread.wait(3000):           # 가져오는 중이면 잠깐 기다렸다가 강제 종료
            self._thread.terminate()
            self._thread.wait()
        e.accept()
        QApplication.quit()                       # Tool 창은 닫혀도 앱이 자동 종료되지 않으므로 명시


def app_qss() -> str:
    """메뉴와 툴팁 스타일. 카드 색을 따라가도록 지금 색 토큰으로 만든다."""
    return f"""
QMenu {{
    background: {C_BASE}; color: {C_TEXT};
    border: 1px solid {C_EDGE}; border-radius: 8px; padding: 5px;
}}
QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {C_TRACK}; }}
QMenu::item:disabled {{ color: {C_MUTED}; }}
QMenu::separator {{ height: 1px; background: {C_EDGE}; margin: 4px 6px; }}
QToolTip {{
    background: {C_BASE}; color: {C_TEXT};
    border: 1px solid {C_EDGE}; padding: 4px 6px;
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# [7] 진입점
# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    if sys.platform.startswith("linux"):
        # Wayland 세션에서는 앱이 스스로 '항상 위'를 걸거나 창 위치를 지정할 수 없다.
        # X11(XWayland)로 띄우면 두 기능과 위치 복원이 모두 동작하므로 기본값을 xcb로 둔다.
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    app = QApplication(sys.argv)
    app.setApplicationName("AI Usage Widget")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(make_font(12))
    app.setStyleSheet(app_qss())

    card = UsageCard()
    card.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
