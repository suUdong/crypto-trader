# Daemon Monitoring Report

- **Generated**: 2026-03-29 09:46 KST
- **Session**: 20260329T002618Z-484059

---

## 1. Daemon Health Check

| Metric | Value |
|--------|-------|
| PID | 484059 |
| Status | **healthy** |
| Uptime | ~20 min (restarted at 09:26 KST) |
| Iterations | 20 |
| Tick Duration | 2.4s |
| Failure Streak | 0 |
| Supervisor | active |
| Auto-restart | enabled |
| Restart Count | 0 |
| Config | config/daemon.toml |

**Active Wallets (4):** momentum_sol, vpin_sol, volspike_btc, vpin_eth

**Symbols:** KRW-BTC, KRW-ETH, KRW-XRP, KRW-SOL

---

## 2. Paper Trade Analysis

### 2.1 All Trades (paper-trades.jsonl)

| # | Time (Entry) | Symbol | Wallet | Strategy | PnL (KRW) | PnL% | Exit Reason | Result |
|---|-------------|--------|--------|----------|-----------|------|-------------|--------|
| 1 | 03/27 07:00 | KRW-BTC | vbreak_btc | vol_breakout | -579 | -0.35% | close_below_prev_low | LOSS |
| 2 | 03/27 11:00 | KRW-ETH | momentum_eth | momentum | -3,376 | -1.35% | momentum_reversal | LOSS |
| 3 | 03/27 08:00 | KRW-BTC | kimchi_premium | kimchi | -1,715 | -1.96% | atr_stop_loss | LOSS |
| 4 | 03/27 09:00 | KRW-ETH | kimchi_premium | kimchi | -2,105 | -2.60% | atr_stop_loss | LOSS |
| 5 | 03/27 13:00 | KRW-XRP | vbreak_xrp | vol_breakout | -1,792 | -0.72% | close_below_prev_low | LOSS |
| 6 | 03/27 22:00 | KRW-ETH | **vpin_eth** | **vpin** | **+3,524** | **+1.60%** | rsi_overbought | **WIN** |
| 7 | 03/28 16:00 | KRW-ETH | vpin_eth | vpin | -204 | -0.35% | rsi_overbought | LOSS |
| 8 | 03/28 16:00 | KRW-ETH | vpin_eth | vpin | -914 | -1.56% | atr_stop_loss | LOSS |
| 9 | 03/28 21:00 | KRW-SOL | momentum_sol | momentum | -533 | -1.72% | atr_stop_loss | LOSS |

**Totals: 1W / 8L (11.1% WR), Net PnL: -7,694 KRW**

### 2.2 New Trades Since Last Check (03/27 22:00+)

전략 개선 커밋(`0fa3989`) 이후 거래 4건:

| # | Trade | PnL | Notes |
|---|-------|-----|-------|
| 6 | vpin_eth 03/27 22:00 | **+3,524** | 유일한 승리 -- vpin 전략이 작동 |
| 7 | vpin_eth 03/28 16:00 | -204 | 소액 손실, rsi_overbought 청산 |
| 8 | vpin_eth 03/28 16:00 | -914 | ATR 스톱로스, 연속 진입 문제 |
| 9 | momentum_sol 03/28 21:00 | -533 | SOL 모멘텀 실패, sideways 장 |

**개선 후 소결: 1W/3L, 순 PnL +1,873 KRW** -- 이전 0W/5L 대비 개선 조짐

### 2.3 Open Position

| Wallet | Symbol | Qty | Entry | Current | Unrealized PnL | PnL% |
|--------|--------|-----|-------|---------|----------------|------|
| vpin_sol | KRW-SOL | 1.796 | 127,095 | 124,700 | **-4,301 KRW** | **-1.89%** |

---

## 3. Portfolio Overview

