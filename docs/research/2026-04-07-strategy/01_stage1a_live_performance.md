# Stage 1a — 실전 성과 분석 (paper-trades.jsonl)

생성: 2026-04-07 | 데이터 소스: `artifacts/paper-trades.jsonl` (169 trades total, 95 trades since 2026-04-06)

> 주의: Codex 1차 시도는 `artifacts/daemon.log`만 봐서 exit_reason을 찾지 못했음.
> 실제 거래/청산 데이터는 `paper-trades.jsonl`에 있음 (향후 분석 기본 소스로 사용).

## 1. 월렛별 최근 거래 요약 (2026-04-06 이후, n=95)

| wallet | n | WR% | 평균손익% | exit 사유 분포 |
|---|---:|---:|---:|---|
| vpin_doge_wallet | 35 | 9% | **−0.733%** | atr_stop_loss:31, trailing_stop:3, breakeven_stop:1 |
| stealth_3gate_wallet_1 | 25 | 20% | −0.226% | atr_stop_loss:11, rs_score_deteriorated:5, breakeven_stop:5, atr_tp:4 |
| vpin_ondo_wallet | 7 | **71%** | **+0.589%** | rsi_overbought:5, atr_stop_loss:2 |
| vpin_sol_wallet | 7 | 57% | +0.127% | atr_stop_loss:3, rsi_overbought:2, trailing_stop:2 |
| vpin_xrp_wallet | 5 | 0% | −0.290% | rsi_overbought:2, atr_stop_loss:3 |
| accumulation_tree_wallet | 5 | 0% | **−1.632%** | breakeven_stop:3, atr_stop_loss:2 |
| accumulation_dood_wallet | 4 | 0% | **−3.922%** | atr_stop_loss:4 |
| vpin_eth_wallet | 4 | 0% | −0.248% | ratchet_stop:4 |
| volspike_btc_wallet | 2 | 0% | −0.907% | atr_stop_loss:2 |
| vpin_avax_wallet | 1 | 0% | −0.532% | atr_stop_loss:1 |

**진입 0건 월렛 (필터 과적합 의심):** momentum_sol, bb_squeeze_eth/doge/link (4개)

## 2. 핵심 발견

### A. vpin_doge — 단일 최대 출혈원
- 35회 중 **31회 atr_stop_loss** (88.6%). WR 9%.
- 방금(10:14 KST) `atr_sl_multiplier` 0.3→1.0 완화 적용했으나 기록은 전부 **수정 이전** 데이터.
- 효과 검증에는 수정 이후 30건+ 새 데이터 필요.

### B. accumulation 계열 손실 심각
- **accumulation_dood**: 4회 전부 atr_stop_loss, 평균 **−3.92%** (최악)
- **accumulation_tree**: 5회 전부 손실, breakeven_stop 3회 — 진입 직후 역행
- 두 월렛 모두 `atr_sl_multiplier` 재검토 필요

### C. vpin_eth — ratchet_stop 4연속
- 4거래 전부 `ratchet_stop` 청산. c216/c220 사이클에서 도입한 래칫이 **수익을 건지기 전에 먼저 작동**하는 패턴 의심.
- 진입 가격 대비 얼마나 상승했을 때 발동했는지 심층 분석 가치 있음.

### D. 유일한 흑자 — vpin_ondo
- 7거래 WR 71% +0.589%. exit는 rsi_overbought 5회(익절성) + atr_stop 2회.
- 파라미터/시그널 구조가 다른 vpin 월렛과 어떻게 다른지 확인 필요 (1b/1c에서).

### E. ⚠️ 이중 daemon 버그의 증거
- 169 거래 중 **29건 중복** — 동일 wallet/symbol/entry_time/pnl인데 session_id만 다름.
- 예: `20260406T224401Z-759458` (systemd) vs `20260406T234258Z-781861` (research loop spawn).
- 이미 10:15에 PID 812999 종료 + `wallet_auto_updater.restart_daemon()` 수정 완료로 재발 차단됨.
- **중복 제거 후 실제 거래 수 ≈ 140건으로 재산정 필요.**

## 3. 집계 메타

- 총 거래: 169
- 중복 거래: 29 (이중 daemon 부산물)
- 최근 24h 거래 (2026-04-06 이후): 95
- 평균 손익 × 거래수 합계: 대부분 음수 — 포트폴리오 -0.138% 상태와 일치
