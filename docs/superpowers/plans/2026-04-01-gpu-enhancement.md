# GPU Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize RTX 3080 utilization to improve alpha signal quality, backtest speed, and regime detection accuracy.

**Architecture:** Shared GPU feature library → extended feature alpha → fully vectorized backtest → correlation matrix rotation detection → ML regime classifier → macro bonus integration.

**Tech Stack:** PyTorch 2.x (CUDA), pandas, numpy, sklearn, pyupbit, Python 3.12+

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `scripts/gpu_features.py` | **Create** | Shared GPU indicator library (RSI, MACD, ATR, OBV, BB) |
| `scripts/autonomous_lab_loop.py` | **Modify** | Use extended features, add correlation output, add macro bonus |
| `scripts/backtest_alpha_filter.py` | **Modify** | Replace per-symbol time loop with full GPU unfold parallelization |
| `scripts/gpu_correlation.py` | **Create** | Correlation matrix + rotation detection (standalone + integrated) |
| `scripts/ml_regime_detector.py` | **Create** | Train/predict BTC regime with sklearn + save model |
| `src/crypto_trader/strategy/alpha_calibrator.py` | **Modify** | Add extended feature weights to `AlphaCalibration` |
| `artifacts/correlation-matrix.json` | **Output** | Written by lab loop each cycle |
| `artifacts/ml-regime-model.pkl` | **Output** | Trained regime classifier |

---

## Phase 1: Short-Term (Tasks 1–4)

### Task 1: GPU Feature Library

**Files:**
- Create: `scripts/gpu_features.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gpu_features.py
import torch
import pytest
import pandas as pd
import numpy as np

def _make_df(n=100):
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    open_ = close + np.random.randn(n) * 0.2
    high  = np.maximum(close, open_) + np.abs(np.random.randn(n) * 0.3)
    low   = np.minimum(close, open_) - np.abs(np.random.randn(n) * 0.3)
    vol   = np.abs(np.random.randn(n) * 1000 + 5000)
    return pd.DataFrame({"close": close, "open": open_, "high": high, "low": low, "volume": vol})

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_compute_gpu_features_shape():
    from scripts.gpu_features import compute_gpu_features
    n_sym, T = 5, 100
    closes = torch.rand(n_sym, T, device="cuda")
    opens  = torch.rand(n_sym, T, device="cuda")
    highs  = closes + torch.rand(n_sym, T, device="cuda") * 0.1
    lows   = closes - torch.rand(n_sym, T, device="cuda") * 0.1
    vols   = torch.rand(n_sym, T, device="cuda") * 1000
    feats = compute_gpu_features(closes, opens, highs, lows, vols)
    for key in ["rsi", "macd", "atr_norm", "obv_slope", "bb_width", "bb_pos"]:
        assert key in feats, f"missing feature: {key}"
        assert feats[key].shape == (n_sym,), f"{key} shape wrong: {feats[key].shape}"

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_rsi_range():
    from scripts.gpu_features import compute_gpu_features
    n_sym, T = 3, 60
    closes = torch.rand(n_sym, T, device="cuda") * 100 + 50
    feats = compute_gpu_features(closes, closes, closes, closes, torch.ones(n_sym, T, device="cuda"))
    assert (feats["rsi"] >= 0).all() and (feats["rsi"] <= 100).all()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source .venv/bin/activate
pytest tests/test_gpu_features.py -v
```
Expected: `ImportError: cannot import name 'compute_gpu_features'`

- [ ] **Step 3: Create `scripts/gpu_features.py`**

