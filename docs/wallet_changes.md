# Wallet Change History

자동 업데이트 이력. market_scan_loop (심볼 교체) + strategy_research_loop (파라미터 갱신).

---
## 2026-04-16 — 부진 4지갑 비활성화 (paper 데이터 + Codex 리뷰 기반)

- **비활성화**: `stealth_3gate_wallet_1` — 75건 WR 16%, ₩-46,724. RS score 자기참조, 통계적 결론.
- **비활성화**: `vpin_bat_wallet` — 14건 WR 29% (ATR OFF 전 0%), ₩-19,437.
- **비활성화**: `vpin_mana_wallet` — 9건 WR 22%, ₩-34,015.
- **비활성화**: `vpin_orbs_wallet` — 13건 WR 23%, ₩-4,670.
- 활성 지갑: 20→16개
- 근거: `docs/strategy-review-2026-04-16.md`

## 2026-04-15 — ATR 스탑 전면 비활성화

- 글로벌 `atr_stop_multiplier` 3.0→0.0
- 개별: momentum_sol 1.5→0.0, volspike_btc 1.5→0.0, vpin_ondo 1.5→0.0
- 근거: 101건 WR 0%, ₩-149,908 (전체 손실 75%)
- 효과: ATR OFF 후 WR 23%→67%, 실현 PnL 양수 전환

---

## 2026-04-05 11:50 UTC — bb_squeeze 포트폴리오 리밸런스 (cycle 210)

- **추가**: `bb_squeeze_link_wallet` (paper, ₩500K, KRW-LINK)
  - 근거: c215 3-fold WF Sharpe +7.151, n=42, WR 58.0%, 슬리피지 robust
- **비활성화**: `bb_squeeze_sol_wallet` (KRW-SOL)
  - 근거: c215 개별 Sharpe +1.075 FAIL, F2/F3 마이너스

---

## 2026-04-03 03:13 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=69 alpha=2.752`
- 변경: `KRW-DOOD` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-03 03:13 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=69 alpha=2.752`
- 변경: `KRW-TREE` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 03:22 UTC — 파라미터 갱신: vpin_eth_wallet

- 트리거: `manual: 4h grid backtest Sharpe=+7.461`
- 변경: `take_profit_pct`: 0.04 → **0.06** | `stop_loss_pct`: 0.012 → **0.008** | `max_holding_bars`: 24 → **18** | `vpin_high_threshold`: 0.65 → **0.55** | `vpin_momentum_threshold`: 0.0003 → **0.0005**
- Sharpe: None → **7.461**
- ✅ daemon 재시작됨

---

## 2026-04-03 03:27 UTC — 파라미터 갱신: momentum_sol_wallet

- 트리거: `manual: 4h grid backtest Sharpe=+14.367`
- 변경: `adx_threshold`: 20.0 → **25.0** | `volume_filter_mult`: 1.5 → **2.0** | `take_profit_pct`: 0.08 → **0.12** | `stop_loss_pct`: 0.03 → **0.04**
- Sharpe: None → **14.367**
- ✅ daemon 재시작됨

---

## 2026-04-03 05:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=71 alpha=2.652`
- 변경: `KRW-TAIKO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-03 06:09 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=72 alpha=1.220`
- 변경: `KRW-ONT` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-03 06:09 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=72 alpha=1.220`
- 변경: `KRW-RAY` → `KRW-MLK`
- ✅ daemon 재시작됨

---

## 2026-04-03 07:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=74 alpha=1.192`
- 변경: `KRW-GAS` → `KRW-MLK`
- ✅ daemon 재시작됨

---

## 2026-04-03 07:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=74 alpha=1.192`
- 변경: `KRW-MLK` → `KRW-TRX`
- ✅ daemon 재시작됨

---

## 2026-04-03 09:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=76 alpha=2.926`
- 변경: `KRW-MLK` → `KRW-ALGO`
- ✅ daemon 재시작됨

---

## 2026-04-03 09:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=76 alpha=2.926`
- 변경: `KRW-TRX` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-03 10:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=77 alpha=2.623`
- 변경: `KRW-ALGO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-03 10:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=77 alpha=2.623`
- 변경: `KRW-JST` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 11:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=78 alpha=1.185`
- 변경: `KRW-RAY` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-03 11:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=78 alpha=1.185`
- 변경: `KRW-TAIKO` → `KRW-OPEN`
- ✅ daemon 재시작됨

---

## 2026-04-03 12:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=79 alpha=2.328`
- 변경: `KRW-MON` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-03 12:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=79 alpha=2.328`
- 변경: `KRW-OPEN` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 13:49 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=80 alpha=1.539`
- 변경: `KRW-RAY` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-03 13:49 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=80 alpha=1.539`
- 변경: `KRW-TAIKO` → `KRW-CRO`
- ✅ daemon 재시작됨

---

## 2026-04-03 14:49 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=81 alpha=2.937`
- 변경: `KRW-JST` → `KRW-ALGO`
- ✅ daemon 재시작됨

