# Strategy Profitability Review — 2026-04-16

**Reviewed by**: Codex (GPT-5.4) + Claude Opus 4.6
**Data basis**: ~260 closed paper trades, 20 wallets, 2026-03-27 ~ 2026-04-16
**Macro regime**: neutral/sideways, confidence 0.03

## 근본 원인 3가지

1. **스탑/타겟 비대칭**: VPIN SL 0.8% vs TP 7% (1:8.75). 횡보장에서 0.8%는 즉시 걸리고 7% TP는 도달 불가. ATR 스탑 비활성화 후에도 고정 0.8% 스탑이 동일 문제 유발.
2. **레짐 불일치**: 대부분 모멘텀/추세 전략이나 시장은 sideways. 노이즈 진입 → chopout.
3. **동일 전략 복제**: VPIN 10지갑 = 분산 아닌 집중. 하나 실패하면 전부 실패.

## 전략별 진단

### stealth_3gate — 73건 WR 14% | ₩-48,622

- RS score가 **자기 자신 대비** 순위 (다른 코인 대비 상대강도 아님) → Gate 3 무력
- `btc_stealth_acc_min = 1.0` 너무 낮아서 랜덤 볼륨 스파이크에 통과
- 전략 자체 exit(`rs_score_deteriorated`)이 느려서 대부분 risk manager stop_loss에 의존
- **73건이면 통계적으로 결론 가능 — 비활성화 권장**

### VPIN (10지갑) — 합산 ~150건 WR ~23% | 대부분 음수

- 저유동성 알트에서 24버킷 VPIN 측정이 노이즈
- `vpin_momentum_threshold` 0.0005는 사실상 필터 없음
- vpin_eth도 실제로는 disable됨 (12일 21건 WR 19% -₩4,772)
- **vpin_bat (0% WR), vpin_mana (22%), vpin_doge (12%), vpin_orbs (25%) 비활성화 권장**
- vpin_sol (35%), vpin_avax (32%) 관찰 유지 (데이터 축적)

### accumulation_dood — 15건 WR 47% | ₩-218

- 유일하게 **4시간봉** 사용 → 노이즈 필터링 효과
- TP 15%가 너무 높아서 수익 도달 전 다른 exit에 걸림
- 열린 포지션 ZBT +5.6%, ZRX +2.5%로 가장 양호
- **TP 15%→7% 조정 시 양수 전환 가능성**

### bb_mr (Bollinger MR) — 3건 | ₩+1,467

- 횡보장에 맞는 평균회귀 전략
- middle_band_reversion exit이 정상 작동
- **샘플 부족하나 유일한 양수. 유지 + 데이터 축적**

### pdh_pdl_btc — 1건 | ₩+565

- 전일 저가 sweep & reclaim 전략
- trailing stop exit 정상 작동
- **샘플 부족. 유지 + 데이터 축적**

### vwm_btc — 2건 | ₩-370

- volume weighted momentum
- **샘플 부족. 유지**

## ATR 스탑 비활성화 후 잔여 문제

ATR 스탑 꺼도 VPIN의 `stop_loss_pct = 0.008` (0.8%)는 60분봉 자연 변동성에서 치명적.
ATR 3.0x = ~2.7%였는데, 고정 0.8%는 **더 타이트함**.

## 권장 액션 (우선순위)

| # | 액션 | 유형 | 과최적화 원칙 |
|---|---|---|---|
| 1 | stealth_3gate 비활성화 | 끄기 | 부합 (73건 데이터 충분) |
| 2 | vpin_bat, vpin_mana, vpin_orbs, vpin_pundix 비활성화 | 끄기 | 부합 (WR 0~25%) |
| 3 | 잔여 지갑 stop_loss_pct ≥ 0.025 | 파라미터 | 경계 (데이터 기반이나 튜닝 영역) |
| 4 | accumulation_dood TP 15%→7% | 파라미터 | 경계 |
| 5 | bb_mr, pdh_pdl 유지 확대 | 유지 | 부합 |
| 6 | breakeven_watermark ≥ 0.03 | 파라미터 | 경계 |

## Exit 사유별 성적

| Exit | 건수 | WR | 총PnL | 평가 |
|---|---|---|---|---|
| trailing_stop | 18 | 94% | +₩12,417 | 최고 |
| atr_take_profit | 8 | 100% | +₩16,900 | 최고 |
| rsi_overbought | 22 | 73% | +₩16,695 | 양호 |
| profit_lock_trailing | 5 | 100% | +₩4,723 | 양호 |
| ratchet_stop | 6 | 50% | +₩3,578 | 보통 |
| middle_band_reversion | 2 | 100% | +₩1,469 | 양호 |
| breakeven_stop | 20 | 0% | -₩7,839 | 잠재 수익 차단 |
| stop_loss | 4 | 0% | -₩15,507 | 구조적 손실 |
| atr_stop_loss | 101 | 0% | -₩149,908 | **비활성화 완료** |
| rs_score_deteriorated | 25 | 4% | -₩26,447 | stealth 전용 |
| kill_switch_liquidation | 27 | 11% | -₩3,214 | 비상 |

## 미결 사항

- 비활성화 결정은 사용자 판단 대기
- 파라미터 변경(#3,4,6)은 과최적화 원칙과 충돌 가능 — 신중 필요
- BTC stealth gate가 11/20 지갑 차단 중 — regime 전환 시 자연 해소