```python
"""
GPU Feature Library — shared indicator computation for lab loop and backtest.
All functions accept (n_symbols, time) CUDA tensors and return dict[str, Tensor(n_symbols,)].
"""
from __future__ import annotations
import torch


def compute_gpu_features(
    closes_mat: torch.Tensor,   # (n, T)
    opens_mat: torch.Tensor,    # (n, T)
    highs_mat: torch.Tensor,    # (n, T)
    lows_mat: torch.Tensor,     # (n, T)
    vols_mat: torch.Tensor,     # (n, T)
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    atr_period: int = 14,
    obv_window: int = 12,
    bb_period: int = 20,
) -> dict[str, torch.Tensor]:
    """
    Compute RSI, MACD, ATR, OBV slope, Bollinger Band width/position for all symbols at once.
    Returns dict of tensors, each shape (n_symbols,).
    """
    n, T = closes_mat.shape

    # ── RSI ──────────────────────────────────────────────────────────────────
    diff = closes_mat[:, 1:] - closes_mat[:, :-1]          # (n, T-1)
    gains  = diff.clamp(min=0)
    losses = (-diff).clamp(min=0)
    avg_gain = gains[:, -rsi_period:].mean(dim=1).clamp(min=1e-9)
    avg_loss = losses[:, -rsi_period:].mean(dim=1).clamp(min=1e-9)
    rsi = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)     # (n,)

    # ── MACD histogram (SMA approximation) ───────────────────────────────────
    fast_ma = closes_mat[:, -macd_fast:].mean(dim=1)       # (n,)
    slow_ma = closes_mat[:, -macd_slow:].mean(dim=1)       # (n,)
    macd = fast_ma - slow_ma                               # (n,)

    # ── ATR (normalized by close) ─────────────────────────────────────────────
    prev_close = closes_mat[:, :-1]                        # (n, T-1)
    tr_hl  = highs_mat[:, 1:] - lows_mat[:, 1:]
    tr_hpc = (highs_mat[:, 1:] - prev_close).abs()
    tr_lpc = (lows_mat[:, 1:] - prev_close).abs()
    true_range = torch.stack([tr_hl, tr_hpc, tr_lpc], dim=2).max(dim=2).values  # (n, T-1)
    atr = true_range[:, -atr_period:].mean(dim=1)          # (n,)
    atr_norm = atr / closes_mat[:, -1].clamp(min=1e-9)     # normalized ATR (n,)

    # ── OBV slope (normalized) ────────────────────────────────────────────────
    obv_dir = torch.where(
        closes_mat[:, 1:] >= closes_mat[:, :-1],
        torch.ones_like(vols_mat[:, 1:]),
        torch.full_like(vols_mat[:, 1:], -1.0),
    )
    obv = (vols_mat[:, 1:] * obv_dir).cumsum(dim=1)        # (n, T-1)
    vol_mean = vols_mat.mean(dim=1).clamp(min=1e-9)
    obv_slope = (obv[:, -1] - obv[:, -obv_window]) / vol_mean  # (n,)

    # ── Bollinger Band width + position ──────────────────────────────────────
    bb_window = closes_mat[:, -bb_period:]                  # (n, bb_period)
    bb_ma  = bb_window.mean(dim=1)                          # (n,)
    bb_std = bb_window.std(dim=1).clamp(min=1e-9)          # (n,)
    bb_width = 2.0 * bb_std / bb_ma.clamp(min=1e-9)        # (n,)
    bb_pos = (closes_mat[:, -1] - (bb_ma - bb_std)) / (2.0 * bb_std)  # 0-1 (n,)

    return {
        "rsi":      rsi,
        "macd":     macd,
        "atr_norm": atr_norm,
        "obv_slope": obv_slope,
        "bb_width": bb_width,
        "bb_pos":   bb_pos,
    }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_gpu_features.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/gpu_features.py tests/test_gpu_features.py
git commit -m "feat: add GPU feature library (RSI, MACD, ATR, OBV, BB)"
```

---

### Task 2: Extend Alpha with New Features

**Files:**
- Modify: `scripts/autonomous_lab_loop.py:50-127`
- Modify: `src/crypto_trader/strategy/alpha_calibrator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_extended_alpha.py
import pytest
import torch

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_compute_batch_gpu_has_extended_columns():
    """compute_batch_gpu must return RSI_z, MACD_z, ATR_z, OBV_z, BB_z columns."""
    import pandas as pd
    import numpy as np
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

    # Build minimal fake data
    np.random.seed(1)
    def make_df(n=60):
        c = 100 + np.cumsum(np.random.randn(n) * 0.5)
        o = c + np.random.randn(n) * 0.1
        h = np.maximum(c, o) + 0.2
        l = np.minimum(c, o) - 0.2
        v = np.abs(np.random.randn(n) * 1000 + 3000)
        return pd.DataFrame({"close": c, "open": o, "high": h, "low": l, "volume": v})

    all_data = {f"SYM{i}": make_df() for i in range(5)}
    btc_df = make_df()

    from autonomous_lab_loop import compute_batch_gpu
    df = compute_batch_gpu(all_data, btc_df)
    for col in ["RSI_z", "MACD_z", "ATR_z", "OBV_z", "BB_z"]:
        assert col in df.columns, f"missing column: {col}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_extended_alpha.py -v
```
Expected: `AssertionError: missing column: RSI_z`

- [ ] **Step 3: Extend `AlphaCalibration` in `src/crypto_trader/strategy/alpha_calibrator.py`**

Add fields after `cvd_weight`:

```python
@dataclass
class AlphaCalibration:
    rs_weight: float = 0.4
    acc_weight: float = 0.3
    cvd_weight: float = 0.3
    # Extended feature weights (sum with above should = 1.0)
    rsi_weight: float = 0.0
    macd_weight: float = 0.0
    atr_weight: float = 0.0
    obv_weight: float = 0.0
    bb_weight: float = 0.0
    threshold: float = 1.0
    verdict: str = "unknown"
    avg_edge_6b_pct: float = 0.0
    avg_corr_6b: float = 0.0
    sample_size: int = 0
    updated_at: str = ""
```

Update `load_calibration` to parse new fields:

