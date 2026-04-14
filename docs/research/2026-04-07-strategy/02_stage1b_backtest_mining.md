# Stage1b Backtest Mining (최근 30 사이클, 파일 말미 역순)

기준: `docs/backtest_history.md` 말미에서 `##` 헤더 기준 역순 최근 30개 엔트리(라인 2159~748).

### 표1: Sharpe > 3.0 달성했지만 daemon 미배포 후보
| cycle | 날짜 | 전략명 | 심볼 | 파라미터 요약 | Sharpe | WR | 거래수 | 결론/배포여부 |
|---|---|---|---|---|---:|---:|---:|---|
| momentum_sol_grid | 2026-04-07 00:45 UTC | momentum_sol 파라미터 그리드 | SOL | lookback/adx/vol/TP/SL 그리드 | +14.367 | 46.8% | 79 | 배포 문구 없음 (daemon.toml 현재값만 기재) |
| vpin_eth_grid | 2026-04-06 23:41 UTC | vpin_eth 파라미터 그리드 | ETH | vpin_high/mom/max_hold/TP/SL 그리드 | +7.461 | 27.6% | 446 | 배포 문구 없음 (daemon.toml 현재값만 기재) |
| c220 | 2026-04-05 12:37 UTC | mom_persist_sym_hold_regime_cd | 다종(기재 없음) | 모멘텀지속+심볼별hold+레짐cooldown | +51.425 | 75.0% | 4200 | 배포 언급 없음 |
| c219 | 2026-04-05 12:19 UTC | partial_tp_atr_regime_adaptive | 다종(기재 없음) | 2tier 분할익절+ATR 레짐 TP/SL 배수 | +158.891 | 100.0% | 86 | 배포 언급 없음 |
| c220 | 2026-04-05 12:15 UTC | vpin_ratchet_partial_tp | 다종(기재 없음) | 래칫+2-tier 분할익절 스태킹 | +20.707 | 42.5% | 64 | 배포 언급 없음 |
| (미기재) | 2026-04-05 12:01 UTC | score_ablation_adaptive_hold | 다종(기재 없음) | 7컴포넌트 ablation+동적 hold | +51.596 | 75.0% | 4200 | 배포 언급 없음 |
| c216 | 2026-04-05 11:57 UTC | ratchet_fair_slip_atr_adaptive | 다종(기재 없음) | slippage 공정비교+ATR adaptive+심볼모드 | +45.320 | 75.0% | 4200 | 배포 언급 없음 |
| c219 | 2026-04-05 12:05 UTC | partial_tp_atr_regime_adaptive | 다종(기재 없음) | 2-tier 분할익절+ATR 레짐 적응형 | +23.575 | 66.0% | 86 | 배포 언급 없음 |
| c215 | 2026-04-05 11:43 UTC | donchian_ema_slope_sym_sl | 다종(기재 없음) | EMA slope 확인+심볼별 SL 스케일 | +175.202 | 100.0% | 91 | 배포 언급 없음 |
| c214 | 2026-04-05 11:35 UTC | mom_accel_vpin_slope_entry | 다종(기재 없음) | 모멘텀 2차미분+VPIN slope 필터 | +39.471 | 66.7% | 4200 | 배포 언급 없음 |
| c213 | 2026-04-05 11:23 UTC | entry_quality_score_tpsl | 다종(기재 없음) | 7컴포넌트 점수 기반 TP/SL/Trail | +51.596 | 75.0% | 4200 | 배포 언급 없음 |
| c212 | 2026-04-05 11:16 UTC | ratchet_stop | 다종(기재 없음) | breakeven/profit lock 래칫 | +43.381 | 75.0% | 64 | 배포 언급 없음 |
| c207 | 2026-04-05 11:05 UTC | donchian_trailing_tpsl_hold_opt | 다종(기재 없음) | trailing/TP·SL/hold decay 재최적화 | +175.202 | 100.0% | 91 | 배포 언급 없음 |
| c209 | 2026-04-05 10:54 UTC | signal_strength_tpsl | 다종(기재 없음) | VPIN+MOM 강도 기반 TP/SL 스케일링 | +42.878 | 75.0% | 4200 | 배포 언급 없음 |
| c209 | 2026-04-05 10:45 UTC | squeeze_soft_gate_vol_surge | 다종(기재 없음) | BB squeeze soft gate + volume surge | +60.126 | 75.0% | 4200 | 배포 언급 없음 |
| c209 | 2026-04-05 10:36 UTC | macd_slope_gate_adaptive_hold | 다종(기재 없음) | MACD slope gate+적응 hold | +24.301 | 58.5% | 4200 | 배포 언급 없음 |
| c210 | 2026-04-05 19:40 UTC | signal_strength_tpsl | 다종(기재 없음) | Signal Strength Adaptive TP/SL | +17.655 | 43.8% | 64 | FAIL vs c179, 배포 언급 없음 |
| c207 | 2026-04-05 10:26 UTC | donchian_vol_regime_filter | 다종(기재 없음) | Donchian+ATR레짐+거래량+RSI | +175.202 | 100.0% | 88 | 배포 언급 없음 |
| c209 | 2026-04-05 19:30 UTC | squeeze_soft_gate_vol_surge | 다종(기재 없음) | BB Squeeze Soft Gate + Volume Surge | +37.473 | 59.9% | 13 | FAIL vs c199, 배포 언급 없음 |
| c207 | 2026-04-05 10:18 UTC | adaptive_exit_mom_reversal | 다종(기재 없음) | 모멘텀반전+시간감쇠+거래량반전 청산 | +42.878 | 75.0% | 4200 | 배포 언급 없음 |
| c206 | 2026-04-05 10:04 UTC | vpin_bb_squeeze_expansion | 다종(기재 없음) | VPIN chain + BB squeeze→expansion | +84.225 | 75.0% | 4200 | 배포 언급 없음 |
| c205 | 2026-04-05 10:00 UTC | macd_hist_accel_gradient | 다종(기재 없음) | MACD hist 가속도 + gradient TP | +24.460 | 57.6% | 4200 | 배포 언급 없음 |
| c207 | 2026-04-05 18:50 UTC | adaptive_exit_mom_reversal | 다종(기재 없음) | 모멘텀반전+시간감쇠 트레일 | +18.392 | 49.2% | 64 | c179 대비 악화, 배포 언급 없음 |

