# CT_ARTIFACTS_ROOT Environment Variable Prefix Override

**Date:** 2026-04-15
**Status:** Approved

## Problem

`RuntimeConfig`의 경로 필드 16개가 전부 `"artifacts/"` prefix 하드코딩. 로컬(WSL)과 Lightsail 서버에서 같은 `daemon.toml`을 쓸 수 없음.

## Solution

환경변수 `CT_ARTIFACTS_ROOT` 하나로 `"artifacts/"` prefix를 일괄 치환.

### 동작

1. `load_config()` 시 `CT_ARTIFACTS_ROOT` 환경변수 확인
2. 미설정 → 아무것도 안 함 (기존 `"artifacts/"` 그대로)
3. 설정됨 → `RuntimeConfig`의 모든 `_path` 필드에서 `"artifacts/"` prefix를 `CT_ARTIFACTS_ROOT` 값으로 치환

### 치환 규칙

- trailing slash 유무 무관하게 정규화 (`/var/lib/ct/artifacts/` → `/var/lib/ct/artifacts`)
- `"artifacts/"` prefix인 경우만 치환 대상
- 절대경로(`/`로 시작)는 이미 직접 지정된 것이므로 치환하지 않음
- 빈 문자열(`""`)은 건드리지 않음

### 대상 필드 (RuntimeConfig)

`kill_switch_path`, `healthcheck_path`, `runtime_checkpoint_path`, `backtest_baseline_path`, `regime_report_path`, `drift_calibration_path`, `operator_report_path`, `strategy_run_journal_path`, `paper_trade_journal_path`, `paper_trade_sqlite_path`, `position_snapshot_path`, `daily_performance_path`, `drift_report_path`, `promotion_gate_path`, `daily_memo_path`, `strategy_report_path`, `performance_report_path`

### 비대상

- `MacroConfig.db_path` — 이미 `CT_MACRO_DB_PATH` env 존재
- `RuntimeConfig.log_file_path` — `"artifacts/"` prefix 아님

## File Changes

| File | Action |
|---|---|
| `src/crypto_trader/config.py` | `_resolve_artifacts_root()` 함수 추가 (~15줄), `_build_runtime_config()` 결과에 적용 |
| `tests/test_config.py` | 테스트 2건: 미설정 시 기본값 유지, 설정 시 prefix 치환 |

## Usage

```bash
# 로컬 (WSL) — 변경 없음
crypto-trader run-multi --config config/daemon.toml

# Lightsail
CT_ARTIFACTS_ROOT=/var/lib/crypto-trader/artifacts \
  crypto-trader run-multi --config config/daemon.toml
# → "artifacts/paper-trades.jsonl" → "/var/lib/crypto-trader/artifacts/paper-trades.jsonl"
```
