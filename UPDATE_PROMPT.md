AI 사용량 위젯(ai_usage_widget.py)을 새 버전으로 업데이트해줘. 명령은 네가 직접 실행해서 끝내줘.
설치본이 git 저장소(폴더에 .git 이 있음)면 1~4 대신 그 폴더에서 `git pull --ff-only` 로 받고 5단계부터 이어가.
아니면 새 파일은 내가 첨부했거나, 다운로드 폴더(~/다운로드 또는 ~/Downloads)에 받아 둔 상태야. 브라우저 때문에 이름이 "ai_usage_widget (1).py" 처럼 바뀌었을 수 있어.

1. 새 파일 고르기
   첨부한 파일이 있으면 그걸 써. 없으면 다운로드 폴더 바로 아래에서 이름이 ai_usage_widget 로 시작하는 .py 들을 모아 `grep -H 'APP_VERSION = '` 로 버전을 보고, 가장 높은 것을 골라. APP_VERSION 줄이 없는 파일은 옛 버전이니 후보에서 빼.

2. 지금 쓰고 있는 설치본 찾기
   아래를 차례로 확인해:
   - 실행 중인 위젯: `pgrep -af '^[^ ]*python[0-9.]* ([^ ]*/)?ai_usage_widget\.py'`
   - 바로가기: `~/.local/share/applications/ai-usage-widget.desktop` 의 Exec 줄
   - 흔한 위치: `~/gpt_claude_usage`, `~/다운로드/widget`, `~/ai-usage-widget`
   다운로드 폴더 바로 아래에 내려받은 새 파일 자체는 설치본이 아니야. 설치본이 여러 곳에서 나오면 어느 걸 바꿀지 나에게 물어봐.

3. 버전 비교
   설치본의 APP_VERSION 이 새 파일과 같거나 더 높으면 바꾸지 말고 그렇다고 알려줘. 설치본에 APP_VERSION 줄이 없으면 옛 버전으로 보고 진행해.

4. 교체
   설치본을 같은 폴더에 `ai_usage_widget.py.bak-<오늘 날짜>` 로 백업한 뒤, 새 파일을 `ai_usage_widget.py` 라는 이름으로 그 자리에 복사해. 같은 폴더의 `__pycache__` 는 지워.
   ~/.claude/settings.json, 브리지 파일, 바로가기, 그 밖의 파일은 건드리지 마.

5. 확인
   `python3 -m py_compile` 로 문법을 확인하고, `grep 'APP_VERSION = '` 로 새 버전이 들어갔는지 확인해.

6. 재시작
   `pkill -f '^[^ ]*python[0-9.]* ([^ ]*/)?ai_usage_widget\.py'` 로 기존 위젯을 끈 다음,
   (그냥 `pkill -f ai_usage_widget.py` 를 쓰면 이 명령을 실행하는 네 셸까지 같이 꺼지니 반드시 이 패턴을 써.)
   바로가기 파일이 있고 `gtk-launch` 가 있으면 `gtk-launch ai-usage-widget` 로,
   아니면 설치 폴더에서 `setsid bash run_widget.sh < /dev/null` 로 띄워.
   3초 뒤 `pgrep -af '^[^ ]*python[0-9.]* ([^ ]*/)?ai_usage_widget\.py'` 로 떠 있는지 확인하고, 안 떠 있으면
   로그(`~/.cache/ai-usage-widget/widget.log`)를 보여 주고 원인을 고쳐줘.

7. 보고
   짧게 알려줘: 설치 위치, 이전 버전 → 새 버전, 백업 파일 이름.
   새 파일 맨 위 설명의 "조작" 부분을 읽고, 이번에 새로 생긴 기능이 있으면 한두 줄로 알려줘.
   되돌리고 싶을 때 쓸 명령(백업을 원래 이름으로 복사 후 재시작)도 한 줄로 알려줘.

주의: 경로에 한글과 공백이 있으니 경로는 항상 따옴표로 감싸.
