# CI Setup — Design Spec

- **Date:** 2026-04-07
- **Status:** Approved (pending user review of written spec)
- **Branch:** `feature/ci-setup`

## 1. 목표 & 원칙

**목표:** crypto-trader에 GitHub Actions 기반 CI를 추가해, master/PR마다 매매 코어가 회귀하지 않도록 게이트한다.

**원칙 (CLAUDE.md 준수):**
- 과엔지니어링 금지 — 매트릭스/커버리지/멀티 OS 다 거부
- 매매 핵심만 게이트 — 백테스트/리서치/GPU/리포트는 CI 제외
- 코드 변경 최소화 — 마커/디렉토리 이동 X. 워크플로우 파일에 화이트리스트 직접 나열

**Non-goals (이번에 안 함):**
- CD (Lightsail 자동 배포)
- 커버리지 게이팅
- pyproject extras 정리
- 테스트 디렉토리 재구조화
- mypy strict 통과

## 2. CI 워크플로우 구조

**파일:** `.github/workflows/ci.yml` (1개)

**트리거:**
```yaml
on:
  pull_request:
  push:
    branches: [master]
```

**최소 권한 & 동시 실행 제어:**
```yaml
permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

**Job: `test`** — Ubuntu latest, Python 3.12 단일, `timeout-minutes: 10`

**Steps:**
1. `actions/checkout@v4`
2. `actions/setup-python@v5` — Python 3.12, pip 캐시
3. `pip install -e .[dev]`
4. **Lint:** `ruff check src/ tests/ scripts/`
5. **Type check:** `mypy src/` — `continue-on-error: true`
6. **Test:** `pytest <whitelist>`

1 job 안에서 ruff → mypy → pytest 순차 실행. ruff 실패하면 빠르게 fail.

## 3. 테스트 화이트리스트

CI에서 돌릴 매매 코어 (60~70개, 목표 ~1분 이내).

**포함 (glob):**
- `tests/test_risk_*.py`, `tests/test_kill_switch*.py`
- `tests/test_pipeline.py`, `tests/test_runtime.py`, `tests/test_runtime_state.py`, `tests/test_multi_symbol.py`
- `tests/test_wallet*.py`, `tests/test_capital_allocator.py`, `tests/test_config.py`
- `tests/test_paper_broker.py`, `tests/test_live_broker.py`, `tests/test_broker_selection.py`
- `tests/test_daemon_*.py`, `tests/test_circuit_breaker.py`, `tests/test_cooldown.py`, `tests/test_watchdog.py`
- `tests/test_alert_manager.py`, `tests/test_monitoring.py`, `tests/test_preflight.py`, `tests/test_auto_pause.py`
- `tests/test_min_trade_filter.py`, `tests/test_correlation_guard.py`, `tests/test_drawdown_sizing.py`, `tests/test_kelly_sizing.py`
- `tests/test_partial_take_profit.py`, `tests/test_trailing_stop.py`, `tests/test_trailing_after_partial_tp.py`, `tests/test_time_decay_exit.py`
- `tests/test_macro_adapter.py`, `tests/test_macro_client.py`, `tests/test_macro_bonus.py`
- `tests/test_regime.py`, `tests/test_regime_gate.py`, `tests/test_regime_weights.py`, `tests/test_weekend_regime.py`
- `tests/test_strategy.py`, `tests/test_strategy_evaluator.py`, `tests/test_indicators.py`, `tests/test_adx_indicator.py`
- `tests/test_stealth_3gate.py`, `tests/test_vpin_strategy.py`
- `tests/test_momentum_strategy.py`, `tests/test_momentum_pullback_strategy.py`
- `tests/test_bollinger_mean_reversion.py`, `tests/test_bollinger_rsi_strategy.py`
- `tests/test_mean_reversion_strategy.py`, `tests/test_mean_reversion_rsi_filter.py`
- `tests/test_volume_spike_strategy.py`, `tests/test_volume_filter.py`, `tests/test_volatility_breakout.py`
- `tests/test_consensus_strategy.py`, `tests/test_consensus_enhanced.py`, `tests/test_weighted_consensus.py`
- `tests/test_session11_wave*.py`, `tests/test_session12_wave*.py`
- `tests/test_pyupbit_client.py`, `tests/test_data_clients.py`, `tests/test_candle_cache.py`

**명시적 제외:**
- 백테스트/walk-forward/grid: `test_backtest_*`, `test_walk_forward*`, `test_grid_*`
- GPU: `test_gpu_*`, `test_extended_alpha`
- 리포트/대시보드/알림: `test_*_report*`, `test_dashboard`, `test_telegram*`, `test_*pnl*`, `test_operator_*`, `test_drift_report`, `test_research_summary_report`, `test_gate_progress_report`, `test_performance_report`, `test_strategy_perf_report`, `test_offline_strategy_report`, `test_automated_reporting`, `test_daily_report`, `test_roi_report`, `test_regime_report`, `test_strategy_report`
- 보조/실험: `test_calibration`, `test_correlation*`(단 `_guard` 제외), `test_compound_simulator`, `test_cli*`, `test_apply_params`, `test_auto_tune`, `test_recent_strategy_optimizer`, `test_portfolio_*`, `test_promotion_gate`, `test_edge_*`, `test_rolling_correlation`, `test_kimchi_premium`, `test_funding_rate_strategy`, `test_obi_strategy`, `test_micro_*`, `test_ml_regime`, `test_sortino_and_mcl`, `test_stage1_contract`, `test_verdict_engine`, `test_snapshot_cli`, `test_structured_logger`, `test_file_logging`, `test_paper_trading_operations`, `test_execution_quality`, `test_adaptive_*`, `test_session11_features`, `test_restart_daemon_script`, `test_equity_curve_export`, `test_pnl_snapshot_store`, `test_macro_memo`

화이트리스트는 시작점이며, 첫 PR에서 실제로 돌려보고 깨지는 파일은 즉시 제외한다.

## 4. 의존성 변경

**`pyproject.toml`**: `duckdb`를 메인 의존성에 추가.
- 이유: `test_runtime.py`, `test_multi_symbol.py`, `test_paper_trading_operations.py` 등 매매 코어가 storage 레이어에서 duckdb를 import. 운영 환경에서도 필요.

## 5. 실패 처리 & 점진 정착

| 무엇 | 처리 |
|---|---|
| `ruff check` 실패 | 반드시 fix (`ruff check --fix`) |
| `mypy src/` 실패 | `continue-on-error: true` — 경고만 |
| `pytest` 일부 실패 | 화이트리스트에서 제외 + **`docs/tech-debt.md`에 한 줄 등록 의무** (파일명, 사유, 복구 기한) |
| 추가 import 에러 | 같은 처리 — 제외 + tech-debt 등록 |

**품질 하한선:**
- 1차 PR에서 **제외하는 테스트 파일 수가 10개 초과**하면 작업 중단하고 사용자에게 확인. 화이트리스트 자체가 잘못 잡힌 신호.
- 한번 제외한 테스트는 반드시 `tech-debt.md`에 등록 — 회귀 은닉 방지.

**1차 PR 성공 기준:**
- ✅ ruff green
- ✅ mypy 실행됨 (red여도 통과)
- ✅ pytest green (화이트리스트)
- ✅ master 머지

**점진 정착 (별도 사이클):**
1. 제외된 테스트 복구
2. mypy strict 통과 → `continue-on-error` 제거
3. 테스트 디렉토리 재구조화 (`tests/core/`, `tests/research/`)
4. CD (Lightsail 자동 배포)

## 6. 보안 & 운영 메모

- **Secrets 미사용** — 1차 CI는 외부 자격증명 0. Upbit/Telegram/macro API 키는 사용 안 함.
- **Permissions** — `contents: read`만 부여. write 권한 없음.
- **Action SHA pinning** — 1차에는 적용 안 함 (1인 프로젝트, Dependabot 없으면 유지보수 부담). 추후 보안 강화 사이클에서 검토.
- **타임아웃** — job-level `timeout-minutes: 10` 으로 폭주 방지.
- **동시 실행** — `concurrency` 그룹으로 같은 ref 중복 실행 자동 취소.

## 7. 작업 순서 & 산출물

**산출물:**
1. `.github/workflows/ci.yml` (신규)
2. `pyproject.toml` (`duckdb` 추가)
3. 본 디자인 문서

**순서:**
1. 디자인 문서 작성 & 커밋 (브랜치 `feature/ci-setup`)
2. 로컬 검증: `pip install duckdb` → `ruff check` → `pytest <whitelist>`
3. `.github/workflows/ci.yml` 작성
4. `pyproject.toml` 수정
5. 로컬 재검증
6. 커밋 → push → PR 생성
7. CI 실행 결과 확인 → red면 화이트리스트 조정 → green
8. Codex 리뷰 (`/codex:review`)
9. 리뷰 반영 후 master 머지
