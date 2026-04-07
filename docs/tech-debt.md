# Tech Debt Backlog

진행하지 않고 미뤄둔 작업들. 우선순위 낮음 → 손 빌 때 처리.

## 2026-04-07

### Lightsail 배포 후속 작업 (PR #1 머지 전후)
- Cloudflare Tunnel 재연결 (대시보드 노출)
- Lightsail 콘솔 SSH 22번 포트 본인 IP 화이트리스트
- Lightsail 자동 daily 스냅샷
- 24h soak (메모리 leak, restart 카운트)
- ATOM OHLCV root cause (위 항목과 통합)
- daemon 정본 결정 (현재 로컬 WSL PID 1013373이 paper 30거래 누적 중, Lightsail은 stop). 30거래 달성 후 Lightsail로 컷오버.

### CI 화이트리스트 복구 완료 (2026-04-07 당일)

처음 1차 PR(#2)에서 제외했던 4개 항목 모두 복구 완료. 같은 날 후속 PR로 화이트리스트 재포함.
- ✅ `test_wallet.py` (6) — `_macro_snapshot` 주입 누락이 원인. `_benign_macro_snapshot` helper 추가, fail-closed 안전 게이트는 유지.
- ✅ `test_macro_adapter.py` (2) — fail-closed 의도 반영 (None → block), F&G threshold 명시적 전달로 수정.
- ✅ `test_macro_bonus.py` (4) — `compute_macro_bonus`가 `scripts/market_scan_loop.py`로 이동된 후 import 경로 미수정. import만 갱신.
- ✅ `test_macro_client.py::test_log_throttling_*` — `_last_failure_log_time = -1e9`로 결정적 throttle 진입.
