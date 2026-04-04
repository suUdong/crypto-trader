# Regime-Aware Wallet Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 각 지갑이 `active_regimes`를 TOML에 선언해 BEAR/SIDEWAYS에서도 거래 가능하도록 런타임 레짐 게이트를 추가한다.

**Architecture:** `multi_runtime.py`가 틱마다 `wallet.set_market_regime(regime)`을 호출하고, `StrategyWallet.run_once()`은 신규 진입(BUY) 전에 `active_regimes` 체크를 먼저 실행한다. 기본값 `["bull"]`이므로 기존 지갑 동작은 그대로 보존된다.

**Tech Stack:** Python 3.12, dataclasses, pytest, mypy (strict), ruff

---

## File Map

| 파일 | 변경 유형 | 책임 |
|---|---|---|
| `src/crypto_trader/config.py` | Modify (line 956-957) | `_COMMON_WALLET_OVERRIDE_FIELDS` 추가 → `active_regimes` 검증 통과 |
| `src/crypto_trader/wallet.py` | Modify (~line 322-340, 525-580) | `_active_regimes`, `_current_market_regime` 필드 + `set_market_regime()` + run_once 게이트 |
| `src/crypto_trader/multi_runtime.py` | Modify (~line 440, ~line 1002) | `_propagate_market_regime()` + `_run_tick()` 호출 |
| `config/daemon.toml` | Modify (각 [[wallets]] 섹션) | `active_regimes` 선언, momentum_sol/vpin_eth btc_stealth_gate 정리 |
| `tests/test_regime_gate.py` | Create | 7개 유닛/통합 테스트 케이스 |

---

## Task 1: config.py — active_regimes 검증 허용

**Files:**
- Modify: `src/crypto_trader/config.py:956-957`
- Test: `tests/test_regime_gate.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_regime_gate.py` 파일 생성:

```python
"""Tests for regime-aware wallet active_regimes gate."""
from __future__ import annotations

from crypto_trader.config import _strategy_override_names


def test_active_regimes_allowed_for_all_strategies() -> None:
    """active_regimes must pass config validation for every strategy type."""
    strategy_types = [
        "momentum",
        "vpin",
        "accumulation_breakout",
        "volume_spike",
        "stealth_3gate",
        "mean_reversion",
        "funding_rate",
        "consensus",
        "kimchi_premium",
        "truth_seeker",
        "truth_seeker_v2",
        "etf_flow_admission",
    ]
    for strategy in strategy_types:
        allowed = _strategy_override_names(strategy)
        assert "active_regimes" in allowed, (
            f"active_regimes not allowed for strategy '{strategy}'"
        )
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader
pytest tests/test_regime_gate.py::test_active_regimes_allowed_for_all_strategies -v
```

Expected: `FAILED` — `AssertionError: active_regimes not allowed for strategy 'momentum'`

- [ ] **Step 3: config.py 수정 — `_COMMON_WALLET_OVERRIDE_FIELDS` 추가**

`src/crypto_trader/config.py` line 956-957 (현재):
```python
def _strategy_override_names(strategy_name: str) -> set[str]:
    return _STRATEGY_FIELD_NAMES | _STRATEGY_EXTRA_OVERRIDE_FIELDS.get(strategy_name, set())
```

변경 후 (`_STRATEGY_EXTRA_OVERRIDE_FIELDS` 블록 바로 뒤, `_strategy_override_names` 정의 앞에 상수 추가):
```python
# Fields allowed in strategy_overrides for ALL wallet strategies (not strategy-specific)
_COMMON_WALLET_OVERRIDE_FIELDS: frozenset[str] = frozenset({"active_regimes"})


def _strategy_override_names(strategy_name: str) -> set[str]:
    return (
        _STRATEGY_FIELD_NAMES
        | _STRATEGY_EXTRA_OVERRIDE_FIELDS.get(strategy_name, set())
        | _COMMON_WALLET_OVERRIDE_FIELDS
    )
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_regime_gate.py::test_active_regimes_allowed_for_all_strategies -v
```

Expected: `PASSED`

- [ ] **Step 5: 기존 테스트 회귀 확인**

```bash
pytest tests/ -x -q
```

Expected: 모든 기존 테스트 통과