---

## 2026-04-03 14:49 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=81 alpha=2.937`
- 변경: `KRW-CRO` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-03 15:49 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=82 alpha=2.327`
- 변경: `KRW-ALGO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-03 15:49 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=82 alpha=2.327`
- 변경: `KRW-JST` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 16:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=83 alpha=2.380`
- 변경: `KRW-RAY` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-03 16:50 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=83 alpha=2.380`
- 변경: `KRW-TAIKO` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-03 19:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=86 alpha=1.891`
- 변경: `KRW-ONG` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 19:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=86 alpha=1.891`
- 변경: `KRW-TAO` → `KRW-TRX`
- ✅ daemon 재시작됨

---

## 2026-04-03 20:57 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=87 alpha=1.688`
- 변경: `KRW-TAIKO` → `KRW-QTUM`
- ✅ daemon 재시작됨

---

## 2026-04-03 20:57 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=87 alpha=1.688`
- 변경: `KRW-TRX` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-03 21:59 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=88 alpha=2.737`
- 변경: `KRW-QTUM` → `KRW-ALGO`
- ✅ daemon 재시작됨

---

## 2026-04-03 21:59 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=88 alpha=2.737`
- 변경: `KRW-G` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-03 23:01 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=89 alpha=1.882`
- 변경: `KRW-ALGO` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-03 23:01 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=89 alpha=1.882`
- 변경: `KRW-RAY` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-04 00:03 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=90 alpha=2.691`
- 변경: `KRW-TAIKO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 01:06 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=91 alpha=3.145`
- 변경: `KRW-RAY` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-04 01:06 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=91 alpha=3.145`
- 변경: `KRW-G` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-04 02:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=92 alpha=1.773`
- 변경: `None` → `KRW-QTUM`
- ✅ daemon 재시작됨

---

## 2026-04-04 02:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=92 alpha=1.773`
- 변경: `None` → `KRW-POWR`
- ✅ daemon 재시작됨

---

## 2026-04-04 03:13 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=93 alpha=2.713`
- 변경: `KRW-ZBT` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 04:17 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=94 alpha=3.394`
- 변경: `KRW-ONT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-04 04:17 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=94 alpha=3.394`
- 변경: `KRW-RAY` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-04 05:21 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=95 alpha=3.243`
- 변경: `KRW-ONG` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-04 05:21 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=95 alpha=3.243`
- 변경: `KRW-ZBT` → `KRW-YGG`
- ✅ daemon 재시작됨

---

## 2026-04-04 07:29 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=97 alpha=2.633`
- 변경: `KRW-ONT` → `KRW-ALGO`
- ✅ daemon 재시작됨

---

## 2026-04-04 07:29 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=97 alpha=2.633`
- 변경: `KRW-YGG` → `KRW-IOTA`
- ✅ daemon 재시작됨

---

## 2026-04-04 08:33 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=98 alpha=1.586`
- 변경: `KRW-ALGO` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-04 08:33 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=98 alpha=1.586`
- 변경: `KRW-IOTA` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-04 09:38 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=99 alpha=1.817`
- 변경: `KRW-ZBT` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 09:38 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=99 alpha=1.817`
- 변경: `KRW-TAO` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-04 10:44 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=100 alpha=2.572`
- 변경: `KRW-RAY` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-04 10:44 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=100 alpha=2.572`
- 변경: `KRW-JST` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 11:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=101 alpha=1.693`
- 변경: `KRW-ONT` → `KRW-POLYX`
- ✅ daemon 재시작됨

---

## 2026-04-04 11:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=101 alpha=1.693`
- 변경: `KRW-RAY` → `KRW-THETA`
- ✅ daemon 재시작됨

---

## 2026-04-04 12:53 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=102 alpha=2.835`
- 변경: `KRW-POLYX` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-04 12:53 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=102 alpha=2.835`
- 변경: `KRW-THETA` → `KRW-SOMI`
- ✅ daemon 재시작됨

---

## 2026-04-04 13:58 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=103 alpha=2.177`
- 변경: `KRW-ONT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-04 13:58 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=103 alpha=2.177`
- 변경: `KRW-SOMI` → `KRW-ALGO`
- ✅ daemon 재시작됨

---

## 2026-04-04 15:03 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=104 alpha=1.785`
- 변경: `KRW-ONG` → `KRW-THETA`
- ✅ daemon 재시작됨

---

