# Backtest Integrity Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 코드에서 확인된 3개 버그 수정 — BacktestEngine 1봉 선행 편향, daemon.toml 비원자 쓰기, ralph 프롬프트 진입가 규칙 추가

**Architecture:**
- Task 1: `BacktestEngine`의 진입가를 신호 봉 종가 → 다음 봉 시가로 변경 (1봉 지연 진입)
- Task 2: `wallet_auto_updater._write_config`를 temp파일 + `os.replace()` 원자적 쓰기로 교체
- Task 3: ralph 프롬프트에 "다음 봉 시가 진입" 규칙 추가 (ralph 생성 스크립트도 동일 기준 적용)

**Tech Stack:** Python 3.12, pathlib, os

**참고: 확인되지 않은 주장들**
- ~~매크로 서버 오염~~ → adapter.py는 순수 계산 클래스, HTTP 호출 없음 (GPT-5.4 hallucination)
- KillSwitch 영속화 → 이미 구현됨 (multi_runtime.py:110, 357, 687)
- stealth_3gate volume 0 나눗셈 → 이미 방어 코드 있음 (line 291 `if v_ma < 1e-9`)

---

## File Map

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `src/crypto_trader/backtest/engine.py` | Modify | 진입가: signal봉 close → next봉 open, 루프 구조 조정 |
| `scripts/wallet_auto_updater.py:66-67` | Modify | `_write_config`: write_text → temp + os.replace |
| `scripts/crypto_ralph.sh` | Modify | 프롬프트 규칙: 다음 봉 시가 진입 명시 |

---

### Task 1: BacktestEngine 1봉 선행 편향 수정

**문제:** `engine.py:61`에서 `market_price = current.close` 후 동일 봉에서 진입.
실거래에서는 신호 봉 종가 확인 후 다음 봉 시가에 진입. 모든 Sharpe 수치가 낙관적으로 편향됨.

**Files:**
- Modify: `src/crypto_trader/backtest/engine.py`
- Test: `tests/test_backtest_engine.py` (있으면 수정, 없으면 생성)

- [ ] **Step 1: 현재 진입 로직 확인**

```bash
grep -n "market_price\|fill_price\|pending" src/crypto_trader/backtest/engine.py | head -20
```

- [ ] **Step 2: 테스트 작성 — 신호 봉과 진입 봉이 분리되는지 확인**

`tests/test_backtest_engine_entry.py` 생성:

```python
"""BacktestEngine이 신호 봉 다음 봉에 진입하는지 검증."""
from crypto_trader.backtest.engine import BacktestEngine
from crypto_trader.config import BacktestConfig
from crypto_trader.models import Candle, Signal, SignalAction
from crypto_trader.risk.manager import RiskManager
from crypto_trader.config import RiskConfig
from datetime import datetime, timezone


class AlwaysBuyStrategy:
    """항상 BUY 신호를 반환하는 테스트용 전략."""
    def evaluate(self, candles, position=None, *, symbol=""):
        return Signal(
            action=SignalAction.BUY,
            confidence=1.0,
            reason="always_buy",
        )


def _make_candle(ts_offset_hours: int, open_: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, 1, ts_offset_hours, 0, tzinfo=timezone.utc),
        open=open_,
        high=max(open_, close) + 1,
        low=min(open_, close) - 1,
        close=close,
        volume=1000.0,
    )


def test_entry_uses_next_bar_open():
    """진입가가 신호 봉 종가가 아닌 다음 봉 시가여야 한다."""
    candles = [
        _make_candle(0, open_=100.0, close=110.0),  # bar 0: 신호 발생 봉
        _make_candle(1, open_=105.0, close=115.0),  # bar 1: 진입해야 하는 봉 (시가=105)
        _make_candle(2, open_=106.0, close=112.0),  # bar 2
        _make_candle(3, open_=107.0, close=108.0),  # bar 3
    ]
    config = BacktestConfig(initial_capital=1_000_000.0, fee_rate=0.0005, slippage_pct=0.0)
    risk = RiskManager(RiskConfig())
    engine = BacktestEngine(AlwaysBuyStrategy(), risk, config, symbol="TEST")
    result = engine.run(candles)

    assert len(result.trades) >= 1
    # 진입가는 bar 1의 시가(105.0)여야 함, bar 0의 종가(110.0)가 아님
    first_trade = result.trades[0]
    assert abs(first_trade.entry_price - 105.0) < 1.0, (
        f"진입가 {first_trade.entry_price}가 다음 봉 시가(105.0) 근방이어야 함. "
        f"신호 봉 종가(110.0)면 선행 편향 버그."
    )
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
.venv/bin/python -m pytest tests/test_backtest_engine_entry.py -v 2>&1 | tail -20
```
Expected: FAIL — `entry_price`가 110.0 (신호 봉 종가) 근방

