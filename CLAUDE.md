# crypto-trader

Upbit multi-strategy auto-trading. Backtesting, paper, live. FIRE workspace: `~/workspace/WORKSPACE.md`.

## *** 과최적화 금지 — 최우선 원칙 ***

> **백테스트 Sharpe 숫자를 올리는 것 ≠ 실전 수익.**
> 13일 553커밋, ralph 213사이클, research 251사이클 돌렸지만 실전 paper 9거래 WR 11% (₩-7,695).
> 필터를 쌓을수록 실전 진입 0건이 되는 과최적화 함정에 빠졌음.

**절대 규칙:**
1. 백테스트는 **아이디어 스크리닝 용도만**. 최종 판단은 forward(paper/live) 데이터로.
2. 자동 루프(ralph/research/evaluator)로 Sharpe 반복 최적화 **금지**.
3. paper 데이터 30건+ 없이 파라미터 변경/전략 배포 **금지**.
4. "시스템 위에 시스템" (메타 평가자, 추가 루프 등) 제안 **금지**.
5. 백테스트 필터와 daemon 필터가 **동일한지 반드시 확인** — 괴리가 실전 거래 0건의 원인이었음.
6. **"더이상 하지마라" = 진짜 멈춰라.** 기본을 지킬 것.

## Architecture

```
src/crypto_trader/
  config.py          # AppConfig dataclass, TOML loader, HARD safety constants
  pipeline.py        # Single-symbol trading pipeline (signal -> risk -> order)
  runtime.py         # Single-wallet runtime loop
  multi_runtime.py   # Multi-wallet daemon supervisor
  models.py          # Signal, Order, PipelineResult dataclasses
  wallet.py          # Wallet state tracking
  capital_allocator.py
  strategy/          # Strategy implementations (momentum, vpin, volume_spike, etc.)
    composite.py     # CompositeStrategy -- multi-strategy consensus
    evaluator.py     # Strategy evaluation framework
  risk/
    manager.py       # RiskManager -- position sizing, stop-loss, take-profit
    kill_switch.py   # Tiered kill switch (warn -> reduce -> halt)
  backtest/          # Backtesting engine, grid search, walk-forward
  data/              # Market data clients (Upbit, candle cache)
  execution/         # Paper broker, live broker
  macro/             # macro-intelligence integration
  monitoring/        # Health checks, PnL snapshots
  notifications/     # Telegram alerts
  operator/          # Operator reports, journals, memos
config/              # TOML configs (daemon.toml = production)
scripts/             # CLI tools: backtest, optimize, reports
dashboard/           # Streamlit dashboard
tests/               # pytest suite
```

## Tech Stack

- Python 3.12+, setuptools
- Upbit REST API via pyupbit
- pytest, mypy (strict on src/), ruff (E/F/I/B/UP)
- Streamlit dashboard
- macro-intelligence HTTP client for regime signals

## Safety Rules (NEVER BYPASS)

`config.py` hard limits — change requires explicit user approval:
- `HARD_MAX_DAILY_LOSS_PCT = 0.05`
- `SAFE_MAX_CONSECUTIVE_LOSSES = 3`
- `SAFE_DEFAULT_MAX_POSITION_PCT = 0.10`
- kill switch: warn(50%) → reduce(75%) → halt(100%)

## Coding Rules

- Line length: 100 chars (ruff)
- Type hints required for all src/ code (mypy strict)
- Tests in `tests/`, named `test_*.py`, run with `pytest`
- Config via TOML dataclasses -- no env vars for trading params
- All strategies must implement the base strategy interface
- Backtest before deploying any parameter change to daemon.toml
- Never commit real API keys -- credentials fields stay empty in config

## Key Commands

```bash
pytest                              # run all tests
pytest tests/test_risk_hardening.py # safety-specific tests
mypy src/                           # type check
ruff check src/ tests/ scripts/     # lint
python -m crypto_trader.cli         # run daemon
```

## Config Hierarchy

1. `config/daemon.toml` -- production config (5 active wallets)
2. `config/live.toml` -- live trading overrides
3. `config/optimized.toml` -- latest optimization results
4. Per-wallet `strategy_overrides` / `risk_overrides` in `[[wallets]]` sections

## Wallet Strategy

Allocated by 90-day ROI + Sharpe. Disabled wallets commented in `daemon.toml`.

## Macro Regime Integration

매크로 서버: `http://127.0.0.1:8000` (macro-intelligence 프로젝트)
- `/regime/current` — 전체 레짐 + VIX/DXY/KOSPI 등 개별 시그널
- `/regime/downstream/crypto-trader` — crypto-trader 전용 페이로드
- `src/crypto_trader/macro/client.py` + `adapter.py` — 레짐 → 포지션 배수 변환

**TODO: pre_bull_score에 매크로 보너스 추가**
```
macro_bonus = btc_trend_pos(+0.1) + expansionary(+0.3)
pre_bull_score_adjusted = pre_bull_score + macro_bonus
```
- btc_trend_pos: BTC 10봉 수익률 > 0 (DXY 약세 proxy) — 사이클 94 검증
- vix_falling: 백테스트 역효과 확인 → 삭제 (사이클 94)
- dxy_falling: btc_trend_pos로 대체
- 서버 다운 또는 confidence < 0.3 이면 macro_bonus = 0.0 (fallback)

## Codex 활용

| 트리거 | 커맨드 |
|---|---|
| 백테스트 30분+ | `/codex:rescue --background scripts/xxx.py` |
| daemon.toml 반영 전 | `/codex:review` |
| 두 작업 병렬 | Claude 하나 + `/codex:rescue --background` |
| 리팩토링/검증 | `/codex:adversarial-review` |
| 탐색적 분석 | `/codex:rescue 결과만 보고` |

금지: safety 상수 변경, daemon.toml 수정, API 키 — Claude 직접 처리.

## Backtest Rules

- 백테스트 완료 시 결과를 반드시 `docs/backtest_history.md`에 누적 기록
- CLAUDE.md에 결과 직접 기록 금지 (토큰 낭비)
- 실패한 전략도 기록 필수 — 동일 실험 반복 방지
- 기록 포맷: 날짜 | 전략명 | 파라미터 | 승률 | avg수익 | Sharpe | 결론
- **새 전략 설계 전 반드시 `docs/backtest_history.md` 확인** — 과거 실험 반복 방지
