#!/usr/bin/env bash
# context_watch_hook.sh
# UserPromptSubmit hook: 컨텍스트 ~75% 도달 시 SESSION_HANDOFF.md 자동 생성

set -euo pipefail

PAYLOAD=$(cat)
SESSION_ID=$(echo "$PAYLOAD" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d.get('session_id',''))
" 2>/dev/null || echo "")

if [ -z "$SESSION_ID" ]; then exit 0; fi

# 프로젝트 디렉터리 해시 (pwd → - 치환)
PROJECT_KEY=$(pwd | sed 's|/|-|g')
SESSION_FILE="$HOME/.claude/projects/${PROJECT_KEY}/${SESSION_ID}.jsonl"

if [ ! -f "$SESSION_FILE" ]; then exit 0; fi

FILE_SIZE=$(wc -c < "$SESSION_FILE")
# JSONL 파일 크기 기준 (HUD 토큰 % 와 다름 — JSONL엔 tool result 등 오버헤드 포함)
# HUD ~80% ≈ JSONL ~1,100KB 경험치 기준
THRESHOLD=1100000
HANDOFF_FLAG="/tmp/handoff_done_${SESSION_ID}"

# 이미 이번 세션에서 생성했으면 스킵
if [ -f "$HANDOFF_FLAG" ]; then exit 0; fi

if [ "$FILE_SIZE" -lt "$THRESHOLD" ]; then exit 0; fi

# SESSION_HANDOFF.md 생성
PROJ_ROOT=$(pwd)
python3 "${PROJ_ROOT}/scripts/generate_handoff.py" 2>/dev/null

touch "$HANDOFF_FLAG"

# tmux 새 창에서 claude 실행 후 ㄱ 전송, 현재 창 자동 종료 (tmux 세션 있을 때만)
if command -v tmux &>/dev/null && tmux info &>/dev/null 2>&1; then
    TMUX_SESSION=$(tmux display-message -p '#S' 2>/dev/null || echo "")
    CURRENT_WINDOW=$(tmux display-message -p '#I' 2>/dev/null || echo "")
    if [ -n "$TMUX_SESSION" ]; then
        tmux new-window -n "claude-next" -c "$PROJ_ROOT" "claude --dangerously-skip-permissions" 2>/dev/null || true
        sleep 4
        tmux send-keys -t "${TMUX_SESSION}:claude-next" "ㄱ" Enter 2>/dev/null || true

        # 새 창 확인 후 현재 창 종료 (45초 후 백그라운드 — Claude 응답 완료 대기)
        if [ -n "$CURRENT_WINDOW" ]; then
            (
                sleep 15
                # 새 창 여전히 존재하면 현재 창 종료
                if tmux list-windows -t "$TMUX_SESSION" -F '#W' 2>/dev/null | grep -q "claude-next"; then
                    tmux kill-window -t "${TMUX_SESSION}:${CURRENT_WINDOW}" 2>/dev/null || true
                fi
            ) &
        fi
    fi
fi

# Claude + 사용자에게 알림
python3 -c "
import json
msg = {
    'systemMessage': '⚠️ 컨텍스트 ~80% 도달 — SESSION_HANDOFF.md 자동 생성 완료. 새 세션(claude-next 창) 시작됨. 이 창은 15초 후 자동 종료됩니다. 지금 마무리하세요.',
    'hookSpecificOutput': {
        'hookEventName': 'UserPromptSubmit',
        'additionalContext': 'SYSTEM ALERT: Context ~80% full. SESSION_HANDOFF.md generated. New session (claude-next window) opened with handoff. THIS WINDOW will auto-close in 15 seconds — wrap up now.'
    }
}
print(json.dumps(msg))
"
