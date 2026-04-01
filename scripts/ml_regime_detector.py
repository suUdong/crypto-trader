"""
ML Regime Detector — RandomForest classifier trained on BTC OHLCV features.
Labels generated from rule-based detect_btc_regime, used as training targets.
Model saved to artifacts/ml-regime-model.pkl.
"""
from __future__ import annotations
import pickle
import sys
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
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from backtest_alpha_filter import detect_btc_regime

        labels = detect_btc_regime(btc_df, sma_period=self.sma_period)
        feats  = _build_features(btc_df, sma_period=self.sma_period)
        common = feats.index.intersection(labels.index)
        X = feats.loc[common].values
        y = labels.loc[common].values
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
            pickle.dump({
                "clf": self._clf, "le": self._le,
                "sma_period": self.sma_period, "trained": self._trained,
            }, f)

    @classmethod
    def load(cls, path: Path = DEFAULT_MODEL_PATH) -> "MLRegimeDetector":
        with Path(path).open("rb") as f:
            data = pickle.load(f)
        det = cls(sma_period=data["sma_period"])
        det._clf = data["clf"]
        det._le  = data["le"]
        det._trained = data["trained"]
        return det


def train_and_save(btc_df: pd.DataFrame, path: Path = DEFAULT_MODEL_PATH) -> "MLRegimeDetector":
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
