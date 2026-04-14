# Stage 1c — 전략 다양성 갭 분석

생성: 2026-04-07 | 소스: `config/daemon.toml` (14 wallets) + `src/crypto_trader/strategy/` (27 files)

## 시그널 카테고리 분류 규칙
- **mean_reversion**: 되돌림(RSI 과매도·BB 바운스·mean_reversion 류)
- **breakout**: 돌파(BB squeeze 확장, 볼륨 spike, volatility_breakout, accumulation_breakout)
- **momentum**: 추세(momentum, ema_crossover, momentum_pullback)
- **volume_flow**: 주문흐름(vpin, obi, volume_spike)
- **multi_gate**: 복수 게이트(stealth_3gate, composite, truth_seeker)

## 표1: 활성 월렛 × 전략 × 카테고리

| wallet | strategy | symbols | 카테고리 | 자본(₩) |
|---|---|---|---|---:|
| accumulation_dood_wallet | accumulation_breakout | KRW-ONT | breakout + accumulation | 500,000 |
| accumulation_tree_wallet | accumulation_breakout | KRW-RED | breakout + accumulation | 500,000 |
| momentum_sol_wallet | momentum | KRW-SOL | momentum | 1,200,000 |
| volspike_btc_wallet | volume_spike | KRW-BTC | volume_flow + breakout | 1,000,000 |
| vpin_eth_wallet | vpin | KRW-ETH | volume_flow + momentum | 800,000 |
| vpin_sol_wallet | vpin | KRW-SOL | volume_flow + momentum | 500,000 |
| vpin_xrp_wallet | vpin | KRW-XRP | volume_flow + momentum | 500,000 |
| vpin_doge_wallet | vpin | KRW-DOGE | volume_flow + momentum | 500,000 |
| vpin_avax_wallet | vpin | KRW-AVAX | volume_flow + momentum | 500,000 |
| vpin_ondo_wallet | vpin | KRW-ONDO | volume_flow + momentum | 500,000 |
| stealth_3gate_wallet_1 | stealth_3gate | 8개 알트 | multi_gate + accumulation | 750,000 |
| bb_squeeze_eth_wallet | bb_squeeze_independent | KRW-ETH | breakout (BB expansion) | 2,300,000 |
| bb_squeeze_doge_wallet | bb_squeeze_independent | KRW-DOGE | breakout (BB expansion) | 500,000 |
| bb_squeeze_link_wallet | bb_squeeze_independent | KRW-LINK | breakout (BB expansion) | 500,000 |

**전 월렛 paper 모드.** live 월렛 0개.

## 표2: 카테고리별 자본 배분

| 카테고리 | 월렛 수 | 자본(₩) | 비중 |
|---|---:|---:|---:|
| volume_flow (vpin + volspike) | 7 | 4,300,000 | **37.3%** |
| breakout (bb_squeeze + accumulation + volspike*) | 6 | 5,300,000 | **46.0%** |
| momentum (순수) | 1 | 1,200,000 | 10.4% |
| multi_gate (stealth_3gate) | 1 | 750,000 | 6.5% |
| mean_reversion | **0** | **0** | **0%** |

(volspike_btc는 volume_flow와 breakout 양쪽에 포함되므로 합계 > 100%)

**총 자본: ₩11,550,000**

## 표3: src/strategy/ 에 존재하지만 daemon에서 미사용

| 파일 | 카테고리 | 비고 |
|---|---|---|
| `bollinger_mean_reversion.py` | mean_reversion | **순수 mean reversion** — 현재 월렛 0개 |
| `bollinger_rsi.py` | mean_reversion | BB + RSI 조합 |
| `mean_reversion.py` | mean_reversion | 일반 MR |
| `rsi_mr_bear.py` | mean_reversion (bear 전용) | 하락장 RSI MR |
| `momentum_pullback.py` | momentum | 모멘텀 풀백 진입 |
| `ema_crossover.py` | momentum | EMA 교차 |
| `volatility_breakout.py` | breakout | 변동성 돌파 (래리 윌리엄스류?) |
| `btc_regime_rotation.py` | multi_gate | BTC 레짐 기반 심볼 로테이션 |
| `obi.py` | volume_flow | Order Book Imbalance |
| `funding_rate.py` | (외생) | 선물 펀딩 레이트 (Upbit 현물에 적용 어려움 가능성) |
| `kimchi_premium.py` | (외생) | 김치 프리미엄 |
| `etf_flow_admission.py` | (외생) | ETF 유입 |
| `truth_seeker.py / v2 / v3` | multi_gate | 복합 필터 |
| `consensus.py` | meta | 다중 전략 합의 |
| `alpha_calibrator.py` | meta | 알파 스케일 보정 |

## 결론

- **최대 편중:** volume_flow(vpin) — 7개 월렛, 37.3% 자본. vpin 단일 시그널 공식이 실패하면 전 월렛 동시 손실 위험. 실제로 1a에서 vpin_doge/xrp/avax/sol이 전부 음수 상관 확인됨.
- **완전 누락 카테고리:** **mean_reversion**. 14 월렛 중 단 하나도 순수 MR 전략을 쓰지 않음. 박스권/횡보 장에서 수익원 부재 — vpin_doge가 박스권 노이즈에 당한 것도 역설적 증거.
- **재검토 가치 1순위:** `bollinger_mean_reversion.py`. 누락 카테고리를 정확히 메우고, 현재 DOGE·XRP 같은 저가 알트의 박스권 상황에 구조적으로 적합. (단 CLAUDE.md 원칙대로 paper 30건+ 검증 필수)