## 2026-04-04 15:03 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=104 alpha=1.785`
- 변경: `KRW-ALGO` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-04 16:08 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=105 alpha=3.053`
- 변경: `KRW-THETA` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-04 16:08 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=105 alpha=3.053`
- 변경: `KRW-GAS` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 17:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=106 alpha=1.874`
- 변경: `KRW-ONG` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 17:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=106 alpha=1.874`
- 변경: `KRW-RAY` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-04 18:11 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=107 alpha=2.390`
- 변경: `KRW-RAY` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-04 18:11 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=107 alpha=2.390`
- 변경: `KRW-GAS` → `KRW-THETA`
- ✅ daemon 재시작됨

---

## 2026-04-04 19:11 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=108 alpha=1.413`
- 변경: `KRW-ONG` → `KRW-RENDER`
- ✅ daemon 재시작됨

---

## 2026-04-04 19:11 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=108 alpha=1.413`
- 변경: `KRW-THETA` → `KRW-VET`
- ✅ daemon 재시작됨

---

## 2026-04-04 20:11 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=109 alpha=2.829`
- 변경: `KRW-RENDER` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-04 20:11 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=109 alpha=2.829`
- 변경: `KRW-VET` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-04 21:12 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=110 alpha=1.093`
- 변경: `KRW-ONT` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-04 21:12 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=110 alpha=1.093`
- 변경: `KRW-RAY` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-04 22:13 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=111 alpha=1.518`
- 변경: `KRW-MASK` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-04 22:13 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=111 alpha=1.518`
- 변경: `KRW-G` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-05 00:15 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=113 alpha=1.353`
- 변경: `KRW-GAS` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-05 00:15 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=113 alpha=1.353`
- 변경: `KRW-SAFE` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-05 01:17 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=114 alpha=2.132`
- 변경: `KRW-TAO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 01:17 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=114 alpha=2.132`
- 변경: `KRW-ORBS` → `KRW-CPOOL`
- ✅ daemon 재시작됨

---

## 2026-04-05 02:19 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=115 alpha=2.554`
- 변경: `KRW-RAY` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-05 02:19 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=115 alpha=2.554`
- 변경: `KRW-CPOOL` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 06:29 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=119 alpha=2.004`
- 변경: `KRW-ONG` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 06:29 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=119 alpha=2.004`
- 변경: `KRW-RAY` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-05 07:32 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=120 alpha=1.810`
- 변경: `KRW-G` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-05 08:36 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=121 alpha=1.836`
- 변경: `KRW-RAY` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-05 08:36 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=121 alpha=1.836`
- 변경: `KRW-JST` → `KRW-CELO`
- ✅ daemon 재시작됨

---

## 2026-04-05 09:40 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=122 alpha=3.012`
- 변경: `KRW-GAS` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-05 09:40 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=122 alpha=3.012`
- 변경: `KRW-CELO` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 11:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=124 alpha=1.554`
- 변경: `KRW-ONT` → `KRW-CELO`
- ✅ daemon 재시작됨

---

## 2026-04-05 11:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=124 alpha=1.554`
- 변경: `KRW-RAY` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-05 12:52 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=125 alpha=2.511`
- 변경: `KRW-CELO` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-05 12:52 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=125 alpha=2.511`
- 변경: `KRW-TAO` → `KRW-KERNEL`
- ✅ daemon 재시작됨

---

## 2026-04-05 13:23 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=126 alpha=1.699`
- 변경: `KRW-MMT` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 13:23 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=126 alpha=1.699`
- 변경: `KRW-KERNEL` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-05 14:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=127 alpha=2.053`
- 변경: `KRW-RAY` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-05 14:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=127 alpha=2.053`
- 변경: `KRW-MASK` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-05 15:21 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=128 alpha=2.474`
- 변경: `KRW-ONT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-05 15:21 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=128 alpha=2.474`
- 변경: `KRW-G` → `KRW-ATH`
- ✅ daemon 재시작됨

---

## 2026-04-05 16:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=129 alpha=2.455`
- 변경: `KRW-ONG` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-05 16:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=129 alpha=2.455`
- 변경: `KRW-ATH` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-05 17:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=130 alpha=2.197`
- 변경: `KRW-ONT` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-05 17:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=130 alpha=2.197`
- 변경: `KRW-MASK` → `KRW-KERNEL`
- ✅ daemon 재시작됨

---

## 2026-04-05 18:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=131 alpha=1.396`
- 변경: `KRW-SAFE` → `KRW-TAIKO`
- ✅ daemon 재시작됨

---

## 2026-04-05 18:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=131 alpha=1.396`
- 변경: `KRW-KERNEL` → `KRW-G`
- ✅ daemon 재시작됨

---

