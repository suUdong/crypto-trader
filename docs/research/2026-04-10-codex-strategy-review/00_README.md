# 2026-04-10 — Codex 전략 리뷰

## 목적

Codex가 현재 자동매매 포트폴리오를 코드, 설정, paper 거래 기록, 전략 실행 로그 기준으로 재평가한 결과를 남긴다.

이번 문서는 **전략 수정 제안서가 아니라 평가 문서**다. 이 시점에는 코드 변경을 하지 않았고, "지금 무엇이 실제 수익성 병목인지"를 정리하는 데 집중한다.

## 사용한 근거

- 설정: `config/daemon.toml`
- paper 거래: `artifacts/paper-trades.jsonl`
- 전략 실행 로그: `artifacts/strategy-runs.jsonl`
- 런타임 스냅샷: `artifacts/runtime-checkpoint.json`, `artifacts/health.json`
- 기존 리서치:
  - `docs/research/2026-04-07-strategy/`
  - `docs/research/2026-04-07-daily-review/`
- 전략 코드:
  - `src/crypto_trader/strategy/vpin.py`
  - `src/crypto_trader/strategy/bb_squeeze_independent.py`
  - `src/crypto_trader/strategy/bollinger_mean_reversion.py`
  - `src/crypto_trader/strategy/stealth_3gate.py`
  - `src/crypto_trader/strategy/experimental/accumulation_hunter.py`
  - `src/crypto_trader/risk/manager.py`
  - `src/crypto_trader/multi_runtime.py`

## 한 줄 결론

**현재 돌파구는 "새 지표 발명"보다 "이미 검증된 전략이 실제로 돌게 만들고, VPIN 계열의 출구 구조를 제대로 다루는 것"에 가깝다.**

---

## 1. 총평

### 1.1 VPIN은 "좋은 전략"이 아니라 "조건부로 살아남은 계열"

VPIN이 전체 최강이라고 보기 어렵다. 다만 현재 활성 전략군 중에서 **일부 심볼에서만 의미 있는 생존성**을 보이고 있다.

- `vpin_ondo_wallet`: 현재 최고 후보
- `vpin_sol_wallet`: 2순위 후보
- `vpin_eth_wallet`: 실전 괴리 심각
- `vpin_doge_wallet`: 구조적 실패
- `vpin_xrp_wallet`: 아직 열세

즉, 결론은 "`VPIN`이 좋다"가 아니라 **"`VPIN + 심볼 선택 + 출구 구조`가 맞을 때만 좋다"**이다.

### 1.2 현재 병목은 전략 로직만이 아니다

Codex 리뷰 결과, 수익성 병목은 두 층으로 나뉜다.

1. **전략/출구 구조 병목**
2. **런타임 실행 병목**

특히 실행 병목이 중요하다. 일부 전략은 성능이 나쁜 것이 아니라 **아예 실행되지 않고 있었다.**

---

## 2. 전략별 평가

| 전략/월렛 | 평가 | 근거 |
|---|---|---|
| `vpin_ondo_wallet` | `A-` | 현재 가장 안정적인 VPIN 후보. paper 누적 기준 상대 우위, OOS 서사도 가장 일관적 |
| `vpin_sol_wallet` | `B-` | 생존 가능성은 있으나 얇다. 손익이 entry보다 exit 구조에 더 민감 |
| `bb_mr_doge_wallet` | `C` | 표본이 거의 없지만, 최소한 논리 불일치보다는 희소 전략에 가깝다 |
| `momentum_sol_wallet` | `C-` | 극단적 손실은 아니나 개선 증거도 약하다. 최근 거래가 거의 없음 |
| `volspike_btc_wallet` | `C-` | 백테 서사는 있으나 현재 paper에서 우위 증거 약함 |
| `accumulation_dood_wallet` | `C-` | 최근 며칠 회복 흔적은 있으나 전체적으로 아직 실험 전략 |
| `stealth_3gate_wallet_1` | `D` | 현재 장세와 전략 정의가 충돌. 횡보/조정장용인데 최근 성과가 나쁨 |
| `vpin_eth_wallet` | `D` | 실전 청산 구조 미스매치가 반복됨 |
| `vpin_doge_wallet` | `F` | 박스권에서 반복 손절. 구조적 실패 사례 |
| `bb_squeeze_*` | `F` (runtime) | 전략 자체보다 런타임 데이터 부족으로 사실상 미작동 |

---

## 3. VPIN 상세 설명

### 3.1 이 프로젝트에서 VPIN이 하는 일

`src/crypto_trader/strategy/vpin.py` 기준으로 보면, VPIN 전략은 아래 질문에 답하는 구조다.

- 지금 흐름이 "독성 높은 추격 구간"인가?
- 아니면 "상대적으로 안전한 흐름에서 모멘텀이 붙는 구간"인가?

핵심 입력은 다음 5개다.

- `VPIN`
- `momentum`
- `RSI`
- `EMA trend`
- `ADX`

