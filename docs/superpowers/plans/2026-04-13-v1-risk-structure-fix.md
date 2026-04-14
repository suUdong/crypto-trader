# v1 리스크 구조 3대 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ATR 스탑 구조적 결함 3가지 (열린 봉, 가변 ATR, 이중 exit) 수정으로 paper 승률 개선

**Architecture:** Position에 entry_atr 필드 추가, RiskManager가 entry_atr 기반으로 스탑 계산, daemon.toml에서 closed_only 강제 + 자체 exit 전략은 전역 스탑 비활성화

**Tech Stack:** Python 3.12, pytest, mypy strict

**Spec:** `docs/superpowers/specs/2026-04-13-v1-risk-structure-fix-design.md`

---

### Task 1: Position에 entry_atr 필드 추가

**Files:**
- Modify: `src/crypto_trader/models.py:68-84`
- Test: `tests/test_models_entry_atr.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_entry_atr.py
from datetime import datetime, timezone
from crypto_trader.models import Position

def test_position_has_entry_atr_default_zero():
    pos = Position(
        symbol="KRW-BTC",
        quantity=0.001,
        entry_price=100_000_000.0,
        entry_time=datetime.now(timezone.utc),
    )
    assert pos.entry_atr == 0.0

def test_position_entry_atr_set_at_construction():
    pos = Position(
        symbol="KRW-BTC",
        quantity=0.001,
        entry_price=100_000_000.0,
        entry_time=datetime.now(timezone.utc),
        entry_atr=1_500_000.0,
    )
    assert pos.entry_atr == 1_500_000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_models_entry_atr.py -v`
Expected: FAIL with `TypeError: ...unexpected keyword argument 'entry_atr'`

- [ ] **Step 3: Add entry_atr field to Position**

In `src/crypto_trader/models.py`, add after `entry_fee_rate: float = 0.0` (line 83):

```python
    entry_atr: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_models_entry_atr.py -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -x -q 2>&1 | tail -5`
Expected: all pass (entry_atr has default 0.0, backward compatible)

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/models.py tests/test_models_entry_atr.py
git commit -m "feat(models): add entry_atr field to Position for frozen ATR stops"
```

---

### Task 2: RiskManager가 entry_atr 기반으로 스탑 계산

**Files:**
- Modify: `src/crypto_trader/risk/manager.py:447-475`
- Test: `tests/test_risk_entry_atr.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_entry_atr.py
from datetime import datetime, timezone
from crypto_trader.config import RiskConfig
from crypto_trader.models import Position
from crypto_trader.risk.manager import RiskManager

def _make_risk_config(**overrides):
    defaults = dict(
        risk_per_trade_pct=0.01,
        stop_loss_pct=0.05,
        take_profit_pct=0.10,
        max_daily_loss_pct=0.05,
        max_concurrent_positions=3,
        trailing_stop_pct=0.0,
        atr_stop_multiplier=0.0,
        atr_tp_multiplier=3.0,
        atr_sl_multiplier=1.5,
        min_entry_confidence=0.0,
        partial_tp_pct=0.0,
        cooldown_bars=0,
        max_position_pct=0.50,
    )
    defaults.update(overrides)
    return RiskConfig(**defaults)

def _make_position(entry_price=100.0, entry_atr=0.0):
    return Position(
        symbol="KRW-BTC",
        quantity=1.0,
        entry_price=entry_price,
        entry_time=datetime.now(timezone.utc),
        entry_atr=entry_atr,
    )

