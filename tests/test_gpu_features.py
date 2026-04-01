import torch
import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
    from gpu_features import compute_gpu_features
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
    from gpu_features import compute_gpu_features
    n_sym, T = 3, 60
    closes = torch.rand(n_sym, T, device="cuda") * 100 + 50
    feats = compute_gpu_features(closes, closes, closes, closes, torch.ones(n_sym, T, device="cuda"))
    assert (feats["rsi"] >= 0).all() and (feats["rsi"] <= 100).all()
