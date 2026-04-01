import pytest
import torch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_compute_batch_gpu_has_extended_columns():
    import pandas as pd
    import numpy as np
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
