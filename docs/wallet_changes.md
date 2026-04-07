# Wallet Change History

자동 업데이트 이력. market_scan_loop (심볼 교체) + strategy_research_loop (파라미터 갱신).

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