def test_atr_stop_uses_entry_atr_not_current():
    """When position has entry_atr, stop distance uses that, not current ATR."""
    config = _make_risk_config(atr_sl_multiplier=2.0, atr_tp_multiplier=4.0)
    rm = RiskManager(config)
    
    # entry_atr = 5.0, current_atr = 1.0 (shrank)
    rm.set_atr(1.0)
    pos = _make_position(entry_price=100.0, entry_atr=5.0)
    
    # With entry_atr=5.0, sl_dist = 5.0 * 2.0 = 10.0, stop at 90.0
    # Price at 91.0 should NOT trigger (above 90.0)
    result = rm.check_exit(pos, 91.0)
    assert result is None, f"Should not stop at 91.0, got {result}"
    
    # Price at 89.0 should trigger (below 90.0)
    result = rm.check_exit(pos, 89.0)
    assert result == "atr_stop_loss"

def test_atr_stop_falls_back_to_current_atr_when_entry_atr_zero():
    """When entry_atr is 0.0 (legacy positions), use current ATR."""
    config = _make_risk_config(atr_sl_multiplier=2.0, atr_tp_multiplier=4.0)
    rm = RiskManager(config)
    rm.set_atr(5.0)
    pos = _make_position(entry_price=100.0, entry_atr=0.0)
    
    # current_atr=5.0, sl_dist = 5.0 * 2.0 = 10.0, stop at 90.0
    result = rm.check_exit(pos, 89.0)
    assert result == "atr_stop_loss"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_risk_entry_atr.py -v`
Expected: `test_atr_stop_uses_entry_atr_not_current` FAILS (stop triggers at 91.0 because current_atr=1.0 is used)

- [ ] **Step 3: Modify RiskManager to use entry_atr**

In `src/crypto_trader/risk/manager.py`, replace the ATR stop block (around lines 447-475). Change `self._current_atr` to use `position.entry_atr` when available:

Find this code (line ~449):
```python
        if cfg.atr_tp_multiplier > 0 and cfg.atr_sl_multiplier > 0 and self._current_atr > 0:
            sl_mult, tp_mult = self._regime_atr_multipliers()
            atr_sl_dist = self._current_atr * sl_mult
            atr_tp_dist = self._current_atr * tp_mult
```

Replace with:
```python
        effective_atr = (
            position.entry_atr if position.entry_atr > 0 else self._current_atr
        )
        if cfg.atr_tp_multiplier > 0 and cfg.atr_sl_multiplier > 0 and effective_atr > 0:
            sl_mult, tp_mult = self._regime_atr_multipliers()
            atr_sl_dist = effective_atr * sl_mult
            atr_tp_dist = effective_atr * tp_mult
```

Also find the legacy block (line ~463):
```python
        elif self._atr_stop_multiplier > 0 and self._current_atr > 0:
            atr_stop_distance = self._current_atr * self._atr_stop_multiplier
```

Replace with:
```python
        elif self._atr_stop_multiplier > 0 and effective_atr > 0:
            atr_stop_distance = effective_atr * self._atr_stop_multiplier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_risk_entry_atr.py -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/ -x -q 2>&1 | tail -5`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/risk/manager.py tests/test_risk_entry_atr.py
git commit -m "feat(risk): use entry_atr for frozen ATR stop calculation"
```

---

### Task 3: wallet.py에서 진입 시 entry_atr 저장

**Files:**
- Modify: `src/crypto_trader/wallet.py` (Position 생성 부분)
- Modify: `src/crypto_trader/multi_runtime.py` (checkpoint restore에 entry_atr 포함)

- [ ] **Step 1: Find Position creation in wallet.py**

Run: `grep -n "Position(" src/crypto_trader/wallet.py | head -10`

- [ ] **Step 2: Add entry_atr to Position creation**

In `wallet.py`, where `Position(...)` is constructed for new entries, add `entry_atr=self.risk_manager._current_atr`:

```python
position = Position(
    symbol=symbol,
    quantity=filled_qty,
    entry_price=fill_price,
    entry_time=candles[-1].timestamp,
    entry_index=len(candles) - 1,
    entry_fee_paid=fee_paid,
    entry_confidence=signal.confidence,
    entry_atr=self.risk_manager._current_atr,  # NEW: freeze ATR at entry
    # ... rest of existing fields
)
```

- [ ] **Step 3: Add entry_atr to checkpoint save/restore**