### 표2: 동일 전략 반복 최적화 흔적 (같은 전략이 3회+ 등장)
| 전략명 | 등장 cycle 번호 | 파라미터 변천 1줄 요약 | 마지막 Sharpe |
|---|---|---|---|
| 해당 없음 | 해당 없음 | 최근 30개 엔트리에서 동일 전략명 3회 이상 반복 확인되지 않음 | 해당 없음 |

### 표3: 특정 종목/레짐에서만 실패 기록 (재시도 가치)
| cycle | 전략명 | 실패 조건 | 성공 조건 (있다면) |
|---|---|---|---|
| c208 | vpin_60m_revalidation | "XRP에서 구조적 실패" | "ETH/SOL 단독은 가능성" |
| c205 | donchian_breakout | "F3(최근 4개월) 급격 감쇠 (+0.776)" | "avg OOS Sharpe +9.542 (>5.0)" |
| c209 | squeeze_soft_gate_vol_surge | "c199 대비 -13.952 악화" | "avg OOS Sharpe +37.473 PASS (>5.0)" |
| c210 | signal_strength_tpsl | "c179 대비 -25.223 악화" | "avg OOS Sharpe +17.655 PASS (>5.0)" |

즉시 재검토 가치 후보 top 3
- `c207_donchian_vol_regime_filter`: Sharpe +175.202, WR 100.0%, trades 88 (배포 언급 없음).
- `c206_vpin_bb_squeeze_expansion`: Sharpe +84.225, WR 75.0%, trades 4200 (배포 언급 없음).
- `c219_partial_tp_atr_regime_adaptive`(2026-04-05 12:19): Sharpe +158.891, WR 100.0%, trades 86 (배포 언급 없음).