- [ ] **Step 6: 커밋**

```bash
git add src/crypto_trader/config.py tests/test_regime_gate.py
git commit -m "feat: allow active_regimes in all wallet strategy_overrides"
```

---

## Task 2: wallet.py — set_market_regime setter + active_regimes 게이트

**Files:**
- Modify: `src/crypto_trader/wallet.py` (~line 322-340 `__init__`, ~line 525-580 `run_once`)
- Test: `tests/test_regime_gate.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_regime_gate.py`에 추가:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from crypto_trader.config import RiskConfig, WalletConfig
from crypto_trader.execution.paper import PaperBroker
from crypto_trader.models import Candle, Position, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.wallet import StrategyWallet


def _make_candles(n: int = 50, base: float = 100.0) -> list[Candle]:
    start = datetime(2025, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=start + timedelta(hours=i),
            open=base,
            high=base * 1.01,
            low=base * 0.99,
            close=base,
            volume=1000.0,
        )
        for i in range(n)
    ]


class _StaticSignalStrategy:
    """Strategy that always returns a fixed signal."""

    def __init__(self, action: SignalAction, confidence: float = 0.9) -> None:
        self._action = action
        self._confidence = confidence

    def evaluate(
        self,
        candles: list[Candle],
        position: Position | None = None,
        *,
        symbol: str = "",
        macro: object = None,
    ) -> Signal:
        return Signal(
            action=self._action,
            reason="static_signal",
            confidence=self._confidence,
        )


def _make_wallet(
    active_regimes: list[str] | None = None,
    market_regime: str = "bull",
) -> StrategyWallet:
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides=(
            {"active_regimes": active_regimes} if active_regimes is not None else {}
        ),
    )
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk_manager = RiskManager(
        RiskConfig(
            risk_per_trade_pct=0.01,
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            max_daily_loss_pct=0.05,
            max_concurrent_positions=5,
            min_entry_confidence=0.0,
        )
    )
    wallet = StrategyWallet(
        wallet_config,
        _StaticSignalStrategy(SignalAction.BUY),
        broker,
        risk_manager,
    )
    wallet.set_market_regime(market_regime)
    return wallet


def test_regime_gate_blocks_buy_in_wrong_regime() -> None:
    """active_regimes=["bull"], regime=bear → BUY must be HOLD with regime_gate reason."""
    wallet = _make_wallet(active_regimes=["bull"], market_regime="bear")
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "regime_gate" in result.signal.reason


def test_regime_gate_reason_contains_regime_name() -> None:
    """regime_gate reason must name the blocked regime."""
    wallet = _make_wallet(active_regimes=["bull"], market_regime="sideways")
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "sideways" in result.signal.reason


def test_regime_gate_allows_buy_in_active_regime() -> None:
    """active_regimes includes regime → regime_gate must NOT block."""
    wallet = _make_wallet(active_regimes=["bull", "sideways"], market_regime="sideways")
    result = wallet.run_once("KRW-SOL", _make_candles())
    # regime_gate must NOT be the reason — may still be blocked by macro gate
    assert "regime_gate" not in result.signal.reason


