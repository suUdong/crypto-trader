# Claude — 개인 트레이더 인프라 권장안 (₩50k~150k/mo)

## VPS 비교 결론

Upbit 서버가 한국 리전이라 **Seoul 리전이 객관적 1순위**, Tokyo는 차선.

| 순위 | 옵션 | 월 비용 | latency to Upbit | 평가 |
|---|---|---:|---|---|
| 🥇 | **AWS Lightsail Seoul 2vCPU/4GB** | ₩28k ($20) | 5~15ms | 같은 리전, 고정요금, 가장 균형 |
| 🥈 | AWS EC2 Seoul t3.medium Reserved | ₩45k ($32) | 5~15ms | CPU 안정성, 약정 필요 |
| 🥉 | 네이버/카카오 클라우드 KR | ₩35~50k | ~10ms | KRW 결제, 한국어 콘솔 |
| 4 | Vultr HF Tokyo 4vCPU/8GB | ₩67k ($48) | 30~50ms | 글로벌 편의 |
| 5 | Linode Tokyo Nanode 4GB | ₩34k ($24) | 35~55ms | 가성비 |
| - | Oracle Free ARM Tokyo | ₩0 | 40~60ms | 백업/sandbox만, 회수 위험 |

**탈락:** Hetzner(아시아 리전 없음), DigitalOcean(Tokyo 리전 없음), Contabo(IO 변동 큼).

## 권장 시나리오

### A. 안전 (₩28k/mo) — 최저비용 시작
- Lightsail Seoul 2vCPU/4GB ($20)
- Cloudflare R2 무료 백업
- self-host Grafana

### B. 균형 (₩56k/mo) — 권장
- Lightsail Seoul 4vCPU/8GB ($40)
- 같은 백업
- Better Stack 무료 모니터링

### C. 충분 (₩150k/mo) — sweet spot
- prod: Lightsail Seoul 8GB ₩56k
- dev/stage: Lightsail 2GB ₩14k
- Better Stack Pro ₩35k (logs+uptime+status)
- Cloudflare R2 ₩7k
- Tailscale Pro ₩8k
- GitHub Copilot ₩14k
- 도메인/예비 ₩10k
- **합계 ₩144k**

이 이상 쓰면 trading 자체엔 이득 거의 없음. **수확체감 가파름.**

## 비용 더 써도 안 사지는 것

- Upbit 60분봉 전략의 체결 latency 우위 (이미 5~15ms면 충분)
- 백테 Sharpe 향상 (인프라랑 무관)
- 알파 발견 (데이터 피드 추가는 별개 항목)

## 비용 더 써서 사지는 것

1. **장애 시 빠른 복구** — 모니터링/백업/알림 강화 (₩30~50k)
2. **개발 안정성** — dev 환경 분리 (₩14k)
3. **데이터 피드** — CryptoQuant/Glassnode (₩30~50k)
4. **dev 도구** — Copilot/Linear 등 (₩30k)

## 라이브 전환 로드맵

### Phase 0 (이번 주, ₩0)
- 백업 자동화 cron
- systemd template으로 daemon 분리 (전략군 5개)
- Upbit WebSocket PoC (vpin 1개)

### Phase 1 (다음 주, ₩28k/mo)
- Lightsail Seoul 발주
- Ansible/bash로 전체 환경 복제
- WSL2와 1주일 병행 → WSL2 종료

### Phase 2 (라이브 직전, ₩56~150k/mo)
- 자본 ₩100만 단위로 paper→live 점진 전환
- Prometheus + Grafana 설치
- 24h 장애 시뮬 테스트

### Phase 3 (3개월+, 필요시)
- Rust 핫패스 (py-spy 프로파일 후 결정)
- Bithumb 추가 (차익 거래)
- Oracle Free 콜드 스탠바이 DR

## 핵심 결정

**가장 시급한 1건:** WSL2 → Lightsail Seoul 이전. 이것만 해도 안정성·latency 동시 개선. 다른 건 점진.
