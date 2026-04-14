# 2026-04-07 — 신규 전략 연구

## 목적

CLAUDE.md "과최적화 금지" 원칙 하에서, **paper 거래 데이터 기반**으로 신규 전략 가설을 도출하고 paper 월렛으로 검증한다. 백테스트 Sharpe 추격은 명시적으로 회피.

## 범위

- 1단계: 진단 — 실전 성과(1a), 백테 히스토리(1b), 전략 다양성(1c), 유니버스(1d)
- 2단계: 가설 생성 — 1단계 데이터 직접 인용 가능한 4개
- 3단계 (대기): 30거래 축적 후 검증

## 산출물

| 파일 | 내용 |
|---|---|
| [01_stage1a_live_performance.md](01_stage1a_live_performance.md) | paper-trades.jsonl 95건 분석. 월렛별 WR, exit 사유 분포. 이중 daemon 버그 증거 29건. |
| [02_stage1b_backtest_mining.md](02_stage1b_backtest_mining.md) | backtest_history.md 최근 30 사이클. Sharpe>3 미배포 22건. 과최적화 함정 입증. |
| [03_stage1c_strategy_diversity.md](03_stage1c_strategy_diversity.md) | 14 월렛 카테고리 매핑. mean_reversion 0%, vpin 편중 37.3%. 미사용 전략 15+ 식별. |
| [04_stage1d_universe_scan.md](04_stage1d_universe_scan.md) | market_scan cycle 164 결과. MANA/BAT/PUNDIX/ORBS/SAFE 등 월렛 외 후보 6종. |
| [05_stage2_hypotheses.md](05_stage2_hypotheses.md) | 가설 4개: ① 심볼 교체 ② vpin_eth 래칫 완화 ③ ONDO 출구 복제 ④ MR 신규 |

## 핵심 발견

1. **과최적화 함정 데이터로 입증**: 백테 Sharpe>3 22건 중 daemon 배포 0건
2. **vpin_doge 박스권 11회 반복 손실**: atr_sl_multiplier 0.3 너무 타이트 (→ 1.0으로 완화 적용)
3. **vpin_eth ratchet_stop 4연속 손실**: 백테 Sharpe +43이지만 실전 부적합
4. **vpin_ondo가 유일 흑자 (WR 71%)**: 표본 7건 운 가능성 있음
5. **mean_reversion 카테고리 자본 0%**: 박스권 대응 공백
6. **이중 daemon 버그**: 169 거래 중 29건 중복 — wallet_auto_updater.restart_daemon 수정 완료
7. **market_scan 발견 → 월렛 파이프라인 단절**: stealth-watchlist 결과 미사용 → fallback 로직 추가

## 적용된 행동

| 항목 | 적용 시각 | 파일 |
|---|---|---|
| vpin atr_sl_multiplier 0.3→1.0 (5월렛) | 2026-04-07 10:14 KST | config/daemon.toml |
| wallet_auto_updater.restart_daemon → systemctl 경유 | 2026-04-07 10:30 KST | scripts/wallet_auto_updater.py |
| market_scan_loop stealth-watchlist fallback | 2026-04-07 14:10 KST | scripts/market_scan_loop.py |
| 신규 paper 월렛 7개 (vpin × MANA/BAT/PUNDIX/ORBS, bb_mr × DOGE/XRP/AVAX) | 2026-04-07 14:17 KST | config/daemon.toml |
| systemd daemon 재시작 (21 월렛 로드 확인) | 2026-04-07 14:17 KST | systemctl |

## 다음 액션 (3단계)

1. **24~48h 후**: 신규 7월렛 첫 거래 발생 확인. 특히 vpin_mana/bat/pundix/orbs OHLCV 정상 fetch 여부.
2. **30거래 축적 후**: 가설별 실전 성과 vs 1a 기준선 비교
3. **paper 결과로 가설 우선순위 재평가** (Codex에 의뢰 가치 있는 시점)

## 알려진 미해결

- vpin_mana 등 신규 4 vpin 월렛이 첫 tick 로그에 안 보임 — OHLCV fetch 대기 또는 실패 가능성. 첫 1~2 사이클 후 재확인 필요.
- 기존 다수 심볼(APT/ADA/DOT/ATOM/ASTR/CELO/PEPE/THETA) OHLCV fetch 실패 — 별도 사안.
- market_scan 유니버스가 244 중 45개만 스캔 — 별도 개선 항목.

## 운영 메모

- Codex로 위임한 stage들 중 1c는 stuck → 직접 처리. 1단계 작은 범위로 쪼개도 Codex가 멈추는 사례 다수 발생.
- Stage 1a는 처음 daemon.log만 봤다가 exit_reason 못 찾음 → paper-trades.jsonl이 정답이었음. 이후 분석은 paper-trades.jsonl을 default 소스로.