- [ ] **Step 4: engine.py 수정 — pending_entry 패턴으로 1봉 지연**

`src/crypto_trader/backtest/engine.py`의 `run()` 메서드:

현재 구조 (진입 즉시):
```python
for index in range(len(candles)):
    window = candles[:index + 1]
    current = window[-1]
    market_price = current.close
    ...
    if signal is BUY:
        fill_price = _entry_fill_price(position_side, market_price, slippage_pct)
        open_position = Position(entry_price=fill_price, ...)
```

수정 후 (1봉 지연 진입):

`run()` 메서드 상단 변수 선언부에 추가:
```python
pending_entry_side: str | None = None   # 다음 봉 시가에 채울 진입 사이드
pending_entry_confidence: float = 0.0
pending_entry_regime: str = "unknown"
```

루프 최상단 (`window = candles[:index + 1]` 바로 다음)에 추가:
```python
# ── pending entry 처리 (전 봉 신호 → 현재 봉 시가 진입) ──
if pending_entry_side is not None and open_position is None:
    fill_price = _entry_fill_price(
        pending_entry_side,
        current.open,          # ← 다음 봉 시가 사용
        self._config.slippage_pct,
    )
    regime_mult = 1.0
    if self._regime_aware and self._regime_detector is not None and index >= 31:
        regime_mult = self.REGIME_SIZE_MULT.get(
            self._regime_detector.detect(window), 1.0
        )
    quantity = self._risk_manager.size_position(cash, fill_price, regime_mult)
    if quantity > 0:
        gross = quantity * fill_price
        fee = gross * self._config.fee_rate
        total_cost = gross + fee
        if pending_entry_side == "short":
            cash += gross - fee
            open_position = Position(
                symbol=self._symbol,
                quantity=quantity,
                entry_price=fill_price,
                entry_time=current.timestamp,
                entry_index=index,
                entry_fee_paid=fee,
                side=pending_entry_side,
            )
            entry_bar = index
            entry_confidence = pending_entry_confidence
            entry_regime = pending_entry_regime
        elif total_cost <= cash:
            cash -= total_cost
            open_position = Position(
                symbol=self._symbol,
                quantity=quantity,
                entry_price=fill_price,
                entry_time=current.timestamp,
                entry_index=index,
                entry_fee_paid=fee,
                side=pending_entry_side,
            )
            entry_bar = index
            entry_confidence = pending_entry_confidence
            entry_regime = pending_entry_regime
    pending_entry_side = None
    pending_entry_confidence = 0.0
    pending_entry_regime = "unknown"
```

기존 진입 블록 (`if quantity > 0:` 전체)을 아래로 교체:
```python
# 신호 발생 → pending으로 등록 (다음 봉 시가에 진입)
pending_entry_side = position_side
pending_entry_confidence = signal.confidence
pending_entry_regime = signal.context.get("market_regime", "unknown")
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
.venv/bin/python -m pytest tests/test_backtest_engine_entry.py -v 2>&1 | tail -10
```
Expected: PASS

- [ ] **Step 6: 기존 전체 테스트 확인**

```bash
.venv/bin/python -m pytest tests/ -x -q 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
git add src/crypto_trader/backtest/engine.py tests/test_backtest_engine_entry.py
git commit -m "fix: backtest engine 1봉 선행 편향 수정 — 신호봉 close → 다음봉 open 진입 (Opus/Codex 리뷰)"
```