In `src/crypto_trader/multi_runtime.py`, in the checkpoint positions dict (around line 1823), add:
```python
"entry_atr": pos.entry_atr,
```

In the restore block (around line 1740), add to Position construction:
```python
entry_atr=pos_data.get("entry_atr", 0.0),
```

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -x -q 2>&1 | tail -5`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/crypto_trader/wallet.py src/crypto_trader/multi_runtime.py
git commit -m "feat(wallet): freeze entry_atr on position creation + checkpoint support"
```

---

### Task 4: daemon.toml — closed_only 강제 + 자체 exit 전략 ATR 비활성화

**Files:**
- Modify: `config/daemon.toml`

- [ ] **Step 1: 글로벌 market_data_closed_only 확인**

`market_data_closed_only`는 per-wallet strategy_overrides에서 설정됨. 전 지갑에 추가 필요.

- [ ] **Step 2: 전 지갑에 market_data_closed_only = true 추가**

모든 `[wallets.strategy_overrides]` 섹션에 `market_data_closed_only = true` 추가.
없는 지갑은 `[wallets.strategy_overrides]` 섹션 생성 후 추가.

- [ ] **Step 3: 자체 exit 전략에 atr_stop_multiplier = 0.0 설정**

아래 지갑의 `[wallets.risk_overrides]`에 `atr_stop_multiplier = 0.0` 추가:
- `pdh_pdl_btc_wallet` (trailing stop 자체 exit)
- `vwm_btc_wallet` (fixed TP/SL 자체 exit)
- `bb_squeeze_eth_wallet` (자체 exit)
- `bb_squeeze_doge_wallet` (자체 exit)
- `bb_squeeze_link_wallet` (자체 exit)
- `bb_mr_doge_wallet` (자체 exit)
- `bb_mr_xrp_wallet` (자체 exit)
- `bb_mr_avax_wallet` (자체 exit)

나머지 지갑(vpin, momentum, stealth, volspike, accumulation)은 글로벌 `atr_stop_multiplier = 3.0` 유지.

- [ ] **Step 4: config 테스트 실행**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add config/daemon.toml
git commit -m "fix(config): closed_only=true all wallets + disable ATR stop for self-exit strategies"
```

---

### Task 5: 통합 검증 + daemon 재시작

**Files:** None (검증만)

- [ ] **Step 1: 전체 테스트 실행**

Run: `python3 -m pytest tests/ -x -q 2>&1 | tail -10`
Expected: all pass

- [ ] **Step 2: mypy 실행**

Run: `python3 -m mypy src/crypto_trader/models.py src/crypto_trader/risk/manager.py src/crypto_trader/wallet.py --strict 2>&1 | tail -10`
Expected: no errors

- [ ] **Step 3: daemon 재시작**

```bash
kill $(pgrep -f "crypto_trader.cli run-multi") 2>/dev/null
sleep 1
nohup .venv/bin/python -m crypto_trader.cli run-multi --config config/daemon.toml > logs/daemon.log 2>&1 &
echo "PID: $!"
```

- [ ] **Step 4: 로그 검증 — same-tick churn 없음 확인**

```bash
sleep 120  # 2분 대기 (2 ticks)
grep "order=filled" logs/daemon.log | head -5
# 진입 있으면: entry_time != exit_time 확인
```

- [ ] **Step 5: 로그 검증 — 자체 exit 전략에 atr_stop 없음 확인**

```bash
grep "pdh_pdl.*atr_stop\|vwm_btc.*atr_stop\|bb_squeeze.*atr_stop\|bb_mr.*atr_stop" logs/daemon.log
# Expected: 0 matches
```

- [ ] **Step 6: backtest_history.md 업데이트**

v1 리스크 구조 수정 사항 기록.

- [ ] **Step 7: Commit**

```bash
git add docs/backtest_history.md
git commit -m "docs: record v1 risk structure fix deployment"
```
