# 2026-04-07 — 라이브 거래 인프라 설계

## 목적

paper 운영 안정화 후 라이브 전환을 위한 최적 인프라 구성안. 개인 트레이더 규모(월 ₩50k~150k 예산), Upbit 단일 거래소.

## 범위

- 현재 WSL2 + Python single daemon 병목 진단
- VPS/클라우드 옵션 비교 (한국/일본 리전 우선)
- 데이터베이스 도입 (현재 JSONL+JSON 파일 → SQLite/PostgreSQL)
- 모니터링·백업·HA 구성
- 단계적 마이그레이션 로드맵

## 산출물

| 파일 | 내용 | 상태 |
|---|---|---|
| [01_codex_full_research.md](01_codex_full_research.md) | Codex xhigh effort 인프라 보고서 (3000~5000단어) | 🟡 대기 (task-mno6pwjm-9wkgpu) |
| [02_claude_personal_recommendation.md](02_claude_personal_recommendation.md) | Claude 개인 규모 권장안 | 🟢 완료 |
| [03_db_design.md](03_db_design.md) | DB 도입 계획 (SQLite→Postgres 단계) | 🟢 완료 |

## 핵심 결정 사항 (잠정)

| 항목 | 결정 |
|---|---|
| **VPS** | AWS Lightsail Seoul 4GB ($20~40/mo) — Upbit과 같은 리전 latency 5~15ms |
| **OS** | 현행 systemd 유지, WSL2 → VPS 이전 |
| **데이터베이스** | Phase 1: SQLite + DuckDB / Phase 2: PostgreSQL self-host (같은 VPS) |
| **모니터링** | self-host Grafana + Loki + Telegram (이미 코드 존재) |
| **백업** | Cloudflare R2 (10GB 무료) |
| **언어 마이그레이션** | Python 유지. Rust는 60분봉 전략엔 ROI 없음 |
| **예상 월 비용** | ₩28~150k (단계별) |

## 핵심 통찰

- Upbit 60분봉 전략은 latency 5ms vs 50ms 차이가 수익에 거의 영향 없음
- 비용 더 써서 얻는 trading 이득보다 **장애 복구·모니터링·DB 일관성**이 ROI 큼
- 현재 가장 시급한 변경: WSL2 → Seoul VPS, DB 도입(이중 daemon 사고 같은 race condition 방지)

## 다음 액션

1. Codex 보고서 도착 후 두 시각(Claude/Codex) 종합
2. SQLite 스키마 설계 → PoC (paper-trades.jsonl 마이그레이션)
3. Lightsail Seoul 인스턴스 발주 (라이브 전환 결정 후)