## 2026-04-05 19:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=132 alpha=1.798`
- 변경: `KRW-TAIKO` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-05 19:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=132 alpha=1.798`
- 변경: `KRW-G` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-05 20:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=133 alpha=1.807`
- 변경: `KRW-MASK` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-05 20:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=133 alpha=1.807`
- 변경: `KRW-RAY` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-05 22:23 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=135 alpha=2.589`
- 변경: `KRW-ONT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-05 22:23 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=135 alpha=2.589`
- 변경: `KRW-SAFE` → `KRW-ATH`
- ✅ daemon 재시작됨

---

## 2026-04-05 23:24 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=136 alpha=2.407`
- 변경: `KRW-ONG` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-05 23:24 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=136 alpha=2.407`
- 변경: `KRW-ATH` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-06 00:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=137 alpha=2.628`
- 변경: `KRW-MMT` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-06 00:25 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=137 alpha=2.628`
- 변경: `KRW-GAS` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-06 01:27 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=138 alpha=1.654`
- 변경: `KRW-ONT` → `KRW-CELO`
- ✅ daemon 재시작됨

---

## 2026-04-06 01:27 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=138 alpha=1.654`
- 변경: `KRW-MASK` → `KRW-STRAX`
- ✅ daemon 재시작됨

---

## 2026-04-06 02:31 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=139 alpha=2.178`
- 변경: `KRW-CELO` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-06 02:31 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=139 alpha=2.178`
- 변경: `KRW-STRAX` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-06 03:33 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=140 alpha=1.913`
- 변경: `KRW-ONG` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-06 03:33 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=140 alpha=1.913`
- 변경: `KRW-SAFE` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-06 04:36 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=141 alpha=2.398`
- 변경: `KRW-RAY` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-06 04:36 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=141 alpha=2.398`
- 변경: `KRW-GAS` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-06 05:38 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=142 alpha=1.991`
- 변경: `KRW-ONT` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-06 05:38 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=142 alpha=1.991`
- 변경: `KRW-SAFE` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-06 06:41 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=143 alpha=2.095`
- 변경: `KRW-SAFE` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-06 06:41 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=143 alpha=2.095`
- 변경: `KRW-MASK` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-06 07:44 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=144 alpha=1.925`
- 변경: `KRW-RAY` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-06 09:53 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=146 alpha=1.790`
- 변경: `KRW-ONG` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-06 10:56 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=147 alpha=2.231`
- 변경: `KRW-MMT` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-06 10:56 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=147 alpha=2.231`
- 변경: `KRW-ZRX` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-06 13:05 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=149 alpha=3.153`
- 변경: `KRW-ONT` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-06 13:05 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=149 alpha=3.153`
- 변경: `KRW-ONG` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-06 14:11 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=150 alpha=1.841`
- 변경: `KRW-RED` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-06 14:11 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=150 alpha=1.841`
- 변경: `KRW-MMT` → `KRW-RAY`
- ✅ daemon 재시작됨

---

## 2026-04-06 15:15 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=151 alpha=1.502`
- 변경: `KRW-MMT` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-06 16:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=152 alpha=2.158`
- 변경: `KRW-ZRX` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-06 16:18 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=152 alpha=2.158`
- 변경: `KRW-RAY` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-06 17:18 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=153 alpha=1.606`
- 변경: `KRW-ZRX` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-06 18:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=154 alpha=2.867`
- 변경: `KRW-ONG` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-06 18:18 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=154 alpha=2.867`
- 변경: `KRW-TAO` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-06 19:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=155 alpha=1.439`
- 변경: `KRW-RED` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-06 19:18 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=155 alpha=1.439`
- 변경: `KRW-ZBT` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-06 20:19 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=156 alpha=1.572`
- 변경: `KRW-ZRX` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-06 20:19 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=156 alpha=1.572`
- 변경: `KRW-GAS` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-06 21:20 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=157 alpha=1.336`
- 변경: `KRW-MMT` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-06 21:20 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=157 alpha=1.336`
- 변경: `KRW-ZBT` → `KRW-ERA`
- ✅ daemon 재시작됨

---

## 2026-04-06 22:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=158 alpha=1.454`
- 변경: `KRW-SAFE` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-06 22:22 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=158 alpha=1.454`
- 변경: `KRW-ERA` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-06 23:24 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=159 alpha=3.058`
- 변경: `KRW-ZRX` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-06 23:24 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=159 alpha=3.058`
- 변경: `KRW-GAS` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-06 23:42 UTC — 파라미터 갱신: vpin_eth_wallet

- 트리거: `vpin_eth_grid Sharpe=+7.461 cycle=255`
- 변경: `max_holding_bars`: 36 → **18** | `take_profit_pct`: 0.07 → **0.06**
- Sharpe: None → **7.461**
- ✅ daemon 재시작됨

---

## 2026-04-07 00:46 UTC — 파라미터 갱신: momentum_sol_wallet

- 트리거: `momentum_sol_grid Sharpe=+14.367 cycle=256`
- 변경: `momentum_lookback`: 12 → **20**
- Sharpe: None → **14.367**
- ✅ daemon 재시작됨

---

## 2026-04-07 01:28 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=161 alpha=1.779`
- 변경: `KRW-RED` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-07 01:28 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=161 alpha=1.779`
- 변경: `KRW-ZBT` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-07 02:31 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=162 alpha=2.209`
- 변경: `KRW-MMT` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-07 02:31 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=162 alpha=2.209`
- 변경: `KRW-ZRX` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-07 03:33 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=163 alpha=1.361`
- 변경: `KRW-ONT` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-07 03:33 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=163 alpha=1.361`
- 변경: `KRW-RED` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-07 05:40 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=165 alpha=1.233`
- 변경: `KRW-XPL` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-07 07:47 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=167 alpha=1.416`
- 변경: `KRW-ZBT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-07 07:47 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=167 alpha=1.416`
- 변경: `KRW-MASK` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-07 09:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=169 alpha=1.617`
- 변경: `KRW-ONG` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-07 09:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=169 alpha=1.617`
- 변경: `KRW-SAFE` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-07 11:00 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=170 alpha=1.601`
- 변경: `KRW-ONT` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-07 11:00 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=170 alpha=1.601`
- 변경: `KRW-MASK` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=172 alpha=1.034`
- 변경: `KRW-ONG` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=172 alpha=1.034`
- 변경: `KRW-ONT` → `KRW-JST`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:16 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=173 src=alpha top=KRW-TAO@1.543`
- 변경: `KRW-GAS` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:17 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=173 src=alpha top=KRW-TAO@1.543`
- 변경: `KRW-JST` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:28 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=174 src=alpha top=KRW-RED@2.311`
- 변경: `KRW-TAO` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-07 13:28 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=174 src=alpha top=KRW-RED@2.311`
- 변경: `KRW-ORBS` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-07 14:33 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=175 src=alpha top=KRW-ZRX@1.215`
- 변경: `KRW-RED` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-07 14:33 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=175 src=alpha top=KRW-ZRX@1.215`
- 변경: `KRW-ONG` → `KRW-BSV`
- ✅ daemon 재시작됨

---

## 2026-04-07 16:40 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=177 src=alpha top=KRW-MMT@1.454`
- 변경: `KRW-ZRX` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-07 16:40 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=177 src=alpha top=KRW-MMT@1.454`
- 변경: `KRW-BSV` → `KRW-TRUST`
- ✅ daemon 재시작됨

---

## 2026-04-07 17:40 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=178 src=alpha top=KRW-MMT@1.571`
- 변경: `KRW-TRUST` → `KRW-HYPER`
- ✅ daemon 재시작됨

