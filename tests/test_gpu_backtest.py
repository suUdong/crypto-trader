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
    from backtest_alpha_filter import compute_alpha_series, compute_alpha_series_vectorized
    df = _make_df(200, seed=1)
    btc = _make_df(200, seed=2)
    original = compute_alpha_series(df, btc, lookback=12)
    vectorized = compute_alpha_series_vectorized(df, btc, lookback=12)
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
