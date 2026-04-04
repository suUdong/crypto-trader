# Regime-Aware Wallet Workflow Design

**Date:** 2026-04-04  
**Status:** Approved  
**Approach:** Option A — `active_regimes` gate in TOML

---

## Problem

현재 BTC BEAR 레짐 시 전 지갑/전 전략이 동일하게 차단된다. `btc_stealth_gate = true`를 통해
`artifacts/stealth-watchlist.json`의 `btc_bull_regime` 필드를 읽고, `adapter.should_block_entry()`에서
이진 차단(block/pass)이 발생한다. 결과적으로 BEAR 또는 SIDEWAYS 레짐에서 시스템 전체가 마비된다.

**목표:** 지갑별로 허용 레짐을 선언해 BEAR/SIDEWAYS에서도 일부 지갑이 거래 가능하도록 한다.
단, 레짐별 전략은 아직 미검증 상태이므로 아키텍처만 먼저 구성하고 전략은 추후 채워넣는다.

---

## Architecture

### Current Flow

```
multi_runtime.py:407  RegimeDetector.analyze(btc_candles)
                      → self._current_market_regime  (전역 문자열: bull/sideways/bear)

multi_runtime.py:512  wallet.run_once(symbol, candles)
                      ← 레짐 정보 미전달

wallet.py:555         btc_bull_regime = self._read_btc_regime()
                      → adapter.should_block_entry(btc_bull_regime=False)
                      → 전 전략 이진 차단
```

### New Flow

```
multi_runtime.py:407  RegimeDetector.analyze(btc_candles)
                      → self._current_market_regime

multi_runtime.py:NEW  for wallet in self._wallets:
                          wallet.set_market_regime(self._current_market_regime)

wallet.run_once()     if signal.action == BUY:
                          if regime not in self._active_regimes:
                              return HOLD (reason="regime_gate: {regime}")
```

---

## Components

### 1. `config.py` — WalletConfig

`active_regimes` 필드 추가:

```python
active_regimes: list[str] = field(default_factory=lambda: ["bull"])
```

`_STRATEGY_EXTRA_OVERRIDE_FIELDS`의 모든 전략 키에 `"active_regimes"` 등록.

### 2. `wallet.py` — StrategyWallet

```python
# __init__
self._active_regimes: list[str] = list(
    wallet_config.strategy_overrides.get("active_regimes", ["bull"])
)
self._current_market_regime: str = "sideways"  # 기본값 (set_market_regime 미호출 시)

# 새 setter
def set_market_regime(self, regime: str) -> None:
    self._current_market_regime = regime

# run_once() — signal 생성 후, should_block_entry() 이전에 삽입
if signal.action == SignalAction.BUY:
    if self._current_market_regime not in self._active_regimes:
        return PipelineResult(
            signal=Signal(
                action=SignalAction.HOLD,
                reason=f"regime_gate: {self._current_market_regime} not in {self._active_regimes}",
                confidence=0.0,
            ),
            ...
        )
```

**핵심 원칙:**
- 신규 진입(BUY)만 차단. 기존 포지션 청산(SELL)은 레짐 무관하게 항상 허용.
- 기본값 `["bull"]` → 기존 모든 지갑 동작 그대로 보존.

### 3. `multi_runtime.py` — `_run_tick()`

레짐 감지 직후(line ~408) 모든 지갑에 레짐 주입:

```python
# regime 감지 블록 이후
for wallet in self._wallets:
    wallet.set_market_regime(self._current_market_regime)
```

### 4. `config/daemon.toml` — 지갑별 active_regimes 선언

| 지갑 | active_regimes | btc_stealth_gate |
|---|---|---|
| accumulation_dood_wallet | `["bull"]` | 유지 (stealth SMA20 fine-grained) |
| accumulation_tree_wallet | `["bull"]` | 유지 |
| momentum_sol_wallet | `["bull"]` | 제거 가능 (active_regimes로 대체) |
| vpin_eth_wallet | `["bull", "sideways", "bear"]` | 해당 없음 |
| stealth_3gate_wallet (신규 시) | `["bull"]` | 유지 |

> **Note:** `btc_stealth_gate`는 stealth_3gate 전략의 BTC SMA20 검증용으로 별도 목적을 가지므로
> `active_regimes`와 공존한다. momentum_sol에서는 `btc_stealth_gate`가 레짐 필터 역할이었으므로
> `active_regimes = ["bull"]`로 대체 후 제거한다.

---

## Regime Source

- **소스:** `multi_runtime.py`의 `RegimeDetector.analyze()` (BTC 60분봉 기반)
- **값:** `"bull"` / `"sideways"` / `"bear"` (소문자 문자열)
- **기본값(미감지 시):** `"sideways"` (multi_runtime.py:90 기존 동작)
- **`btc_bull_regime` (stealth-watchlist.json):** `active_regimes` 게이트와 별개로 유지

---

## Testing

### Unit Tests — `tests/test_regime_gate.py` (신규)

| # | 케이스 | 기대 결과 |
|---|---|---|
| 1 | `active_regimes=["bull"]`, 레짐=bear, BUY 신호 | HOLD, reason="regime_gate:bear" |
| 2 | `active_regimes=["bull","sideways"]`, 레짐=sideways, BUY 신호 | regime gate 통과 |
| 3 | `active_regimes=["bull"]`, 레짐=bear, 포지션 보유 중 SELL 신호 | SELL 허용 |
| 4 | active_regimes 미지정 | 기본값 `["bull"]` |
| 5 | `set_market_regime` 미호출 | 기본값 "sideways" → bull-only 지갑 차단 |
| 6 | WalletConfig TOML 파싱 | `active_regimes=["bull","sideways"]` 정상 파싱 |

### Integration Test — `tests/test_multi_runtime_regime_injection.py` (신규)

| # | 케이스 | 기대 결과 |
|---|---|---|
| 7 | `_run_tick()` 호출 후 | 모든 wallet의 `_current_market_regime == runtime._current_market_regime` |

### 회귀 테스트

```bash
pytest tests/test_risk_hardening.py   # safety 상수 불변
pytest tests/                          # 전체 회귀
mypy src/                              # active_regimes: list[str] 타입 체크
ruff check src/ tests/                 # 린트
```

### 수동 검증 시나리오 (daemon.toml 반영 후)

| 시나리오 | 기대 동작 |
|---|---|
| BTC BEAR + momentum_sol `active_regimes=["bull"]` | regime_gate 차단 → HOLD |
| BTC SIDEWAYS + vpin_eth `active_regimes=["bull","sideways"]` | 진입 시도 허용 |
| 포지션 보유 중 레짐 BEAR 전환 | 청산 신호 그대로 실행 |

---

## Out of Scope

- 레짐별 전략 교체 (Option B) — 전략 미검증 상태, 추후 설계
- 레짐별 파라미터 페르소나 (Option C) — 추후 설계
- BEAR/SIDEWAYS 전용 전략 백테스트 — 사이클 146에서 BB mean reversion sideways 검증 예정

---

## Implementation Notes

- `run_once()` 시그니처 변경 없음 — `set_market_regime()` setter 패턴 사용 (macro_multiplier와 동일)
- 실행 순서: ① strategy.generate_signal() → ② active_regimes 체크 → ③ should_block_entry() (btc_stealth_gate 포함)
- `active_regimes`가 먼저 실행되는 이유: file I/O 없이 빠른 차단 가능, should_block_entry()는 그 이후