```python
cal = AlphaCalibration(
    rs_weight=float(data.get("rs_weight", 0.4)),
    acc_weight=float(data.get("acc_weight", 0.3)),
    cvd_weight=float(data.get("cvd_weight", 0.3)),
    rsi_weight=float(data.get("rsi_weight", 0.0)),
    macd_weight=float(data.get("macd_weight", 0.0)),
    atr_weight=float(data.get("atr_weight", 0.0)),
    obv_weight=float(data.get("obv_weight", 0.0)),
    bb_weight=float(data.get("bb_weight", 0.0)),
    threshold=float(data.get("threshold", 1.0)),
    verdict=str(data.get("verdict", "unknown")),
    avg_edge_6b_pct=float(data.get("avg_edge_6b_pct", 0.0)),
    avg_corr_6b=float(data.get("avg_corr_6b", 0.0)),
    sample_size=int(data.get("sample_size", 0)),
    updated_at=str(data.get("updated_at", "")),
)
```

- [ ] **Step 4: Extend `compute_batch_gpu` in `scripts/autonomous_lab_loop.py`**

Add import at top: `from gpu_features import compute_gpu_features`

Replace the z-score + alpha block (after CVD slope computation, line ~101):

```python
    # ── Extended features ─────────────────────────────────────────────────
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gpu_features import compute_gpu_features
    ext = compute_gpu_features(closes_mat, opens_mat, highs_mat, lows_mat, vols_mat)

    # ── z-score 정규화 ────────────────────────────────────────────────────
    def zscore(t: torch.Tensor) -> torch.Tensor:
        return (t - t.mean()) / (t.std() + 1e-9)

    rs_z    = zscore(rs)
    acc_z   = zscore(acc)
    cvd_z   = zscore(cvd_slope)
    rsi_z   = zscore(ext["rsi"])
    macd_z  = zscore(ext["macd"])
    atr_z   = zscore(ext["atr_norm"])
    obv_z   = zscore(ext["obv_slope"])
    bb_z    = zscore(ext["bb_pos"])

    # calibration weights
    rs_w   = cal.rs_weight   if cal else 0.4
    acc_w  = cal.acc_weight  if cal else 0.3
    cvd_w  = cal.cvd_weight  if cal else 0.3
    rsi_w  = cal.rsi_weight  if cal else 0.0
    macd_w = cal.macd_weight if cal else 0.0
    atr_w  = cal.atr_weight  if cal else 0.0
    obv_w  = cal.obv_weight  if cal else 0.0
    bb_w   = cal.bb_weight   if cal else 0.0

    alpha = (
        rs_z * rs_w + acc_z * acc_w + cvd_z * cvd_w
        + rsi_z * rsi_w + macd_z * macd_w
        + atr_z * atr_w + obv_z * obv_w + bb_z * bb_w
    )

    df_out = pd.DataFrame({
        "Symbol":  symbols,
        "Alpha":   alpha.cpu().numpy().round(4),
        "RS":      rs.cpu().numpy().round(4),
        "Acc":     acc.cpu().numpy().round(4),
        "CVD":     cvd_slope.cpu().numpy().round(4),
        "RS_z":    rs_z.cpu().numpy().round(4),
        "Acc_z":   acc_z.cpu().numpy().round(4),
        "CVD_z":   cvd_z.cpu().numpy().round(4),
        "RSI_z":   rsi_z.cpu().numpy().round(4),
        "MACD_z":  macd_z.cpu().numpy().round(4),
        "ATR_z":   atr_z.cpu().numpy().round(4),
        "OBV_z":   obv_z.cpu().numpy().round(4),
        "BB_z":    bb_z.cpu().numpy().round(4),
    }).sort_values("Alpha", ascending=False)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_extended_alpha.py tests/test_gpu_features.py -v
```
Expected: all PASS

- [ ] **Step 6: Smoke test lab loop feature computation**

```bash
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
import pyupbit, torch
from autonomous_lab_loop import compute_batch_gpu, fetch_all_parallel, INTERVAL, COUNT
symbols = pyupbit.get_tickers(fiat='KRW')[:10]
btc_df = pyupbit.get_ohlcv('KRW-BTC', interval=INTERVAL, count=COUNT)
data = fetch_all_parallel(symbols)
df = compute_batch_gpu(data, btc_df)
print(df.columns.tolist())
print(df.head(3))
"
```
Expected: columns include RSI_z, MACD_z, ATR_z, OBV_z, BB_z; no errors.

- [ ] **Step 7: Commit**

```bash
git add scripts/autonomous_lab_loop.py src/crypto_trader/strategy/alpha_calibrator.py
git commit -m "feat: extend alpha with RSI, MACD, ATR, OBV, BB GPU features"
```

---

### Task 3: Full GPU-Parallel Backtest (unfold trick)

**Files:**
- Modify: `scripts/backtest_alpha_filter.py:72-132` (`compute_alpha_series`)

**Key idea**: Replace Python time-step loop with `torch.Tensor.unfold` to create sliding windows → fully vectorized over all symbols AND all time steps simultaneously.

- [ ] **Step 1: Write failing test**