---

## 2026-04-07 18:43 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=179 src=alpha top=KRW-MMT@1.348`
- 변경: `KRW-HYPER` → `KRW-TRUST`
- ✅ daemon 재시작됨

---

## 2026-04-07 19:43 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=180 src=alpha top=KRW-RED@1.721`
- 변경: `KRW-MMT` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-07 19:43 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=180 src=alpha top=KRW-RED@1.721`
- 변경: `KRW-TRUST` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-07 20:43 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=181 src=alpha top=KRW-AKT@1.482`
- 변경: `KRW-RED` → `KRW-AKT`
- ✅ daemon 재시작됨

---

## 2026-04-07 20:43 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=181 src=alpha top=KRW-AKT@1.482`
- 변경: `KRW-ONT` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-07 21:45 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=182 src=alpha top=KRW-MASK@1.722`
- 변경: `KRW-AKT` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-07 21:45 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=182 src=alpha top=KRW-MASK@1.722`
- 변경: `KRW-MMT` → `KRW-ATH`
- ✅ daemon 재시작됨

---

## 2026-04-07 22:46 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=183 src=stealth top=KRW-MASK@1.722`
- 변경: `KRW-ATH` → `KRW-WAXP`
- ✅ daemon 재시작됨

---

## 2026-04-07 23:48 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=184 src=stealth top=KRW-MMT@1.134`
- 변경: `KRW-MASK` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-07 23:48 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=184 src=stealth top=KRW-MMT@1.134`
- 변경: `KRW-WAXP` → `KRW-TRUST`
- ✅ daemon 재시작됨

---

## 2026-04-08 00:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=185 src=alpha top=KRW-ORDER@1.200`
- 변경: `KRW-MMT` → `KRW-ORDER`
- ✅ daemon 재시작됨

---

