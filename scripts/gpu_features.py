"""
GPU Feature Library — shared indicator computation for lab loop and backtest.
All functions accept (n_symbols, time) CUDA tensors and return dict[str, Tensor(n_symbols,)].
"""
from __future__ import annotations
import torch


def compute_gpu_features(
    closes_mat: torch.Tensor,   # (n, T)
    opens_mat: torch.Tensor,    # (n, T) — reserved for gap/body features; unused for now
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

    Args:
        closes_mat:  Closing prices, shape (n, T).
        opens_mat:   Opening prices, shape (n, T).  Reserved for future gap/body features.
        highs_mat:   High prices, shape (n, T).
        lows_mat:    Low prices, shape (n, T).
        vols_mat:    Volume, shape (n, T).
        rsi_period:  Lookback for RSI average gain/loss (requires T > rsi_period).
        macd_fast:   Fast SMA window for MACD (requires T >= macd_fast).
        macd_slow:   Slow SMA window for MACD (requires T >= macd_slow).
        atr_period:  Lookback for ATR (requires T > atr_period).
        obv_window:  Lookback for OBV slope (requires T > obv_window).
        bb_period:   Lookback for Bollinger Bands (requires T >= bb_period).
    """
    n, T = closes_mat.shape

    if T <= obv_window:
        raise ValueError(
            f"Time dimension T={T} must be greater than obv_window={obv_window}."
        )

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