```python
# tests/test_gpu_backtest.py
import pytest
import torch
import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

def _make_df(n=200, seed=0):
    np.random.seed(seed)
    c = 100 + np.cumsum(np.random.randn(n) * 0.5)
    o = c + np.random.randn(n) * 0.1
    h = np.maximum(c, o) + 0.2
    l = np.minimum(c, o) - 0.2
    v = np.abs(np.random.randn(n) * 1000 + 3000)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame({"close": c, "open": o, "high": h, "low": l, "volume": v}, index=idx)

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_compute_alpha_series_vectorized_matches_original():
    """Vectorized result must be close to the original loop-based result."""
    from backtest_alpha_filter import compute_alpha_series, compute_alpha_series_vectorized
    df = _make_df(200, seed=1)
    btc = _make_df(200, seed=2)
    original = compute_alpha_series(df, btc, lookback=12)
    vectorized = compute_alpha_series_vectorized(df, btc, lookback=12)
    # alpha values should match within floating point tolerance
    diff = (original["alpha"] - vectorized["alpha"]).abs().mean()
    assert diff < 0.01, f"mean abs diff too large: {diff}"

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_vectorized_is_faster():
    import time
    from backtest_alpha_filter import compute_alpha_series, compute_alpha_series_vectorized
    df = _make_df(500, seed=3)
    btc = _make_df(500, seed=4)
    t0 = time.time(); compute_alpha_series(df, btc, lookback=30); t1 = time.time()
    t2 = time.time(); compute_alpha_series_vectorized(df, btc, lookback=30); t3 = time.time()
    assert (t3 - t2) < (t1 - t0), "vectorized should be faster than loop"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_gpu_backtest.py -v
```
Expected: `ImportError: cannot import name 'compute_alpha_series_vectorized'`

- [ ] **Step 3: Add `compute_alpha_series_vectorized` to `scripts/backtest_alpha_filter.py`**

Add after `compute_alpha_series` function (around line 133):

```python
def compute_alpha_series_vectorized(
    df: pd.DataFrame,
    btc_df: pd.DataFrame,
    lookback: int = LOOKBACK,
    recent_w: int = RECENT_W,
) -> pd.DataFrame:
    """
    Fully GPU-vectorized alpha series — uses unfold to eliminate Python time loop.
    ~10-50x faster than compute_alpha_series for long series.
    Returns same schema as compute_alpha_series.
    """
    common_len = min(len(df), len(btc_df))
    df = df.iloc[-common_len:]
    btc_df = btc_df.iloc[-common_len:]

    closes  = torch.tensor(df['close'].values,     device='cuda', dtype=torch.float32)
    opens   = torch.tensor(df['open'].values,      device='cuda', dtype=torch.float32)
    highs   = torch.tensor(df['high'].values,      device='cuda', dtype=torch.float32)
    lows    = torch.tensor(df['low'].values,       device='cuda', dtype=torch.float32)
    vols    = torch.tensor(df['volume'].values,    device='cuda', dtype=torch.float32)
    btc_c   = torch.tensor(btc_df['close'].values, device='cuda', dtype=torch.float32)

    n_windows = common_len - lookback
    if n_windows <= 0:
        return pd.DataFrame()

    # ── sliding windows via unfold: (n_windows, lookback) ────────────────
    c_w   = closes.unfold(0, lookback, 1)   # (n_windows, lookback)
    o_w   = opens.unfold(0, lookback, 1)
    h_w   = highs.unfold(0, lookback, 1)
    l_w   = lows.unfold(0, lookback, 1)
    v_w   = vols.unfold(0, lookback, 1)
    btc_w = btc_c.unfold(0, lookback, 1)

    # ── RS (n_windows,) ──────────────────────────────────────────────────
    sym_norm = c_w / c_w[:, 0:1].clamp(min=1e-9)
    btc_norm = btc_w / btc_w[:, 0:1].clamp(min=1e-9)
    rs = (sym_norm / btc_norm)[:, -1]

    # ── Acc (n_windows,) ─────────────────────────────────────────────────
    rng  = (h_w - l_w).clamp(min=1e-9)
    vpin = (c_w - o_w).abs() / rng
    acc  = vpin[:, -recent_w:].mean(dim=1) / vpin[:, :-recent_w].mean(dim=1).clamp(min=1e-9)

    # ── CVD slope (n_windows,) ────────────────────────────────────────────
    direction = torch.where(c_w >= o_w, torch.ones_like(v_w), torch.full_like(v_w, -1.0))
    cvd = (v_w * direction).cumsum(dim=1)
    vol_mean = v_w.mean(dim=1).clamp(min=1e-9)
    cvd_slope = (cvd[:, -1] - cvd[:, -recent_w]) / vol_mean

    # ── z-score (time-series normalization) ──────────────────────────────
    def zs(t: torch.Tensor) -> torch.Tensor:
        return (t - t.mean()) / (t.std() + 1e-9)

    rs_z, acc_z, cvd_z = zs(rs), zs(acc), zs(cvd_slope)
    alpha = rs_z * 0.4 + acc_z * 0.3 + cvd_z * 0.3

    idx = df.index[lookback:]
    result = pd.DataFrame({
        "rs":    rs.cpu().numpy(),
        "acc":   acc.cpu().numpy(),
        "cvd":   cvd_slope.cpu().numpy(),
        "rs_z":  rs_z.cpu().numpy(),
        "acc_z": acc_z.cpu().numpy(),
        "cvd_z": cvd_z.cpu().numpy(),
        "alpha": alpha.cpu().numpy(),
    }, index=idx)
    return result
```

