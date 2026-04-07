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

### CI 화이트리스트에서 제외된 테스트 (회귀 의심 — 복구 필요)

스펙 `docs/superpowers/specs/2026-04-07-ci-setup-design.md` §5 회귀 은닉 방지 룰. CI 도입 시점(2026-04-07)에 master에서 이미 깨져 있던 테스트들. 화이트리스트에서 제외했지만 반드시 원인 파악 후 복구할 것. 복구 기한: **2026-04-21 (2주 내)**.

- [ ] `tests/test_wallet.py` — 6 failures (TestStrategyWalletRunOnce). 모멘텀 BUY 시그널이 HOLD로 떨어지는 등 매매 의사결정 회귀 의심. 우선순위 ⚠️ **HIGH** (코어 로직).
- [ ] `tests/test_macro_adapter.py` — 2 failures (TestShouldBlockEntry: extreme_fear_blocks, none_snapshot_does_not_block). 매크로 게이트 동작 변경 의심. 우선순위 **MEDIUM**.
- [ ] `tests/test_macro_bonus.py` — 4 failures. `ModuleNotFoundError: autonomous_lab_loop` (외부 lab 스크립트가 src/에 없음). 우선순위 **LOW** (테스트가 production이 아닌 lab 모듈을 import). 테스트를 lab repo로 옮기거나 모듈 위치 정리 필요.