def test_regime_gate_does_not_block_sell_exit() -> None:
    """SELL (exit) must never be blocked by active_regimes gate."""
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides={"active_regimes": ["bull"]},
    )
    broker = PaperBroker(starting_cash=500_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    # Inject an existing position so strategy sees it and can SELL
    broker.positions["KRW-SOL"] = Position(
        symbol="KRW-SOL",
        quantity=5.0,
        entry_price=100.0,
        entry_time=datetime(2025, 1, 1),
    )
    risk_manager = RiskManager(RiskConfig(min_entry_confidence=0.0))
    sell_strategy = _StaticSignalStrategy(SignalAction.SELL, confidence=0.9)
    wallet = StrategyWallet(wallet_config, sell_strategy, broker, risk_manager)
    wallet.set_market_regime("bear")  # regime would block BUY but must not block SELL

    result = wallet.run_once("KRW-SOL", _make_candles())

    assert "regime_gate" not in result.signal.reason


def test_default_active_regimes_is_bull() -> None:
    """Wallet with no active_regimes override defaults to ['bull']."""
    wallet = _make_wallet(active_regimes=None, market_regime="bull")
    assert wallet._active_regimes == ["bull"]


def test_set_market_regime_not_called_defaults_to_sideways() -> None:
    """Without set_market_regime, default is 'sideways' — bull-only wallet blocks."""
    wallet_config = WalletConfig(
        name="test_wallet",
        strategy="momentum",
        initial_capital=1_000_000.0,
        strategy_overrides={"active_regimes": ["bull"]},
    )
    broker = PaperBroker(starting_cash=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0005)
    risk_manager = RiskManager(RiskConfig(min_entry_confidence=0.0))
    wallet = StrategyWallet(
        wallet_config,
        _StaticSignalStrategy(SignalAction.BUY),
        broker,
        risk_manager,
    )
    # Intentionally NOT calling set_market_regime → defaults to "sideways"
    result = wallet.run_once("KRW-SOL", _make_candles())
    assert result.signal.action == SignalAction.HOLD
    assert "regime_gate" in result.signal.reason
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_regime_gate.py -k "regime_gate or default_active_regimes or set_market_regime" -v
```

Expected: 여러 테스트 `FAILED` with `AttributeError: 'StrategyWallet' object has no attribute 'set_market_regime'` or `'_active_regimes'`

- [ ] **Step 3: wallet.py `__init__` 수정 — `_active_regimes`, `_current_market_regime` 추가**

`src/crypto_trader/wallet.py` `__init__` 내 `_btc_stealth_gate` 선언 바로 뒤(line ~326)에 추가:

```python
        self._btc_stealth_gate: bool = bool(
            wallet_config.strategy_overrides.get("btc_stealth_gate", False)
        )
        self._btc_30bar_gate: bool = bool(
            wallet_config.strategy_overrides.get("btc_30bar_gate", False)
        )
        # Regime-aware gate: list of regime strings this wallet may trade in.
        # Populated from strategy_overrides["active_regimes"]; defaults to ["bull"].
        self._active_regimes: list[str] = list(
            wallet_config.strategy_overrides.get("active_regimes", ["bull"])
        )
        # Injected per-tick by multi_runtime via set_market_regime(); defaults to "sideways"
        # so un-initialized wallets do not accidentally trade in unknown regimes.
        self._current_market_regime: str = "sideways"
```

- [ ] **Step 4: wallet.py `set_market_regime()` 메서드 추가**

`set_macro_snapshot()` 메서드 바로 뒤에 추가:

```python
    def set_market_regime(self, regime: str) -> None:
        """Inject the current market regime string (bull/sideways/bear) from multi_runtime."""
        self._current_market_regime = regime
```

- [ ] **Step 5: wallet.py `run_once()` — active_regimes 게이트 삽입**

`run_once()` 내 `force_fear_buy` 선언 줄(현재 line ~550) 바로 앞에 삽입:

현재 코드:
```python
            # --- Macro regime gate: block entries in adverse regimes ---
            force_fear_buy = str(signal.context.get("force_fear_buy", "")).lower() == "true"
            regime_blocked, regime_reason = self._macro_adapter.should_block_entry(
```

변경 후:
```python
            # --- active_regimes gate (fast, no I/O) — must run before macro gate ---
            if position is None and signal.action is SignalAction.BUY:
                if self._current_market_regime not in self._active_regimes:
                    self._logger.info(
                        "[%s] BUY blocked by active_regimes gate: regime=%s not in %s",
                        symbol,
                        self._current_market_regime,
                        self._active_regimes,
                    )
                    signal = Signal(
                        action=SignalAction.HOLD,
                        reason=f"regime_gate: {self._current_market_regime}",
                        confidence=signal.confidence,
                        indicators=signal.indicators,
                        context={**(signal.context or {}), "original_action": "BUY"},
                    )

            # --- Macro regime gate: block entries in adverse regimes ---
            force_fear_buy = str(signal.context.get("force_fear_buy", "")).lower() == "true"
            regime_blocked, regime_reason = self._macro_adapter.should_block_entry(
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
pytest tests/test_regime_gate.py -k "regime_gate or default_active_regimes or set_market_regime" -v
```

Expected: 모든 해당 테스트 `PASSED`

- [ ] **Step 7: mypy 타입 체크**

```bash
mypy src/crypto_trader/wallet.py
```

Expected: `Success: no issues found`

- [ ] **Step 8: ruff 린트**

```bash
ruff check src/crypto_trader/wallet.py
```

Expected: 에러 없음

- [ ] **Step 9: 커밋**

```bash
git add src/crypto_trader/wallet.py tests/test_regime_gate.py
git commit -m "feat: wallet active_regimes gate — set_market_regime() + run_once BUY guard"
```

---

## Task 3: multi_runtime.py — 틱마다 regime 주입

**Files:**
- Modify: `src/crypto_trader/multi_runtime.py` (~line 440, ~line 1002)
- Test: `tests/test_regime_gate.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_regime_gate.py`에 추가 (import는 파일 상단 import 블록에, 함수는 파일 끝에):

```python
# 파일 상단 import 블록에 추가:
from unittest.mock import MagicMock


def test_run_tick_propagates_regime_to_all_wallets() -> None:
    """_run_tick() must call set_market_regime on every wallet after regime detection."""
    from crypto_trader.multi_runtime import MultiSymbolRuntime

    # Build minimal runtime with mock wallets
    runtime = MagicMock(spec=MultiSymbolRuntime)
    runtime._current_market_regime = "sideways"
    runtime._wallets = [MagicMock(), MagicMock()]

    # Call the real method, not the mock
    MultiSymbolRuntime._propagate_market_regime(runtime)

    for wallet in runtime._wallets:
        wallet.set_market_regime.assert_called_once_with("sideways")
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_regime_gate.py::test_run_tick_propagates_regime_to_all_wallets -v
```

Expected: `FAILED` — `AttributeError: _propagate_market_regime`

- [ ] **Step 3: multi_runtime.py — `_propagate_market_regime()` 추가**

`_propagate_macro_snapshot()` 메서드(line ~1002) 바로 뒤에 추가:

```python
    def _propagate_market_regime(self) -> None:
        """Inject current market regime string into every wallet for active_regimes gating."""
        for wallet in self._wallets:
            wallet.set_market_regime(self._current_market_regime)
```

- [ ] **Step 4: multi_runtime.py — `_run_tick()`에서 호출 추가**

`_run_tick()` 내 `self._refresh_macro()` 호출(line ~440) 바로 뒤에 추가:

현재:
```python
        # Refresh macro/regime-aware multipliers after regime detection and price collection.
        self._refresh_macro()
        self._apply_kill_switch_penalty()
```

변경 후:
```python
        # Refresh macro/regime-aware multipliers after regime detection and price collection.
        self._refresh_macro()
        self._propagate_market_regime()
        self._apply_kill_switch_penalty()
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
pytest tests/test_regime_gate.py::test_run_tick_propagates_regime_to_all_wallets -v
```

Expected: `PASSED`

- [ ] **Step 6: mypy + ruff**

```bash
mypy src/crypto_trader/multi_runtime.py
ruff check src/crypto_trader/multi_runtime.py
```

Expected: 에러 없음

- [ ] **Step 7: 커밋**

```bash
git add src/crypto_trader/multi_runtime.py tests/test_regime_gate.py
git commit -m "feat: multi_runtime propagates market regime to wallets each tick"
```

---

## Task 4: daemon.toml — active_regimes 선언

**Files:**
- Modify: `config/daemon.toml` (각 `[[wallets]]` 섹션)

> **주의:** `wc -c config/daemon.toml` 결과가 100바이트 이상인지 확인 후 작업. 35바이트면 손상 → `git checkout HEAD -- config/daemon.toml`로 복구 먼저.

- [ ] **Step 1: daemon.toml 무결성 확인**

```bash
wc -c config/daemon.toml
```

Expected: 18000바이트 이상. 35이면 `git checkout HEAD -- config/daemon.toml` 실행 후 재시도.

- [ ] **Step 2: 각 지갑에 active_regimes 추가**

변경 내용 (지갑별):

**accumulation_dood_wallet** — `btc_stealth_gate = true` 뒤에 추가:
```toml
btc_stealth_gate = true
active_regimes = ["bull"]
```

**accumulation_tree_wallet** — 동일:
```toml
btc_stealth_gate = true
active_regimes = ["bull"]
```

**momentum_sol_wallet** — `btc_stealth_gate = true` 제거하고 `active_regimes`로 대체:
```toml
# btc_stealth_gate = true  ← 제거 (active_regimes로 대체)
active_regimes = ["bull"]
```

**volspike_btc_wallet** — `btc_stealth_gate = true` 뒤에 추가:
```toml
btc_stealth_gate = true
active_regimes = ["bull"]
```

**vpin_eth_wallet** — `btc_stealth_gate = true`를 `false`로 변경하고 `active_regimes` 추가:
```toml
btc_stealth_gate = false   # ← true에서 변경: active_regimes가 레짐 필터 담당
active_regimes = ["bull", "sideways", "bear"]
```

- [ ] **Step 3: load_config 검증 통과 확인**

```bash
cd /home/wdsr88/workspace/crypto-trader
python -c "
from crypto_trader.config import load_config
cfg = load_config('config/daemon.toml')
for w in cfg.wallets:
    ar = w.strategy_overrides.get('active_regimes', ['bull'])
    print(f'{w.name}: active_regimes={ar}')
"
```

Expected 출력:
```
accumulation_dood_wallet: active_regimes=['bull']
accumulation_tree_wallet: active_regimes=['bull']
momentum_sol_wallet: active_regimes=['bull']
volspike_btc_wallet: active_regimes=['bull']
vpin_eth_wallet: active_regimes=['bull', 'sideways', 'bear']
```

- [ ] **Step 4: 커밋**

```bash
git add config/daemon.toml
git commit -m "config: add active_regimes to all wallets — vpin_eth opens BEAR/SIDEWAYS"
```

---

## Task 5: 전체 검증 및 회귀 테스트

**Files:**
- 수정 없음 — 검증만

- [ ] **Step 1: 전체 테스트 suite 실행**

```bash
cd /home/wdsr88/workspace/crypto-trader
pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: 모든 테스트 PASSED. 실패 시 오류 메시지 확인 후 수정.

- [ ] **Step 2: safety 상수 불변 확인**

```bash
pytest tests/test_risk_hardening.py -v
```

Expected: PASSED. `HARD_MAX_DAILY_LOSS_PCT`, `SAFE_MAX_CONSECUTIVE_LOSSES`, `SAFE_DEFAULT_MAX_POSITION_PCT` 변경 없음.

- [ ] **Step 3: mypy 전체 소스**

```bash
mypy src/ 2>&1 | tail -20
```

Expected: `Success: no issues found` 또는 기존과 동일한 오류만.

> 만약 `_active_regimes`, `_current_market_regime` 관련 새 mypy 오류 발생 시: 타입 어노테이션 재확인.

- [ ] **Step 4: ruff 전체 린트**

```bash
ruff check src/ tests/ 2>&1 | grep -v "^$" | head -20
```

Expected: 에러 없음.

- [ ] **Step 5: daemon.toml 무결성 재확인**

```bash
wc -c config/daemon.toml && python -c "
import tomllib
with open('config/daemon.toml', 'rb') as f:
    data = tomllib.load(f)
print('TOML parse OK, wallets:', len(data.get('wallets', [])))
"
```

Expected: 18000바이트 이상, `TOML parse OK, wallets: 5`

- [ ] **Step 6: 최종 커밋**

```bash
git add -u
git commit -m "test: regime gate full test suite — 7 cases all passing"
```

---

## 완료 기준 체크리스트

- [ ] `pytest tests/` — 전체 통과
- [ ] `pytest tests/test_regime_gate.py -v` — 7개 케이스 모두 PASSED
- [ ] `mypy src/` — 새 오류 없음
- [ ] `ruff check src/ tests/` — 에러 없음
- [ ] `wc -c config/daemon.toml` — 18000바이트 이상 (손상 없음)
- [ ] `active_regimes=["bull","sideways","bear"]` vpin_eth 에서 load_config 검증 통과
- [ ] BEAR 레짐 + momentum_sol → `regime_gate: bear` HOLD 확인
- [ ] BEAR 레짐 + vpin_eth → regime_gate 통과 (macro gate 단계로 진입)
