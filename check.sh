#!/usr/bin/env bash
# 두 서비스의 사용량이 실제로 조회되는지 점검한다.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
/usr/bin/python3 - << 'PY'
import sys
sys.path.insert(0, ".")
import ai_usage_widget as w

print("경로별 조회 결과\n")
for name, fn in (("Claude 계정 조회", w._claude_from_api),
                 ("Claude 브리지 파일", w._read_claude_state),
                 ("GPT 계정 조회", w._gpt_from_api),
                 ("GPT 세션 로그", w._gpt_from_logs)):
    try:
        u = fn()
        five = "–" if u.five_hour.used_pct is None else f"{u.five_hour.used_pct:.0f}%"
        week = "–" if u.seven_day.used_pct is None else f"{u.seven_day.used_pct:.0f}%"
        print(f"  [O] {name}: 5시간 {five} / 주간 {week}")
    except Exception as e:
        print(f"  [X] {name}: {e}")
print("\n한 서비스에서 하나라도 [O] 면 위젯에 값이 나옵니다.")
PY
