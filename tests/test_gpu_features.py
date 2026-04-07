import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


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
