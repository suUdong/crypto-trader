from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from crypto_trader.models import Candle

logger = logging.getLogger(__name__)

class HMMState(IntEnum):
    NOISE = 0
    TREND = 1

@dataclass(slots=True)
class HMMRegimeAnalysis:
    state: HMMState
    confidence: float
    volatility: float

class SimpleHMM:
    """Minimal 2-state Gaussian HMM implementation using NumPy/SciPy."""
    def __init__(self, n_states: int = 2):
        self.n_states = n_states
        self.pi = np.array([0.5, 0.5]) # Initial state distribution
        self.A = np.array([[0.9, 0.1], [0.1, 0.9]]) # Transition matrix
        self.means = np.zeros((n_states, 3)) # Mean of features (returns, vol, vol_z)
        self.stds = np.ones((n_states, 3)) # Std of features
        self.is_trained = False

    def fit(self, X: np.ndarray, n_iter: int = 10):
        """Basic EM algorithm for HMM."""
        n_samples, n_features = X.shape
        # Initialize means/stds
        self.means = np.array([np.mean(X, axis=0), np.mean(X, axis=0) * 1.1])
        self.stds = np.array([np.std(X, axis=0), np.std(X, axis=0) * 1.1])
        
        for _ in range(n_iter):
            # E-step: Compute probabilities
            probs = np.zeros((n_samples, self.n_states))
            for s in range(self.n_states):
                # Likelihood of each feature (assuming independence for simplicity)
                p = 1.0
                for f in range(n_features):
                    p *= _normal_pdf(X[:, f], self.means[s, f], self.stds[s, f] + 1e-6)
                probs[:, s] = p
            
            # Normalize
            probs /= (np.sum(probs, axis=1, keepdims=True) + 1e-9)
            
            # M-step: Update parameters
            for s in range(self.n_states):
                gamma_sum = np.sum(probs[:, s])
                self.means[s] = np.sum(X * probs[:, s][:, np.newaxis], axis=0) / (gamma_sum + 1e-9)
                self.stds[s] = np.sqrt(np.sum(probs[:, s][:, np.newaxis] * (X - self.means[s])**2, axis=0) / (gamma_sum + 1e-9))
                self.pi[s] = gamma_sum / n_samples

        self.is_trained = True

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        if not self.is_trained:
            return np.array([0.5, 0.5])
        
        probs = np.zeros(self.n_states)
        for s in range(self.n_states):
            p = self.pi[s]
            for f in range(x.shape[0]):
                p *= _normal_pdf(x[f], self.means[s, f], self.stds[s, f] + 1e-6)
            probs[s] = p
        
        total = np.sum(probs)
        return probs / total if total > 0 else np.array([0.5, 0.5])

class HMMRegimeDetector:
    def __init__(self) -> None:
        self._model = SimpleHMM(n_states=2)
        self._trend_state_idx = 1

    def _extract_features(self, candles: list[Candle]) -> np.ndarray:
        if len(candles) < 20:
            return np.empty((0, 3))
        closes = np.array([c.close for c in candles])
        returns = np.diff(np.log(closes))
        vols = np.array([np.std(returns[max(0, i-15):i+1]) for i in range(len(returns))])
        volumes = np.array([c.volume for c in candles])[1:]
        vol_mean = np.mean(volumes)
        vol_std = np.std(volumes) + 1e-9
        vol_z = (volumes - vol_mean) / vol_std
        return np.column_stack([returns, vols, vol_z])

    def train(self, candles: list[Candle]) -> bool:
        features = self._extract_features(candles)
        if features.shape[0] < 50:
            return False
        self._model.fit(features)
        # Higher volatility mean usually indicates Trend or Volatile regime
        if self._model.means[0, 1] > self._model.means[1, 1]:
            self._trend_state_idx = 0
        else:
            self._trend_state_idx = 1
        return True

    def predict(self, candles: list[Candle]) -> HMMRegimeAnalysis:
        features = self._extract_features(candles)
        if features.shape[0] == 0:
            return HMMRegimeAnalysis(HMMState.NOISE, 0.0, 0.0)
        
        probs = self._model.predict_proba(features[-1])
        state_idx = np.argmax(probs)
        state = HMMState.TREND if state_idx == self._trend_state_idx else HMMState.NOISE
        return HMMRegimeAnalysis(state, probs[state_idx], features[-1, 1])


def _normal_pdf(x: np.ndarray | float, mean: float, std: float) -> np.ndarray | float:
    safe_std = max(float(std), 1e-6)
    z = (x - mean) / safe_std
    return np.exp(-0.5 * z * z) / (safe_std * np.sqrt(2.0 * np.pi))
