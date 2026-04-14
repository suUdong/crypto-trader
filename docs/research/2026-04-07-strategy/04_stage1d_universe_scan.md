# Stage 1d — 유니버스 스캔 (market_scan 결과 재사용)

생성: 2026-04-07 14:xx | 소스: `market_scan_loop` cycle 164 (13:36:55 KST)
데이터: `artifacts/{alpha,stealth,pre-bull}-watchlist.json`

## 배경

1a~1c는 월렛에 이미 할당된 15개 심볼만 대상으로 함. market_scan_loop는 별도 루프로 **45개 KRW 알트**를 매 사이클 스캔하지만 결과가 전략 연구 파이프라인으로 유입되지 않았음. 이 문서는 그 결과를 Stage 1 맥락으로 합류시킴.

## 현재 매크로 상태 (cycle 164)

| 지표 | 값 | 해석 |
|---|---|---|
| BTC 30-bar 수익률 | +4.06% | 상승 중 |
| BTC bull regime | **True** | 불장 판정 |
| BTC stealth gate | False | 스텔스 진입은 아님 (조용한 매집 아님) |
| Gate active | True | 스텔스 게이트 규칙 활성 |
| Pre-bull score (adj) | 0.822 | 임계 가까움 |
| 스캔 대상 코인 수 | 45 | (244 데이터 풀의 일부) |
| pct_pos_acc | 0.489 | 48.9% 양의 축적 |
| pct_weak_rs | 0.689 | 68.9% 약한 RS |

## 스캔 결과 — 월렛에 **없는** 후보

### A. Stealth Watchlist (5종)
| 심볼 | alpha | RS | acc | 월렛 보유? |
|---|---:|---:|---:|---|
| KRW-MANA | 0.625 | 0.996 | 1.310 | ❌ |
| KRW-BAT | 0.544 | 0.959 | 1.346 | ❌ |
| KRW-PUNDIX | 0.518 | 0.999 | 1.278 | ❌ |
| KRW-ORBS | 0.489 | 0.980 | 1.117 | ❌ |
| KRW-SKR | 0.270 | 0.946 | 1.320 | ❌ |

**전부 우리 14 월렛의 어느 심볼에도 없음.** RS(상대강도)가 0.95+로 상위권이고 acc(매집) 지표도 1.11~1.35로 양호. stealth_3gate 전략 구조상 "BTC 불장 + RS 상위 + 매집 중" 필터를 통과한 알트들.

### B. Alpha Watchlist Top
| 심볼 | alpha | 월렛 보유? |
|---|---:|---|
| KRW-SAFE | 1.8109 | ❌ |

cal-threshold 기반 상위 — 단일 심볼만 임계 통과. 약세장에선 보통 이 리스트가 비는 편.

## 스캔 유니버스의 한계

- market_scan_loop는 `total_coins_scanned=45`. 즉 전체 244 심볼 중 **~18%만** 심사. 나머지 200 심볼은 blind spot.
- `data/historical/daily/60m/2026/`에 244 심볼 데이터가 전부 있으므로, 원한다면 유니버스 확장 가능. 다만 현재 루프가 45개로 제한된 이유는 Upbit API rate limit + 전략 관련성 필터로 추정 (별도 확인 필요).

## 스캔 결과와 Stage 2 가설의 연결

| Stage 2 가설 | 유니버스 관점 재해석 |
|---|---|
| 가설 1 (DOGE/XRP 교체) | 교체 대상으로 MANA/BAT/PUNDIX 고려 가능 — stealth 스코어 우위 |
| 가설 4 (MR 신규) | 박스권 대응 MR 전략의 시범 심볼로 MANA/BAT (RS 상위 + 변동성 있음) |
| 가설 2/3 | ETH/SOL 기존 심볼 고정, 유니버스 무관 |

## 핵심 발견 (Stage 2 가설 보강용)

1. **기존 14 월렛 밖**에 현행 scan이 이미 필터링한 5+1 = 6종의 후보가 있음 (MANA, BAT, PUNDIX, ORBS, SKR, SAFE).
2. 이들은 **stealth_3gate 전략의 적합 대상**으로 이미 판정받음 — 즉 검증 로직이 인정한 심볼들.
3. 다만 alpha 1.81 vs 0.27 편차가 크므로, **MANA/BAT 2종만 Stage 2 가설 확장에 먼저 고려**할 가치.
4. market_scan이 **45/244만** 스캔 중이라는 사실 자체가 별도 개선 항목 — "유니버스 확장" 가설을 Stage 2에 추가 고려 가능.
5. 현재 BTC 불장 판정이라 Stage 2 가설 4 MR 신규는 **시점 불리** — 추세 시장에선 MR 기대값 낮음. 재검토 필요.