| Metric | Value |
|--------|-------|
| Total Equity | 5,262,752 KRW |
| Initial Capital | 5,265,428 KRW |
| Portfolio Return | -0.051% |
| Realized P&L | +1,739 KRW |
| Unrealized P&L | -4,415 KRW |
| Net P&L | -2,676 KRW |
| Sharpe | -0.32 |
| Max Drawdown | 0.12% |
| Kill Switch | **not triggered** (2 consecutive losses) |

### Wallet Performance (Last 24h)

| Wallet | Strategy | Return% | Trades | W/L | Realized PnL |
|--------|----------|---------|--------|-----|-------------|
| vpin_eth | vpin | **+0.15%** | 3 | 1/2 | +2,272 |
| volspike_btc | volume_spike | 0.00% | 0 | 0/0 | 0 |
| momentum_sol | momentum | -0.09% | 1 | 0/1 | -533 |
| vpin_sol | vpin | -0.19% | 0 | 0/0 | 0 (unrealized -4,415) |

---

## 4. Error/Warning Analysis

### Macro Client Errors (165 total)

- **Period**: 01:08 ~ 05:01 KST (약 4시간)
- **Cause**: `ConnectionRefusedError` -- macro-intelligence HTTP server 연결 불가
- **Impact**: 매크로 레짐을 `unavailable`로 폴백, 주말이라 시장 레짐(`sideways`)만 사용
- **Severity**: LOW -- 주말에는 매크로 데이터 소스(FRED 등) 업데이트 없어 실질 영향 미미
- **Resolution**: 매크로 서버가 05:01 이후 자동 복구 또는 데몬 재시작으로 해소

### Other Issues

- 데몬 로그 파일(`artifacts/daemon.log`)이 09:26에 SIGTERM으로 종료된 이전 인스턴스 것
- 새 인스턴스(09:26~ 재시작)의 로그가 같은 파일에 기록되지 않는 것으로 보임 -- **로그 경로 확인 필요**

---

## 5. Trade Pattern Analysis

### Exit Reason Distribution

| Exit Reason | Count | Avg PnL% |
|-------------|-------|----------|
| atr_stop_loss | 4 | -1.96% |
| close_below_prev_low | 2 | -0.53% |
| rsi_overbought | 2 | +0.63% |
| momentum_reversal | 1 | -1.35% |

### Key Observations

1. **ATR 스톱로스가 최대 손실 원인** -- 4/9 손실 거래가 ATR SL 청산, 평균 -1.96%
2. **vpin_eth가 유일한 수익 전략** -- VPIN 전략이 ETH에서 유의미한 엣지 보유
3. **kimchi_premium, vbreak 전략 제거 효과** -- 0fa3989 커밋 이후 이들 전략 비활성화됨, 이전 5패 원인이었음
4. **주말 sideways 장세** -- 매크로 레짐 unavailable, market_regime=sideways, 월렛 멀티플라이어 감소(0.3~0.6x)
5. **SOL 포지션 주의** -- vpin_sol의 미실현 손실 -1.89%, ATR SL 근접 가능성

### PnL Distribution

```
+4000 |  *                          (vpin_eth WIN +3,524)
+2000 |
    0 |----------------------------------
-1000 |     *  *              *     (small losses)
-2000 |        *  *                 (medium losses)
-3000 |  *                          (momentum_eth -3,376)
```

---

## 6. Recommendations

1. **vpin_eth 전략 유지/강화** -- 유일한 수익 전략, confidence 0.76에서 승리
2. **momentum_sol 관찰** -- sideways 장에서 모멘텀 전략 효과 제한적, 멀티플라이어 0.3x 적절
3. **매크로 서버 모니터링** -- 주말 연결 실패 반복, 평일 전 서버 상태 확인 필요
4. **SOL 오픈 포지션 모니터링** -- ATR SL 도달 시 자동 청산 예정, 추가 개입 불필요
5. **로그 경로 점검** -- 재시작 후 daemon.log 갱신 중단 이슈 확인 필요
