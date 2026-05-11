# crypto-trader 파라미터 튜닝 리뷰

**작성**: ARE 세션 2026-04-17
**대상**: crypto-trader의 pdh_pdl + VWM 전략 수익 개선
**참조 경로**: `/home/wdsr88/workspace/crypto-trader/`

## 현재 상태 (paper trading)

| 전략 | Trades | WR | 평균 수익 | 총 PnL | 문제 |
|---|---|---|---|---|---|
| pdh_pdl | 6 | 100% | +2.35%/trade | +10,208 KRW | trailing stop이 일찍 걸려 TP 8%를 못 먹음 |
| VWM | 12 | 50% | +1.35%/trade | +12,712 KRW | 손절 빈도 높음, 수익 거래는 +4~5% |

## 문제 1: pdh_pdl trailing stop이 수익 제한

**현재 파라미터** (`config/daemon.toml` pdh_pdl_btc_wallet):
```toml
trail_pct = 0.08183584818420675      # 8.2% trailing
activation_pct = 0.032930819383335294 # 3.3%에서 trailing 활성화
```

**실제 결과**: 대부분 +0.5~3.6%에서 profit_lock_trailing으로 청산. TP 15%에 도달한 거래 0건.

**원인**: activation_pct=3.3%이면 3.3% 오르자마자 trailing 시작. 이후 8.2% 되돌림에 청산. 실질 수익 = activation 직후 바로 trailing에 걸림.

**튜닝 방향**:
- `activation_pct` 올리기: 0.03 → **0.06~0.08** (6~8% 오른 후에야 trailing 시작)
- `trail_pct` 줄이기: 0.08 → **0.04~0.05** (더 타이트한 trailing으로 수익 보호)
- 또는 fixed TP/SL로 변경: TP=8%, SL=3%

**파일**: `src/crypto_trader/strategy/pdh_pdl_sweep_reclaim.py`
- `__init__` 파라미터: `trail_pct`, `activation_pct`
- `config/daemon.toml`의 `[wallets.strategy_overrides]`에서 오버라이드 가능

## 문제 2: VWM 손절 빈도

**현재 파라미터**: (daemon.toml vwm_btc_wallet 확인 필요)

**실제 결과**:
- 수익 거래: +4.3~5.0% (AVAX, LINK) — 좋음
- 손실 거래: -0.2~1.5% (DOT, DOGE, APT) — 작은 손실

**튜닝 방향**:
- SL을 약간 완화: 현재 SL이 너무 타이트하면 노이즈에 청산
- 진입 threshold 올리기: 더 확신 있는 신호만 진입

## 문제 3: 자본 배분

현재 각 wallet 1,000,000 KRW (paper). 실전 전환 시:
- pdh_pdl 6전 6승 → 자본 우선 배분 후보
- VWM 50% WR 하지만 수익 비대칭 (+4% vs -1%) → 유지

## ARE 백테스트 파라미터 참조

**pdh_pdl Candidate A** (ARE holdout SR=1.82):
```
signal: pdh_pdl_sweep_reclaim
  n=22, eps=0.00183, L=93, clv_min=0.687, rvol_min=2.076, hold_bars=3
exit: trailing_stop
  trail_pct=0.082, activation_pct=0.033, max_holding_bars=68
gates:
  btc_above_sma: period=251
  liquidity_min: min_24h_krw=7,844,751,368
```

**VWM** (ARE holdout SR=1.17):
```
signal: volume_weighted_momentum
  period=23, alpha=326
exit: fixed_tp_sl
  tp_pct=0.096, sl_pct=0.010, max_holding_bars=503
```

## 권장 작업 순서

1. `config/daemon.toml`에서 pdh_pdl `activation_pct` 0.03 → 0.06 변경
2. 48시간 paper 관찰
3. 수익 개선 확인 후 `trail_pct` 조정
4. VWM은 현재 파라미터 유지 (수익 비대칭 양호)
