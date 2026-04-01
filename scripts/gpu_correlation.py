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

    Returns dict with:
        corr_matrix: np.ndarray (n, n)
        symbols: list[str]
        leaders: list[str] — top 5 symbols by avg absolute correlation
        avg_corr: float — mean off-diagonal absolute correlation
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

    # Pearson correlation: normalize rows then dot product
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