## 2026-04-08 00:50 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=185 src=alpha top=KRW-ORDER@1.200`
- 변경: `KRW-TRUST` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-08 01:53 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=186 src=alpha top=KRW-CBK@1.553`
- 변경: `KRW-ORDER` → `KRW-CBK`
- ✅ daemon 재시작됨

---

## 2026-04-08 01:53 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=186 src=alpha top=KRW-CBK@1.553`
- 변경: `KRW-SOL` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-08 02:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=187 src=stealth top=KRW-BAT@0.721`
- 변경: `KRW-CBK` → `KRW-BAT`
- ✅ daemon 재시작됨

---

## 2026-04-08 02:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=187 src=stealth top=KRW-BAT@0.721`
- 변경: `KRW-TAO` → `KRW-ZRO`
- ✅ daemon 재시작됨

---

## 2026-04-08 04:00 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=188 src=alpha top=KRW-RED@1.673`
- 변경: `KRW-BAT` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-08 04:00 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=188 src=alpha top=KRW-RED@1.673`
- 변경: `KRW-ZRO` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-08 05:03 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=189 src=alpha top=KRW-RED@2.354`
- 변경: `KRW-SAFE` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-08 06:07 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=190 src=alpha top=KRW-XPL@1.749`
- 변경: `KRW-RED` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-08 06:07 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=190 src=alpha top=KRW-XPL@1.749`
- 변경: `KRW-MASK` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-08 07:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=191 src=alpha top=KRW-BSV@1.036`
- 변경: `KRW-XPL` → `KRW-BSV`
- ✅ daemon 재시작됨

---

## 2026-04-08 07:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=191 src=alpha top=KRW-BSV@1.036`
- 변경: `KRW-ONG` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-08 08:14 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=192 src=stealth top=KRW-LSK@0.589`
- 변경: `KRW-BSV` → `KRW-LSK`
- ✅ daemon 재시작됨

---

## 2026-04-08 08:14 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=192 src=stealth top=KRW-LSK@0.589`
- 변경: `KRW-ONT` → `KRW-AWE`
- ✅ daemon 재시작됨

---

## 2026-04-08 09:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=193 src=alpha top=KRW-TAO@1.608`
- 변경: `KRW-LSK` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-08 09:18 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=193 src=alpha top=KRW-TAO@1.608`
- 변경: `KRW-AWE` → `KRW-THETA`
- ✅ daemon 재시작됨

---

## 2026-04-08 10:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=194 src=alpha top=KRW-BSV@2.163`
- 변경: `KRW-TAO` → `KRW-BSV`
- ✅ daemon 재시작됨

---

## 2026-04-08 10:25 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=194 src=alpha top=KRW-BSV@2.163`
- 변경: `KRW-THETA` → `KRW-VET`
- ✅ daemon 재시작됨

---

## 2026-04-08 11:29 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=195 src=alpha top=KRW-RED@2.153`
- 변경: `KRW-BSV` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-08 11:29 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=195 src=alpha top=KRW-RED@2.153`
- 변경: `KRW-VET` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-08 12:35 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=196 src=alpha top=KRW-SAFE@1.571`
- 변경: `KRW-RED` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-08 12:35 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=196 src=alpha top=KRW-SAFE@1.571`
- 변경: `KRW-MASK` → `KRW-ZBT`
- ✅ daemon 재시작됨

---

## 2026-04-08 13:40 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=197 src=stealth top=KRW-FLOCK@0.754`
- 변경: `KRW-SAFE` → `KRW-FLOCK`
- ✅ daemon 재시작됨

---

## 2026-04-08 13:40 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=197 src=stealth top=KRW-FLOCK@0.754`
- 변경: `KRW-ZBT` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-08 14:45 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=198 src=stealth top=KRW-ORBS@0.915`
- 변경: `KRW-FLOCK` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-08 14:45 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=198 src=stealth top=KRW-ORBS@0.915`
- 변경: `KRW-ORBS` → `KRW-SIGN`
- ✅ daemon 재시작됨

---

## 2026-04-08 15:49 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=199 src=alpha top=KRW-RED@1.851`
- 변경: `KRW-ORBS` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-08 15:49 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=199 src=alpha top=KRW-RED@1.851`
- 변경: `KRW-SIGN` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-08 16:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=200 src=stealth top=KRW-MASK@0.982`
- 변경: `KRW-RED` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-08 16:50 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=200 src=stealth top=KRW-MASK@0.982`
- 변경: `KRW-XPL` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-08 17:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=201 src=alpha top=KRW-GAS@1.383`
- 변경: `KRW-MASK` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-08 17:50 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=201 src=alpha top=KRW-GAS@1.383`
- 변경: `KRW-ZRX` → `KRW-OPEN`
- ✅ daemon 재시작됨

---

## 2026-04-08 18:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=202 src=alpha top=KRW-MON@1.641`
- 변경: `KRW-GAS` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-08 18:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=202 src=alpha top=KRW-MON@1.641`
- 변경: `KRW-OPEN` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-08 19:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=203 src=alpha top=KRW-RED@2.116`
- 변경: `KRW-MON` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-08 19:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=203 src=alpha top=KRW-RED@2.116`
- 변경: `KRW-ORBS` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-08 20:56 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=204 src=stealth top=KRW-USD1@0.437`
- 변경: `KRW-RED` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-08 20:56 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=204 src=stealth top=KRW-USD1@0.437`
- 변경: `KRW-ONG` → `KRW-GMT`
- ✅ daemon 재시작됨

---

## 2026-04-08 21:58 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=205 src=alpha top=KRW-RED@1.782`
- 변경: `KRW-USD1` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-08 21:58 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=205 src=alpha top=KRW-RED@1.782`
- 변경: `KRW-GMT` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-08 23:01 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=206 src=stealth top=KRW-ORBS@0.661`
- 변경: `KRW-RED` → `KRW-ORBS`
- ✅ daemon 재시작됨