- [ ] **Step 4: Update `main()` in `backtest_alpha_filter.py` to use vectorized version**

In `main()`, replace the call `compute_alpha_series(df, btc_df)` with:

```python
alpha_df = compute_alpha_series_vectorized(df, btc_df)
```

Also update LOOKBACK grid search loop (same replacement).

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_gpu_backtest.py -v
```
Expected: all PASS (vectorized matches original, and is faster)

- [ ] **Step 6: Benchmark**

```bash
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
import time, pyupbit
from backtest_alpha_filter import compute_alpha_series, compute_alpha_series_vectorized, INTERVAL, COUNT
btc = pyupbit.get_ohlcv('KRW-BTC', interval=INTERVAL, count=COUNT)
df  = pyupbit.get_ohlcv('KRW-ETH', interval=INTERVAL, count=COUNT)
t0=time.time(); compute_alpha_series(df, btc); t1=time.time()
t2=time.time(); compute_alpha_series_vectorized(df, btc); t3=time.time()
print(f'loop: {t1-t0:.3f}s  vectorized: {t3-t2:.3f}s  speedup: {(t1-t0)/(t3-t2):.1f}x')
"
```
Expected: vectorized ≥ 5x faster.

- [ ] **Step 7: Commit**

```bash
git add scripts/backtest_alpha_filter.py tests/test_gpu_backtest.py
git commit -m "perf: GPU-vectorized backtest via unfold, eliminate Python time loop"
```

---

### Task 4: Correlation Matrix + Rotation Detection

**Files:**
- Create: `scripts/gpu_correlation.py`
- Modify: `scripts/autonomous_lab_loop.py` (add correlation call in `main()`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_gpu_correlation.py
import pytest
import torch
import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_correlation_matrix_shape():
    from gpu_correlation import compute_correlation_matrix
    np.random.seed(0)
    n_sym, T = 10, 100
    all_data = {}
    for i in range(n_sym):
        c = 100 + np.cumsum(np.random.randn(T) * 0.5)
        all_data[f"SYM{i}"] = pd.DataFrame({"close": c})
    result = compute_correlation_matrix(all_data, window=30)
    assert "corr_matrix" in result
    assert result["corr_matrix"].shape == (n_sym, n_sym)

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_rotation_clusters():
    from gpu_correlation import compute_correlation_matrix
    np.random.seed(1)
    all_data = {}
    # 3 clusters of 3 correlated symbols
    for i in range(3):
        base = np.cumsum(np.random.randn(80) * 0.5)
        for j in range(3):
            noise = np.random.randn(80) * 0.05
            all_data[f"G{i}_S{j}"] = pd.DataFrame({"close": 100 + base + noise})
    result = compute_correlation_matrix(all_data, window=30)
    assert "leaders" in result
    assert isinstance(result["leaders"], list)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_gpu_correlation.py -v
```
Expected: `ImportError: cannot import name 'compute_correlation_matrix'`

- [ ] **Step 3: Create `scripts/gpu_correlation.py`**

```python
"""
GPU Correlation Matrix — computes rolling return correlations across all symbols.
Detects rotation leaders (symbols with highest avg outgoing correlation).
"""
from __future__ import annotations
import torch
import numpy as np
import pandas as pd


def compute_correlation_matrix(
    all_data: dict[str, pd.DataFrame],
    window: int = 30,
) -> dict:
    """
    Compute pairwise return correlation matrix over last `window` bars.

    Returns:
        corr_matrix: np.ndarray (n, n)
        symbols: list[str]
        leaders: list[str] — top 5 symbols by avg absolute correlation (rotation hubs)
        avg_corr: float — mean off-diagonal absolute correlation (market coherence)
    """
    symbols = list(all_data.keys())
    n = len(symbols)
    if n < 2:
        return {"corr_matrix": np.eye(1), "symbols": symbols, "leaders": [], "avg_corr": 0.0}

    common_len = min(len(df) for df in all_data.values())
    w = min(window, common_len - 1)

    # Build returns matrix (n, w) on GPU
    ret_mat = torch.zeros(n, w, device="cuda", dtype=torch.float32)
    for i, sym in enumerate(symbols):
        closes = torch.tensor(
            all_data[sym]["close"].values[-common_len:], device="cuda", dtype=torch.float32
        )
        rets = closes[1:] / closes[:-1] - 1.0
        ret_mat[i] = rets[-w:]

    # Pearson correlation: normalize rows, then dot product
    mean = ret_mat.mean(dim=1, keepdim=True)
    std  = ret_mat.std(dim=1, keepdim=True).clamp(min=1e-9)
    ret_norm = (ret_mat - mean) / std        # (n, w)
    corr = (ret_norm @ ret_norm.T) / w       # (n, n)

    corr_np = corr.cpu().numpy()
    np.fill_diagonal(corr_np, 1.0)

    # Leaders: highest mean absolute off-diagonal correlation
    mask = ~np.eye(n, dtype=bool)
    avg_abs = np.abs(corr_np * mask).sum(axis=1) / (n - 1)
    leader_idx = avg_abs.argsort()[::-1][:5]
    leaders = [symbols[i] for i in leader_idx]

    avg_corr = float(np.abs(corr_np[mask]).mean())

    return {
        "corr_matrix": corr_np,
        "symbols": symbols,
        "leaders": leaders,
        "avg_corr": round(avg_corr, 4),
    }
```

