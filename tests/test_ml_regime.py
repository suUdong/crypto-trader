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
    return pd.DataFrame({
        "close": c, "open": c, "high": c + 100, "low": c - 100,
        "volume": np.ones(n) * 1000
    }, index=idx)

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