---

## 2026-04-08 23:01 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=206 src=stealth top=KRW-ORBS@0.661`
- 변경: `KRW-XPL` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 00:03 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=207 src=alpha top=KRW-ONT@1.725`
- 변경: `KRW-ORBS` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-09 00:03 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=207 src=alpha top=KRW-ONT@1.725`
- 변경: `KRW-MASK` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-09 01:05 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=208 src=stealth top=KRW-MASK@1.040`
- 변경: `KRW-ONT` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 01:05 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=208 src=stealth top=KRW-MASK@1.040`
- 변경: `KRW-RED` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-09 02:08 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=209 src=stealth top=KRW-USD1@0.478`
- 변경: `KRW-MASK` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-09 02:08 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=209 src=stealth top=KRW-USD1@0.478`
- 변경: `KRW-ZRX` → `KRW-BAT`
- ✅ daemon 재시작됨

---

## 2026-04-09 03:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=210 src=alpha top=KRW-KAITO@1.105`
- 변경: `KRW-USD1` → `KRW-KAITO`
- ✅ daemon 재시작됨

---

## 2026-04-09 03:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=210 src=alpha top=KRW-KAITO@1.105`
- 변경: `KRW-BAT` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-09 04:13 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=211 src=stealth top=KRW-ZRX@0.830`
- 변경: `KRW-KAITO` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-09 04:13 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=211 src=stealth top=KRW-ZRX@0.830`
- 변경: `KRW-MON` → `KRW-AWE`
- ✅ daemon 재시작됨

---

## 2026-04-09 05:16 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=212 src=alpha top=KRW-TAO@1.415`
- 변경: `KRW-ZRX` → `KRW-TAO`
- ✅ daemon 재시작됨

---

## 2026-04-09 05:16 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=212 src=alpha top=KRW-TAO@1.415`
- 변경: `KRW-AWE` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-09 06:20 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=213 src=alpha top=KRW-XPL@1.443`
- 변경: `KRW-TAO` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-09 06:20 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=213 src=alpha top=KRW-XPL@1.443`
- 변경: `KRW-ZRX` → `KRW-OPEN`
- ✅ daemon 재시작됨

---

## 2026-04-09 07:23 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=214 src=alpha top=KRW-SAFE@1.892`
- 변경: `KRW-XPL` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-09 07:23 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=214 src=alpha top=KRW-SAFE@1.892`
- 변경: `KRW-OPEN` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-09 08:27 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=215 src=alpha top=KRW-KAITO@1.128`
- 변경: `KRW-SAFE` → `KRW-KAITO`
- ✅ daemon 재시작됨

---

## 2026-04-09 08:27 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=215 src=alpha top=KRW-KAITO@1.128`
- 변경: `KRW-ONT` → `KRW-ZRX`
- ✅ daemon 재시작됨

---