---

### Task 2: daemon.toml 원자적 쓰기

**문제:** `wallet_auto_updater._write_config`가 `write_text()` 사용 → 쓰기 중 다른 프로세스가 읽으면 파셜 TOML.

**Files:**
- Modify: `scripts/wallet_auto_updater.py:66-67`

- [ ] **Step 1: 현재 코드 확인**

```bash
sed -n '60,70p' scripts/wallet_auto_updater.py
```
Expected:
```python
def _write_config(content: str) -> None:
    DAEMON_CONFIG.write_text(content, encoding="utf-8")
```

- [ ] **Step 2: 원자적 쓰기로 교체**

`scripts/wallet_auto_updater.py` 상단 import에 `import os` 추가 (없으면):
```python
import os
```

`_write_config` 함수 교체:
```python
def _write_config(content: str) -> None:
    """daemon.toml을 원자적으로 쓴다. 쓰기 중 다른 프로세스의 파셜 읽기 방지."""
    tmp = DAEMON_CONFIG.with_suffix(".toml.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, DAEMON_CONFIG)
```

- [ ] **Step 3: 동작 확인**

```bash
.venv/bin/python -c "
from scripts.wallet_auto_updater import _write_config
import pathlib
_write_config('[test]\nkey = \"value\"')
print(pathlib.Path('config/daemon.toml').read_text()[:50])
print('원자적 쓰기 OK')
"
```
Expected: daemon.toml 내용 정상 출력 + "원자적 쓰기 OK"

- [ ] **Step 4: Commit**

```bash
git add scripts/wallet_auto_updater.py
git commit -m "fix: daemon.toml 원자적 쓰기 — write_text → tmp+os.replace (race condition 방지)"
```

---

### Task 3: ralph 프롬프트에 다음 봉 시가 진입 규칙 추가

**이유:** ralph가 생성하는 백테스트 스크립트들도 동일한 선행 편향을 가질 수 있음. 프롬프트 규칙으로 Claude에게 올바른 진입 시점 명시.

**Files:**
- Modify: `scripts/crypto_ralph.sh`

- [ ] **Step 1: 현재 규칙 섹션 확인**

```bash
grep -A 15 "규칙 (절대 준수)" scripts/crypto_ralph.sh
```

- [ ] **Step 2: 규칙 추가**

기존:
```
- 슬리피지 미포함 백테스트 결과에는 반드시 ★슬리피지미포함 표시
```

아래에 한 줄 추가:
```
- 백테스트 진입가: 신호 발생 봉의 종가(close) 사용 금지 → 반드시 다음 봉 시가(next_bar.open) 사용
```

- [ ] **Step 3: 확인**

```bash
grep "다음 봉 시가\|next_bar" scripts/crypto_ralph.sh
```
Expected: 추가한 줄 출력

- [ ] **Step 4: Commit**

```bash
git add scripts/crypto_ralph.sh
git commit -m "feat: ralph 프롬프트 — 백테스트 진입가 선행 편향 방지 규칙 추가"
```

---

## 완료 기준

- [ ] `test_entry_uses_next_bar_open` PASS
- [ ] 기존 테스트 전체 통과
- [ ] `daemon.toml.tmp` 임시 파일 → `os.replace()` 확인
- [ ] ralph 프롬프트에 next_bar.open 규칙 포함

## 영향 범위

BacktestEngine을 사용하는 공식 백테스트 경로는 수정됨. ralph가 생성한 standalone 스크립트들은 각자 루프를 구현하므로 이번 수정 직접 적용 안 됨 → 프롬프트 규칙(Task 3)으로 보완.

## 수정 후 재검증 필요 전략

Engine 수정으로 기존 Sharpe 수치가 바뀔 수 있음. 주요 전략 재백테스트 권장:
- stealth_3gate (현재 Sharpe 5.129)
- vpin_eth (Sharpe 7.461)
- momentum_sol (Sharpe 14.37)