- [ ] **Step 4: Integrate into `autonomous_lab_loop.py` `main()`**

After `prebull_path.write_text(...)` block, add:

```python
            # Correlation matrix (rotation detection)
            try:
                import sys as _sys
                _sys.path.insert(0, str(_project_root / "scripts"))
                from gpu_correlation import compute_correlation_matrix
                corr_result = compute_correlation_matrix(all_data, window=30)
                corr_path = Path("artifacts/correlation-matrix.json")
                import json as _json
                _json.dump({
                    "updated_at": datetime.now().isoformat(),
                    "cycle": cycle,
                    "avg_corr": corr_result["avg_corr"],
                    "leaders": corr_result["leaders"],
                }, corr_path.open("w"), indent=2)
                print(
                    f"[Corr] avg={corr_result['avg_corr']:.3f} "
                    f"leaders={corr_result['leaders'][:3]}"
                )
            except Exception as e:
                print(f"[Corr] skipped: {e}")
```

Note: `all_data` is returned from `fetch_all_parallel` — pass it through to `main()` by refactoring `get_alpha_scan_results` to also return `all_data`:

Change `get_alpha_scan_results` return to `tuple[str, float, dict, dict]` (add `all_data` as 4th element):
```python
    return df_result.head(15).to_string(index=False), cal_threshold, pre_bull_signals, all_data
```

And update the `main()` call:
```python
            scan_data, cal_threshold, pre_bull, all_data = get_alpha_scan_results()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_gpu_correlation.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/gpu_correlation.py scripts/autonomous_lab_loop.py tests/test_gpu_correlation.py
git commit -m "feat: GPU correlation matrix + rotation leader detection in lab loop"
```

---

## Phase 2: Mid-Term (Tasks 5–6)

### Task 5: ML Regime Detector

**Files:**
- Create: `scripts/ml_regime_detector.py`
- Modify: `scripts/backtest_alpha_filter.py` (replace `detect_btc_regime` call)

- [ ] **Step 1: Write failing test**

```python
# tests/test_ml_regime.py
import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

def _make_btc(n=300, seed=0):
    np.random.seed(seed)
    c = 50000 + np.cumsum(np.random.randn(n) * 200)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame({"close": c, "open": c, "high": c + 100, "low": c - 100, "volume": np.ones(n) * 1000}, index=idx)

def test_ml_regime_detector_train_predict():
    from ml_regime_detector import MLRegimeDetector
    btc = _make_btc(300)
    det = MLRegimeDetector()
    det.train(btc)
    regime = det.predict(btc)
    assert isinstance(regime, pd.Series)
    assert set(regime.dropna().unique()).issubset({"bull", "bear", "pre_bull", "post_bull"})
    assert len(regime) == len(btc)

def test_ml_regime_detector_save_load(tmp_path):
    from ml_regime_detector import MLRegimeDetector
    btc = _make_btc(300)
    det = MLRegimeDetector()
    det.train(btc)
    path = tmp_path / "model.pkl"
    det.save(path)
    det2 = MLRegimeDetector.load(path)
    r1 = det.predict(btc)
    r2 = det2.predict(btc)
    assert (r1 == r2).all()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_ml_regime.py -v
```
Expected: `ImportError: cannot import name 'MLRegimeDetector'`

- [ ] **Step 3: Create `scripts/ml_regime_detector.py`**

