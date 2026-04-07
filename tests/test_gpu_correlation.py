import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

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
    for i in range(3):
        base = np.cumsum(np.random.randn(80) * 0.5)
        for j in range(3):
            noise = np.random.randn(80) * 0.05
            all_data[f"G{i}_S{j}"] = pd.DataFrame({"close": 100 + base + noise})
    result = compute_correlation_matrix(all_data, window=30)
    assert "leaders" in result
    assert isinstance(result["leaders"], list)
