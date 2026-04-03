
import torch
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root / "scripts"))
from historical_loader import load_historical

INTERVAL = "15m"
START    = "2024-01-01"
END      = "2026-12-31"

from crypto_trader.models import Candle
from crypto_trader.strategy.truth_seeker import TruthSeekerStrategy
from crypto_trader.config import StrategyConfig

def fetch_data_to_gpu(symbol, days=180):
    """Historical data를 로드해서 GPU 텐서(Tensor)로 변환합니다."""
    try:
        print(f"Loading historical data for {symbol} ({START}~{END})...")
        df = load_historical(symbol, INTERVAL, START, END)
        if df is None or df.empty: return None
        
        # GPU 가속을 위해 종가(Close), 거래량(Volume), 고가(High), 저가(Low)를 텐서로 변환
        closes = torch.tensor(df['close'].values, dtype=torch.float32, device='cuda')
        volumes = torch.tensor(df['volume'].values, dtype=torch.float32, device='cuda')
        highs = torch.tensor(df['high'].values, dtype=torch.float32, device='cuda')
        lows = torch.tensor(df['low'].values, dtype=torch.float32, device='cuda')
        
        print(f"Loaded {len(closes)} candles directly onto RTX 3080 VRAM.")
        return closes, volumes, highs, lows
    except Exception as e:
        print(f"Data Fetch Error: {e}")
        return None

def run_3080_monster_sweep():
    data = fetch_data_to_gpu("KRW-SOL", days=180)
    if data is None: return
    closes, volumes, highs, lows = data

    # 3080의 위력: 수만 가지 조합을 '벡터화'하여 동시에 계산
    print("RTX 3080: Starting Parallel Universe Backtest...")
    start_time = time.time()

    # 테스트할 파라미터 그리드 (CPU보다 훨씬 더 촘촘하게!)
    vpin_range = torch.linspace(0.3, 0.6, 10, device='cuda')
    obi_range = torch.linspace(0.05, 0.3, 10, device='cuda')
    tp_range = torch.linspace(0.05, 0.20, 5, device='cuda')
    
    # 3080에서 10x10x5 = 500개 조합을 동시에 연산
    # (실제로는 수만 개도 가능하지만, 구조 파악을 위해 500개 우선 실행)
    holding_window = 16  # 15분봉 × 16 = 4시간 최대 보유
    sl_fixed = 0.03      # 손절 3% 고정

    # 사전 계산: 전체 캔들에 대해 forward return 행렬 구성 (n_bars, holding_window)
    n_bars = len(closes)
    padded = torch.cat([closes, closes[-1].expand(holding_window)])
    windows = padded.unfold(0, holding_window + 1, 1)[:n_bars]  # (n_bars, hw+1)
    entry_prices = windows[:, 0].unsqueeze(1).clamp(min=1e-9)
    future_prices = windows[:, 1:]                               # (n_bars, hw)
    fwd_returns = (future_prices - entry_prices) / entry_prices  # (n_bars, hw)

    # TP/SL 중 먼저 닿는 시점의 수익률 계산 (fully vectorized)
    tp_r = tp_range.unsqueeze(1).unsqueeze(2)     # (n_tp, 1, 1)
    fwd_r_exp = fwd_returns.unsqueeze(0)           # (1, n_bars, hw)
    tp_hit = fwd_r_exp >= tp_r                     # (n_tp, n_bars, hw)
    sl_hit = fwd_r_exp <= -sl_fixed               # (1, n_bars, hw) → broadcast
    exit_mask = tp_hit | sl_hit                    # (n_tp, n_bars, hw)
    has_exit = exit_mask.any(dim=2)                # (n_tp, n_bars)
    first_exit = exit_mask.float().argmax(dim=2)   # (n_tp, n_bars)
    # 청산 없으면 마지막 봉 사용
    last_idx = torch.full_like(first_exit, holding_window - 1)
    exit_idx = torch.where(has_exit, first_exit, last_idx)  # (n_tp, n_bars)

    # VPIN proxy: |close - open| / (high - low)
    price_change = (closes - opens).abs()
    range_ = (highs - lows).clamp(min=1e-9)
    vpin_proxy = price_change / range_  # (n_bars,)
    obi_proxy = (closes - opens) / range_  # (n_bars,) — 방향성 포함

    results = []
    vol_mean = volumes.mean()

    for vi, v in enumerate(vpin_range):
        for oi, o in enumerate(obi_range):
            # 진입 신호: vpin > v AND obi > o AND 거래량 > 평균
            signals = (vpin_proxy > v) & (obi_proxy > o) & (volumes > vol_mean)
            signals_f = signals.float()  # (n_bars,)

            for ti, tp in enumerate(tp_range):
                # 해당 TP에서의 청산 인덱스
                e_idx = exit_idx[ti]  # (n_bars,)
                # 각 봉의 실현 수익률
                trade_ret = fwd_returns.gather(1, e_idx.unsqueeze(1)).squeeze(1)  # (n_bars,)
                # 신호 있는 봉만 집계
                active_returns = signals_f * trade_ret
                n_trades = signals_f.sum().item()
                total_roi = active_returns.sum().item() * 100 if n_trades > 0 else 0.0
                results.append({
                    "VPIN": round(v.item(), 3),
                    "OBI": round(o.item(), 3),
                    "TP": round(tp.item(), 3),
                    "Trades": int(n_trades),
                    "Total_ROI_%": round(total_roi, 2),
                })

    duration = time.time() - start_time
    print(f"3080 Sweep completed in {duration:.2f} seconds.")

    import pandas as pd
    df_r = pd.DataFrame(results).sort_values("Total_ROI_%", ascending=False)
    best = df_r.iloc[0]
    print("\n" + "="*50)
    print("  RTX 3080 STRATEGY OPTIMIZATION REPORT")
    print("="*50)
    print(f"Target:        SOLANA (KRW-SOL) 15m")
    print(f"Data Period:   180 Days ({n_bars:,} candles)")
    print(f"Combinations:  {len(results):,} tested on GPU")
    print("-" * 50)
    print(f"BEST: VPIN={best['VPIN']} OBI={best['OBI']} TP={best['TP']:.0%} SL={sl_fixed:.0%}")
    print(f"Total ROI:  {best['Total_ROI_%']:+.2f}%  Trades: {best['Trades']}")
    print("="*50)
    print(df_r.head(10).to_string(index=False))

if __name__ == "__main__":
    run_3080_monster_sweep()