### 3.2 계산 방식

이 레포의 VPIN은 틱/호가 기반이 아니라 **캔들 기반 근사치**다.

최근 `bucket_count`개의 캔들에 대해:

1. `(close - open) / (high - low)`로 봉 내부 매수 우세/매도 우세를 근사
2. 각 봉 거래량을 buy/sell volume으로 분해
3. `|buy_vol - sell_vol|`의 합을 전체 거래량으로 나눔

해석:

- `VPIN 높음` = 독성 흐름, 진입 보류
- `VPIN 낮음` = 비교적 깨끗한 흐름, 모멘텀 진입 후보

### 3.3 진입 구조

전략의 기본 구조는 아래와 같다.

1. `VPIN >= high_threshold`면 진입 금지
2. EMA 추세가 꺾였으면 신뢰도 축소 또는 차단
3. ADX가 너무 낮으면 횡보 노이즈로 간주해 차단
4. `safe zone`: VPIN이 충분히 낮고 모멘텀/RSI가 맞으면 진입
5. `moderate zone`: VPIN이 아주 낮진 않아도 모멘텀이 더 강하면 진입

중요한 점은, 이 전략이 **"낮은 VPIN만으로 사는 전략"이 아니라 "낮은 VPIN + 추세 확인" 전략**이라는 것이다.

### 3.4 실제 손익은 어디서 갈리나

Codex 리뷰 기준 가장 중요한 발견은 이 부분이다.

**VPIN의 실제 승패는 전략 자체 exit보다 `RiskManager` exit에서 더 크게 갈린다.**

실전 청산 사유 상위는 아래였다.

- `atr_stop_loss`
- `trailing_stop`
- `ratchet_stop`
- `breakeven_stop`

반대로 전략 본체 exit인 `rsi_overbought`가 잘 나오는 케이스는 비교적 양호했다. `vpin_ondo_wallet`이 대표적이다.

즉, VPIN은 entry 품질 필터이고, **수익 곡선은 출구 구조가 결정한다.**

---

## 4. 전략별 핵심 해석

### 4.1 `vpin_ondo_wallet`

가장 좋은 근거를 가진 후보다.

- 기존 문서에서도 OOS walk-forward 통과 서사가 선명함
- `BTC>SMA20` + `BTC 30봉 양수` 게이트를 함께 씀
- 최근 paper 누적 기준도 상대 우위

해석:

- 단순 VPIN이 아니라 **강한 BTC 필터가 먹히는 VPIN 변형**이다
- 따라서 ONDO의 성과를 다른 심볼에 무작정 일반화하면 안 된다

### 4.2 `vpin_sol_wallet`

현재 2순위 후보다.

- paper에서 완전히 붕괴하지는 않음
- 다만 손실과 수익 모두 `RiskManager` 청산 구조에 크게 의존

해석:

- 전략 알파는 약하게 존재
- 그러나 지금 형태는 **entry edge보다 exit tuning 의존도가 높은 상태**

### 4.3 `vpin_eth_wallet`

실전 괴리의 대표 사례다.

- 과거 백테 서사는 강했음
- 실제 paper에서는 `ratchet_stop`이 반복적으로 먼저 발동

해석:

- ETH에서 VPIN 진입이 완전히 무의미하다고 단정할 단계는 아니지만
- 적어도 현재 출구 구조와는 잘 안 맞는다

### 4.4 `vpin_doge_wallet`

폐기 판단이 맞다.

- 최근 실전에서 반복적으로 `atr_stop_loss`
- 문서상으로도 박스권에서 진입 공식 자체가 잘못 작동한 정황이 강함

해석:

- 손절 거리 문제가 아니라 **signal-context mismatch**
- 즉, "더 느슨한 SL"로 해결될 문제가 아니었다

---

## 5. VPIN 외 전략 평가

### 5.1 `bb_squeeze_independent`

전략 문서와 백테 서사는 매우 좋다.

문제는 **지금 런타임에서 안 돈다.**

최근 `strategy-runs`를 보면:

- `bb_squeeze_eth_wallet`
- `bb_squeeze_doge_wallet`
- `bb_squeeze_link_wallet`

세 전략이 모두 `hold / insufficient_data`만 반복했다.

원인:

- 전략은 최소 `201`봉 이상 필요
- 현재 daemon은 `candle_count = 200`

즉, 이 전략군은 "성능이 나쁘다"가 아니라 **실행 조건을 못 맞춘 상태**다.

### 5.2 `bollinger_mr`

mean reversion 계열은 아직 증거가 적다.

다만 최근 로그를 보면 대부분:

- `no_band_touch`
- `adx_too_high`
- `no_squeeze_context`

위 이유로 hold 한다.

해석:

- 논리 자체가 과도하게 오염된 것은 아님
- 다만 현재 표본이 너무 적어 실전 판단을 내리기 이르다

### 5.3 `stealth_3gate`