## 2026-04-09 09:31 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=216 src=alpha top=KRW-MMT@1.302`
- 변경: `KRW-KAITO` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-09 09:31 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=216 src=alpha top=KRW-MMT@1.302`
- 변경: `KRW-ZRX` → `KRW-GAS`
- ✅ daemon 재시작됨

---

## 2026-04-09 10:38 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=217 src=alpha top=KRW-MON@1.404`
- 변경: `KRW-MMT` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-09 10:38 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=217 src=alpha top=KRW-MON@1.404`
- 변경: `KRW-GAS` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-09 11:46 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=218 src=stealth top=KRW-MMT@1.230`
- 변경: `KRW-MON` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-09 11:46 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=218 src=stealth top=KRW-MMT@1.230`
- 변경: `KRW-MMT` → `KRW-IN`
- ✅ daemon 재시작됨

---

## 2026-04-09 12:51 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=219 src=alpha top=KRW-ONT@1.877`
- 변경: `KRW-MMT` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-09 12:51 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=219 src=alpha top=KRW-ONT@1.877`
- 변경: `KRW-IN` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-09 13:55 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=220 src=alpha top=KRW-RED@1.351`
- 변경: `KRW-ONT` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-09 13:55 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=220 src=alpha top=KRW-RED@1.351`
- 변경: `KRW-MON` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 15:00 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=221 src=alpha top=KRW-MON@1.508`
- 변경: `KRW-RED` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-09 15:00 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=221 src=alpha top=KRW-MON@1.508`
- 변경: `KRW-MASK` → `KRW-XPL`
- ✅ daemon 재시작됨

---

## 2026-04-09 16:04 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=222 src=alpha top=KRW-MON@2.018`
- 변경: `KRW-XPL` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-09 17:04 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=223 src=stealth top=KRW-MASK@1.073`
- 변경: `KRW-MON` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 17:04 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=223 src=stealth top=KRW-MASK@1.073`
- 변경: `KRW-RED` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-09 18:04 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=224 src=alpha top=KRW-SAFE@2.017`
- 변경: `KRW-MASK` → `KRW-SAFE`
- ✅ daemon 재시작됨

---

## 2026-04-09 18:04 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=224 src=alpha top=KRW-SAFE@2.017`
- 변경: `KRW-USD1` → `KRW-THETA`
- ✅ daemon 재시작됨

---

## 2026-04-09 19:04 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=225 src=alpha top=KRW-SAFE@2.697`
- 변경: `KRW-THETA` → `KRW-MON`
- ✅ daemon 재시작됨

---

## 2026-04-09 20:04 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=226 src=alpha top=KRW-SAFE@2.240`
- 변경: `KRW-MON` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-09 21:06 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=227 src=alpha top=KRW-USD1@1.120`
- 변경: `KRW-SAFE` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-09 21:06 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=227 src=alpha top=KRW-USD1@1.120`
- 변경: `KRW-RED` → `KRW-ARB`
- ✅ daemon 재시작됨

---

## 2026-04-09 22:07 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=228 src=alpha top=KRW-ONG@1.566`
- 변경: `KRW-USD1` → `KRW-ONG`
- ✅ daemon 재시작됨

---

## 2026-04-09 22:07 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=228 src=alpha top=KRW-ONG@1.566`
- 변경: `KRW-ARB` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 23:09 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=229 src=stealth top=KRW-MASK@1.204`
- 변경: `KRW-ONG` → `KRW-MASK`
- ✅ daemon 재시작됨

---

## 2026-04-09 23:09 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=229 src=stealth top=KRW-MASK@1.204`
- 변경: `KRW-MASK` → `KRW-TT`
- ✅ daemon 재시작됨

---

## 2026-04-10 00:10 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=230 src=stealth top=KRW-USD1@0.744`
- 변경: `KRW-MASK` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-10 00:10 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=230 src=stealth top=KRW-USD1@0.744`
- 변경: `KRW-TT` → `KRW-XEC`
- ✅ daemon 재시작됨

---

## 2026-04-10 01:15 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=231 src=alpha top=KRW-MMT@1.332`
- 변경: `KRW-USD1` → `KRW-MMT`
- ✅ daemon 재시작됨

---

## 2026-04-10 01:15 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=231 src=alpha top=KRW-MMT@1.332`
- 변경: `KRW-XEC` → `KRW-USD1`
- ✅ daemon 재시작됨

---

## 2026-04-10 02:17 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `cycle=232 src=alpha top=KRW-ONT@1.171`
- 변경: `KRW-MMT` → `KRW-ONT`
- ✅ daemon 재시작됨

---

## 2026-04-10 02:17 UTC — 심볼 교체: accumulation_tree_wallet

- 트리거: `cycle=232 src=alpha top=KRW-ONT@1.171`
- 변경: `KRW-USD1` → `KRW-RED`
- ✅ daemon 재시작됨

---

## 2026-04-11 00:05 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-ONT` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-11 00:06 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-12 04:06 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-12 04:11 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 04:59 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 05:01 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 05:05 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 05:07 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 05:13 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-13 05:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:20 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:21 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:21 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:26 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:28 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:30 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:33 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-14 05:36 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-15 02:18 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-15 02:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-15 02:27 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-15 14:20 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-19 08:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-19 08:22 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-19 08:25 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-19 08:27 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-04-19 08:29 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-07 22:47 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-07 22:47 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-10 22:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-10 22:50 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-10 22:56 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---
## 2026-05-10 23:32 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---

## 2026-05-10 23:57 UTC — 심볼 교체: accumulation_dood_wallet

- 트리거: `manual_alpha_apply / cycle=233 / source=legacy`
- 변경: `KRW-OLD` → `KRW-NEW`
- ⚠️ daemon 재시작 안됨

---
