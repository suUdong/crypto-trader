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
