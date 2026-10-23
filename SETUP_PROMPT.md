# 설치를 도와줄 AI에게 붙여넣을 프롬프트

아래 `---` 밑의 내용을 그대로 복사해서 ChatGPT나 Claude 같은 AI에게 붙여넣으면,
그 AI가 단계별로 설치를 안내해 줍니다. 다른 사람에게 보낼 때는 저장소 주소도 함께 알려 주세요.

---

나는 리눅스(Ubuntu 계열)를 쓰고 터미널에 익숙하지 않아.
https://github.com/jaemin0319/gpt_claude_usage 에 있는 위젯을 설치하고 싶어.
Claude와 GPT(Codex)의 5시간/주간 사용량을 바탕화면에 띄워 주는 위젯이래.
이걸 설치해서 바탕화면 아이콘으로 실행할 수 있게 도와줘.

지켜 줬으면 하는 것:
- 내가 할 일을 한 번에 하나씩, 복붙할 수 있는 명령 한 덩어리로 줘. 설명은 짧게.
- 내가 붙여넣은 터미널 출력을 보고 다음 단계를 정해 줘. 오류가 나면 원인부터 알려 줘.
- 내 대신 실행할 수는 없다는 걸 전제로, 내가 직접 판단할 일을 최소로 만들어 줘.

설치 순서는 이렇게 알고 있어 (자세한 건 저장소의 README.md):
1. 저장소를 받는다: `git clone https://github.com/jaemin0319/gpt_claude_usage.git ~/gpt_claude_usage`
   (git이 없으면 `sudo apt install -y git`)
2. 그 폴더에서 `bash setup.sh` 를 실행하면 PyQt6 설치, Claude 연동,
   바탕화면 아이콘 생성, 자동 시작 설정까지 차례로 물어본다.
3. 값이 보이려면 계정 로그인이 필요하다.
   - Claude: `claude` (Claude Code) 로 로그인. 한도 값은 claude.ai Pro/Max 구독 계정에만 내려온다.
   - GPT: `codex login` (Codex CLI) 으로 ChatGPT 계정 로그인.
   - 둘 중 하나만 돼 있어도 그쪽 값은 정상적으로 나온다.
   - 두 CLI의 설치 명령은 README의 "1. CLI 설치와 로그인"에 있다.
4. 값이 안 나오면 폴더에서 `bash check.sh` 를 실행하면 어느 경로가 막혔는지 알려 준다.

내가 물어볼 수 있는 것:
- `claude` 나 `codex` 가 설치돼 있지 않으면 설치 방법
- 한글 경로(`~/다운로드`)나 파일 이름 때문에 명령이 실패할 때 대처
- 위젯이 떴는데 숫자가 "불러오지 못함" 으로 나올 때 원인 찾기 (`cat ~/.cache/ai-usage-widget/widget.log`)
- 위젯이 안 보일 때 (다른 작업 공간에 있거나, "항상 위"가 꺼져 다른 창에 가려진 경우가 많다)

먼저 git이 설치돼 있는지 확인하는 명령부터 알려 줘.
