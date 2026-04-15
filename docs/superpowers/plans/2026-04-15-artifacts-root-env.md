# CT_ARTIFACTS_ROOT Env Prefix Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 환경변수 `CT_ARTIFACTS_ROOT` 하나로 RuntimeConfig의 `artifacts/` prefix 경로를 일괄 치환하여, 동일한 daemon.toml을 로컬/서버에서 사용 가능하게 한다.

**Architecture:** `load_config()` 끝에서 `RuntimeConfig`을 `dataclasses.replace()`로 복사하면서 `_path` 접미사 필드의 `"artifacts/"` prefix를 치환하는 `_resolve_artifacts_root()` 순수 함수 추가. 환경변수 미설정 시 원본 그대로 반환.

**Tech Stack:** Python 3.12, dataclasses

---

## File Structure

| File | Responsibility |
|---|---|
| `src/crypto_trader/config.py` | `_resolve_artifacts_root()` 함수 추가, `load_config()`에서 호출 |
| `tests/test_config.py` | 테스트 3건: 미설정 기본값, 설정 시 치환, 절대경로 스킵 |

---

### Task 1: 테스트 작성

**Files:**
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`의 `ConfigLoadTests` 클래스 끝에 추가:

```python
def test_artifacts_root_not_set_keeps_defaults(self) -> None:
    config = load_config(ROOT / "config" / "example.toml", {})
    self.assertEqual(
        config.runtime.kill_switch_path, "artifacts/kill-switch.json"
    )
    self.assertEqual(
        config.runtime.paper_trade_journal_path, "artifacts/paper-trades.jsonl"
    )

def test_artifacts_root_overrides_prefix(self) -> None:
    config = load_config(
        ROOT / "config" / "example.toml",
        {"CT_ARTIFACTS_ROOT": "/var/lib/crypto-trader/artifacts"},
    )
    self.assertEqual(
        config.runtime.kill_switch_path,
        "/var/lib/crypto-trader/artifacts/kill-switch.json",
    )
    self.assertEqual(
        config.runtime.paper_trade_journal_path,
        "/var/lib/crypto-trader/artifacts/paper-trades.jsonl",
    )
    self.assertEqual(
        config.runtime.position_snapshot_path,
        "/var/lib/crypto-trader/artifacts/positions.json",
    )
    # trailing slash in env value should work the same
    config2 = load_config(
        ROOT / "config" / "example.toml",
        {"CT_ARTIFACTS_ROOT": "/var/lib/crypto-trader/artifacts/"},
    )
    self.assertEqual(
        config2.runtime.kill_switch_path,
        "/var/lib/crypto-trader/artifacts/kill-switch.json",
    )

def test_artifacts_root_skips_absolute_and_empty(self) -> None:
    config = load_config(
        ROOT / "config" / "example.toml",
        {
            "CT_ARTIFACTS_ROOT": "/srv/data",
            "CT_KILL_SWITCH_PATH": "/custom/kill.json",
        },
    )
    # absolute path set via env — should NOT be rewritten
    self.assertEqual(config.runtime.kill_switch_path, "/custom/kill.json")
    # empty string stays empty
    self.assertEqual(config.runtime.paper_trade_sqlite_path, "")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_config.py::ConfigLoadTests::test_artifacts_root_overrides_prefix -xvs
```

Expected: FAIL — `"artifacts/kill-switch.json"` != `"/var/lib/crypto-trader/artifacts/kill-switch.json"`

- [ ] **Step 3: Commit test**

```bash
git add tests/test_config.py
git commit -m "test(config): add CT_ARTIFACTS_ROOT override tests (red)"
```

---

### Task 2: 구현

**Files:**
- Modify: `src/crypto_trader/config.py`

- [ ] **Step 1: Add `_resolve_artifacts_root()` function**

`_read_value()` 함수 바로 위 (line ~1006 부근)에 추가:

```python
_ARTIFACTS_PREFIX = "artifacts/"


def _resolve_artifacts_root(
    runtime: RuntimeConfig, environ: dict[str, str]
) -> RuntimeConfig:
    """Replace ``artifacts/`` prefix in path fields with *CT_ARTIFACTS_ROOT*."""
    root = environ.get("CT_ARTIFACTS_ROOT")
    if not root:
        return runtime
    root = root.rstrip("/")
    overrides: dict[str, str] = {}
    for field_name in RuntimeConfig.__dataclass_fields__:
        if not field_name.endswith("_path"):
            continue
        value = getattr(runtime, field_name)
        if not value or value.startswith("/"):
            continue
        if value.startswith(_ARTIFACTS_PREFIX):
            overrides[field_name] = root + "/" + value[len(_ARTIFACTS_PREFIX) :]
    if not overrides:
        return runtime
    return replace(runtime, **overrides)
```

- [ ] **Step 2: Ensure `replace` is imported**

`config.py` 상단 import 확인. 이미 `from dataclasses import dataclass, field, replace` 가 있는지 확인하고, `replace`가 없으면 추가.

```bash
grep "from dataclasses import" src/crypto_trader/config.py
```

`replace`가 이미 import 목록에 있으면 스킵. 없으면 import에 추가.

- [ ] **Step 3: Call from `load_config()`**

`load_config()` 함수 내, line 988 `runtime=runtime,` 를 변경:

기존:
```python
    app_config = AppConfig(
        trading=trading,
        strategy=strategy,
        regime=regime,
        drift=drift,
        risk=risk,
        backtest=backtest,
        telegram=telegram,
        runtime=runtime,
```

변경:
```python
    app_config = AppConfig(
        trading=trading,
        strategy=strategy,
        regime=regime,
        drift=drift,
        risk=risk,
        backtest=backtest,
        telegram=telegram,
        runtime=_resolve_artifacts_root(runtime, env),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_config.py -xvs
```

Expected: ALL PASS (기존 테스트 + 신규 3건)

- [ ] **Step 5: Run full checks**

```bash
ruff check src/crypto_trader/config.py tests/test_config.py
mypy src/crypto_trader/config.py
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/crypto_trader/config.py tests/test_config.py
git commit -m "feat(config): add CT_ARTIFACTS_ROOT env prefix override for Lightsail deploy"
```