현재 장세에서 약하다.

최근 run 로그 기준 상위 이유가:

- `btc_regime_bear`
- `btc_stealth_gate_fail`
- `alt_quality_gate_fail`

였다.

즉, 전략 정의상 "`조용한 매집` 환경"을 기다리는데, 지금은 그 환경이 아니다.

결론:

- 전략 자체가 틀렸다고 보기보다
- **지금 장세와의 미스매치**로 보는 편이 맞다

### 5.4 `accumulation_breakout`

가장 실험적이다.

- 프로토타입 성격이 강함
- RS gate, VPIN toxicity gate, CVD slope, 변동성 응축 점수를 합산
- 최근 며칠은 회복 흔적이 있으나 전체적으로 아직 불안정

결론:

- 연구 가치 자체는 있음
- 하지만 현재 주력 수익원 후보로 보기에는 이르다

---

## 6. Codex가 본 진짜 병목

### 6.1 병목 A — 실행되지 않는 전략이 있다

가장 중요한 사실.

- `bb_squeeze_*`는 현재 candle 부족으로 사실상 비활성 상태
- `vpin_mana/bat/pundix/orbs`는 `config.trading.symbols`에 없어서 런타임 순회 대상에서 빠져 있음

즉, 일부 신규 실험은 **"수익성이 없다"가 아니라 "평가조차 못 받고 있다."**

### 6.2 병목 B — VPIN은 entry보다 exit에 더 민감하다

실전 손실 사유를 보면 VPIN 본체 exit보다 `RiskManager` exit 비중이 높다.

따라서 앞으로의 개선 논점은:

- 신호를 더 복잡하게 만들기

보다

- 어떤 심볼에 어떤 exit 구조를 붙일지

가 더 중요하다.

### 6.3 병목 C — 포트폴리오가 현재 레짐과 약간 어긋나 있다

현재 health snapshot 기준 시장 레짐은 `sideways`다.

그런데 실전 자본과 실험 방향은 여전히:

- VPIN
- breakout
- stealth

비중이 높다.

mean reversion은 막 도입됐지만 아직 표본이 거의 없다.

즉, 포트폴리오는 **횡보 대응 전략 공백을 아직 완전히 못 메웠다.**

---

## 7. 방향성 제안

이번 리뷰 기준, 다음 우선순위가 가장 합리적이다.

### 우선순위 1 — 실행 병목 해소

이게 제일 중요하다.

- `bb_squeeze_*`가 실제 tick에서 평가되게 만들기
- `vpin_mana/bat/pundix/orbs`가 실제 runtime 순회 대상에 들어가게 만들기

이 단계 없이 전략 비교를 계속하면 왜곡된다.

### 우선순위 2 — VPIN은 `ONDO/SOL` 위주로 보되, "출구 구조"를 중심으로 본다

- `ONDO`는 기준선
- `SOL`은 추적 후보
- `ETH/DOGE/XRP`는 현재 구조에서는 후순위

핵심 질문:

- 어떤 exit 조합이 `rsi_overbought` 중심의 건강한 청산을 늘리고
- 어떤 exit 조합이 `atr_stop_loss`/`ratchet_stop` 과잉을 줄이는가

### 우선순위 3 — mean reversion은 폐기하지 말고 증거 축적

`bb_mr_*`는 아직 판단 유보가 맞다.

- 좋아 보인다고 결론 내리기엔 데이터가 적고
- 나쁘다고 폐기하기에도 실행 표본이 너무 적다

즉, 현 시점 평가는:

- **promising but unproven**

### 우선순위 4 — stealth / accumulation은 레짐 맞춤형 슬롯으로 다룬다

이 둘은 "항상 켜놓을 주력"보다:

- 특정 장세에서만 이득을 줄 수 있는 보조 전략

으로 보는 편이 낫다.

---

## 8. 최종 판단

Codex가 본 현재 전략 판도는 아래와 같다.

1. **가장 실전성이 있는 계열은 VPIN이다.**
2. 단, **모든 심볼에 일반화 가능한 VPIN은 아니다.**
3. 현재 진짜 돌파구는 **실행 병목 해소 + VPIN 출구 구조 정리**다.
4. `bb_squeeze`와 `bb_mr`는 지금 성능 판정 이전에 **실행 가능성/표본 부족 문제**를 먼저 해결해야 한다.

따라서 이번 시점의 운영 문장으로 정리하면:

> "Codex 전략 리뷰 결과, 현 시점 주력 후보는 VPIN 계열이 맞다. 다만 범용 우승 전략이라기보다 ONDO/SOL 중심의 조건부 우위 전략이며, 현재 수익성 돌파구는 신규 지표 추가보다 실행 병목 해소와 출구 구조 정리에 있다."

---

## 9. 문서 상태

- 상태: `평가 완료`
- 코드 변경: `없음`
- 다음 단계: 사용자가 원할 때 개선 항목을 구현/검증으로 전환