```python
"""
ML Regime Detector — trains a RandomForest on BTC OHLCV features to classify
market regime as bull/bear/pre_bull/post_bull.
Labels are generated from the rule-based detector (backtest_alpha_filter.detect_btc_regime)
and used as training targets. Model is saved to artifacts/ml-regime-model.pkl.
"""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder


DEFAULT_MODEL_PATH = Path("artifacts/ml-regime-model.pkl")


def _build_features(btc_df: pd.DataFrame, sma_period: int = 20) -> pd.DataFrame:
    """Build feature matrix from BTC OHLCV."""
    c = btc_df["close"]
    sma = c.rolling(sma_period).mean()
    feats = pd.DataFrame(index=btc_df.index)
    feats["close_over_sma"]  = (c / sma.replace(0, np.nan)).fillna(1.0)
    feats["sma_slope_5"]     = sma.pct_change(5).fillna(0)
    feats["sma_slope_10"]    = sma.pct_change(10).fillna(0)
    feats["ret_1"]           = c.pct_change(1).fillna(0)
    feats["ret_6"]           = c.pct_change(6).fillna(0)
    feats["ret_24"]          = c.pct_change(24).fillna(0)
    feats["vol_ratio"]       = (
        btc_df["volume"].rolling(6).mean() /
        btc_df["volume"].rolling(30).mean().replace(0, np.nan)
    ).fillna(1.0)
    feats["hl_range_norm"]   = (
        (btc_df["high"] - btc_df["low"]) / c.replace(0, np.nan)
    ).fillna(0)
    return feats.fillna(0)


class MLRegimeDetector:
    def __init__(self, n_estimators: int = 100, sma_period: int = 20) -> None:
        self.sma_period = sma_period
        self._clf = RandomForestClassifier(
            n_estimators=n_estimators, max_depth=6, random_state=42, n_jobs=-1
        )
        self._le = LabelEncoder()
        self._trained = False

    def train(self, btc_df: pd.DataFrame) -> None:
        """Generate rule-based labels, then train RF on BTC features."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from backtest_alpha_filter import detect_btc_regime

        labels = detect_btc_regime(btc_df, sma_period=self.sma_period)
        feats  = _build_features(btc_df, sma_period=self.sma_period)
        common = feats.index.intersection(labels.index)
        X = feats.loc[common].values
        y = labels.loc[common].values
        # Drop NaN rows
        valid = ~np.isnan(X).any(axis=1)
        X, y = X[valid], y[valid]
        y_enc = self._le.fit_transform(y)
        self._clf.fit(X, y_enc)
        self._trained = True

    def predict(self, btc_df: pd.DataFrame) -> pd.Series:
        """Return pd.Series[str] of regime labels for btc_df index."""
        if not self._trained:
            raise RuntimeError("Model not trained. Call train() first.")
        feats = _build_features(btc_df, sma_period=self.sma_period)
        X = feats.values
        preds = self._clf.predict(X)
        labels = self._le.inverse_transform(preds)
        return pd.Series(labels, index=btc_df.index, dtype=str)

    def save(self, path: Path = DEFAULT_MODEL_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"clf": self._clf, "le": self._le, "sma_period": self.sma_period, "trained": self._trained}, f)

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL_PATH) -> "MLRegimeDetector":
        with Path(path).open("rb") as f:
            data = pickle.load(f)
        det = cls(sma_period=data["sma_period"])
        det._clf = data["clf"]
        det._le  = data["le"]
        det._trained = data["trained"]
        return det


def train_and_save(btc_df: pd.DataFrame, path: Path = DEFAULT_MODEL_PATH) -> MLRegimeDetector:
    det = MLRegimeDetector()
    det.train(btc_df)
    det.save(path)
    print(f"ML regime model saved → {path}")
    return det


if __name__ == "__main__":
    import pyupbit
    btc = pyupbit.get_ohlcv("KRW-BTC", interval="minute240", count=500)
    det = train_and_save(btc)
    regime = det.predict(btc)
    print(regime.value_counts())
```

- [ ] **Step 4: Integrate into `backtest_alpha_filter.py`**

In `main()`, after `btc_regime = detect_btc_regime(btc_df)`, add:

```python
    # Try ML regime detector if model exists
    ml_model_path = Path("artifacts/ml-regime-model.pkl")
    if ml_model_path.exists():
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from ml_regime_detector import MLRegimeDetector
            ml_det = MLRegimeDetector.load(ml_model_path)
            btc_regime = ml_det.predict(btc_df)
            print("Using ML regime detector")
        except Exception as e:
            print(f"ML regime fallback to rule-based: {e}")
    else:
        # Train and save for next run
        try:
            from ml_regime_detector import train_and_save
            train_and_save(btc_df, ml_model_path)
        except Exception:
            pass
```

- [ ] **Step 5: Install sklearn if needed**

```bash
source .venv/bin/activate && pip install scikit-learn
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_ml_regime.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add scripts/ml_regime_detector.py scripts/backtest_alpha_filter.py tests/test_ml_regime.py
git commit -m "feat: ML regime detector (RandomForest on BTC features) with rule-based fallback"
```

---

### Task 6: Macro Bonus Integration into Pre-Bull Score

**Files:**
- Modify: `scripts/autonomous_lab_loop.py` (`get_alpha_scan_results`)

- [ ] **Step 1: Write failing test**

```python
# tests/test_macro_bonus.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

def test_macro_bonus_vix_falling():
    from autonomous_lab_loop import compute_macro_bonus
    payload = {
        "overall_regime": "neutral",
        "overall_confidence": 0.5,
        "layers": {
            "us": {
                "signals": {
                    "vix_trend": "-17.5% (falling)",
                    "dxy_trend": "-0.6% (falling)",
                }
            }
        }
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # vix_falling(0.2) + dxy_falling(0.1)

def test_macro_bonus_expansionary():
    from autonomous_lab_loop import compute_macro_bonus
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.6,
        "layers": {"us": {"signals": {"vix_trend": "stable", "dxy_trend": "stable"}}}
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # expansionary(0.3)

def test_macro_bonus_low_confidence_returns_zero():
    from autonomous_lab_loop import compute_macro_bonus
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.2,  # below 0.3 threshold
        "layers": {"us": {"signals": {"vix_trend": "-20% (falling)", "dxy_trend": "-1% (falling)"}}}
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.0

def test_macro_bonus_server_down():
    from autonomous_lab_loop import compute_macro_bonus
    bonus = compute_macro_bonus(None)
    assert bonus == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_macro_bonus.py -v
```
Expected: `ImportError: cannot import name 'compute_macro_bonus'`

