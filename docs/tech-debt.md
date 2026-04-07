# Tech Debt Backlog

진행하지 않고 미뤄둔 작업들. 우선순위 낮음 → 손 빌 때 처리.

## 2026-04-07

### OHLCV transient None false-degraded
- **증상**: paper daemon `health.json` `status="degraded"`, `consecutive_failures` 증가, `last_error="No OHLCV data returned for KRW-ATOM"`. 동시에 같은 틱에서 `KRW-ATOM price=2532.00 signal=hold` 정상 출력 → 가격은 받지만 1차 OHLCV 호출만 None.
- **Root cause** (Codex 분석, 2026-04-07): `multi_runtime.py` 411-469에서 같은 틱 내 OHLCV를 두 번 호출. 1차 None을 recoverable로 기록만 하고 재시도가 성공해도 `_failure_streak`/`consecutive_failures`는 계속 증가 → 거짓 degraded.
- **권장 수정안** (적용 보류):
  1. 같은 틱 재시도 성공 시 직전 recoverable 에러를 "회복됨" 마킹하여 카운트에서 제외 (`multi_runtime.py` ~5줄)
  2. transient 회복 history를 health.json 또는 별도 artifact에 누적 → ATOM 같은 빈번 패턴 사후 분석
- **왜 미뤘나**: 표면 문제만, daemon은 정상 동작 (NRestarts=0, 메모리 정상). 실제 paper 거래에는 영향 없음. Codex 작업 시작했다가 중간 중단.
- **재개 트리거**: 24h soak에서 false degraded가 알림 노이즈가 되거나, 진짜 OHLCV 실패와 구분이 안 되는 사고가 발생하면.

### Lightsail 배포 후속 작업 (PR #1 머지 전후)
- Cloudflare Tunnel 재연결 (대시보드 노출)
- Lightsail 콘솔 SSH 22번 포트 본인 IP 화이트리스트
- Lightsail 자동 daily 스냅샷
- 24h soak (메모리 leak, restart 카운트)
- ATOM OHLCV root cause (위 항목과 통합)
- daemon 정본 결정 (현재 로컬 WSL PID 1013373이 paper 30거래 누적 중, Lightsail은 stop). 30거래 달성 후 Lightsail로 컷오버.