- [ ] **Step 3: Add `compute_macro_bonus` to `scripts/autonomous_lab_loop.py`**

Add after imports, before `fetch_single`:

```python
def _fetch_macro_payload() -> dict | None:
    """Fetch macro regime from macro-intelligence server. Returns None on failure."""
    try:
        from urllib.request import urlopen
        import json as _json
        with urlopen("http://127.0.0.1:8000/regime/current", timeout=3) as resp:
            return _json.loads(resp.read())
    except Exception:
        return None


def compute_macro_bonus(payload: dict | None) -> float:
    """
    Compute macro bonus for pre_bull_score adjustment.
    Returns 0.0 on failure or low confidence.

    Bonuses:
      VIX trend falling  → +0.2
      DXY trend falling  → +0.1
      expansionary regime → +0.3
    Conditions:
      payload must not be None AND overall_confidence >= 0.3
    """
    if payload is None:
        return 0.0
    confidence = float(payload.get("overall_confidence", 0.0))
    if confidence < 0.3:
        return 0.0
    bonus = 0.0
    try:
        us_signals = payload["layers"]["us"]["signals"]
        vix_trend = str(us_signals.get("vix_trend", ""))
        dxy_trend = str(us_signals.get("dxy_trend", ""))
        if "falling" in vix_trend.lower():
            bonus += 0.2
        if "falling" in dxy_trend.lower():
            bonus += 0.1
    except (KeyError, TypeError):
        pass
    if payload.get("overall_regime") == "expansionary":
        bonus += 0.3
    return round(bonus, 3)
```

- [ ] **Step 4: Integrate macro bonus into `get_alpha_scan_results`**

In `get_alpha_scan_results`, after `pre_bull_score = round(...)`, add:

```python
    macro_payload = _fetch_macro_payload()
    macro_bonus = compute_macro_bonus(macro_payload)
    pre_bull_score_adj = round(pre_bull_score + macro_bonus, 3)
```

Update `pre_bull_signals` dict:

```python
    pre_bull_signals = {
        "stealth_acc_count": stealth_acc_count,
        "stealth_acc_ratio": round(stealth_acc_count / max(total_coins, 1), 3),
        "pct_pos_acc": pct_pos_acc,
        "pct_pos_cvd": pct_pos_cvd,
        "pct_weak_rs": pct_weak_rs,
        "pre_bull_score": pre_bull_score,
        "macro_bonus": macro_bonus,
        "pre_bull_score_adj": pre_bull_score_adj,
        "total_coins_scanned": total_coins,
    }
```

Update the print in `main()`:

```python
            print(
                f"[Pre-Bull] score={pre_bull['pre_bull_score']:+.3f} "
                f"macro_bonus={pre_bull['macro_bonus']:+.3f} "
                f"adj={pre_bull['pre_bull_score_adj']:+.3f} "
                f"stealth={pre_bull['stealth_acc_count']}/{pre_bull['total_coins_scanned']}"
            )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_macro_bonus.py -v
```
Expected: all PASS

- [ ] **Step 6: Smoke test**

```bash
source .venv/bin/activate
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from autonomous_lab_loop import _fetch_macro_payload, compute_macro_bonus
p = _fetch_macro_payload()
print('payload ok:', p is not None)
print('bonus:', compute_macro_bonus(p))
"
```
Expected: `payload ok: True`, `bonus: 0.3` (VIX falling + DXY falling)

- [ ] **Step 7: Commit**

```bash
git add scripts/autonomous_lab_loop.py tests/test_macro_bonus.py
git commit -m "feat: macro bonus integration into pre_bull_score (VIX/DXY/regime)"
```

---

## Self-Review

**Spec coverage:**
- ✅ GPU feature expansion (RSI, MACD, ATR, OBV, BB) — Task 1+2
- ✅ Backtest GPU parallelization — Task 3
- ✅ Correlation matrix + rotation detection — Task 4
- ✅ ML regime detector — Task 5
- ✅ Macro bonus integration — Task 6

**Placeholder scan:** None found — all steps have concrete code.

**Type consistency:**
- `compute_gpu_features` returns `dict[str, torch.Tensor]` — used as `ext["rsi"]` etc. ✅
- `compute_alpha_series_vectorized` returns `pd.DataFrame` same schema as original ✅
- `compute_macro_bonus(payload: dict | None) -> float` — test uses `None` and dict ✅
- `get_alpha_scan_results` return type updated to `tuple[str, float, dict, dict]` ✅

**Dependency order:**
- Task 1 (`gpu_features.py`) must complete before Task 2 (lab loop integration)
- Task 3 and 4 are independent of Tasks 1–2
- Task 5 depends on `detect_btc_regime` still existing in `backtest_alpha_filter.py` ✅
- Task 6 is fully independent
