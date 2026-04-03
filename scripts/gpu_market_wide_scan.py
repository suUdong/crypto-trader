
import torch
import sys
import time
import pandas as pd
from pathlib import Path
from datetime import datetime

# 프로젝트 루트 설정
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

def get_all_krw_symbols():
    """업비트의 모든 KRW 마켓 심볼을 가져옵니다."""
    try:
        import pyupbit
        return pyupbit.get_tickers(fiat="KRW")
    except:
        return ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-DOGE", "KRW-ADA", "KRW-AVAX", "KRW-DOT"]

def fetch_gpu_data(symbol, days=60):
    """특정 종목의 데이터를 GPU로 로드합니다."""
    try:
        import pyupbit
        # 15분봉 데이터 로드
        df = pyupbit.get_ohlcv(symbol, interval="minute15", count=days*24*4)
        if df is None or len(df) < 100: return None
        return {
            'close': torch.tensor(df['close'].values, dtype=torch.float32, device='cuda'),
            'volume': torch.tensor(df['volume'].values, dtype=torch.float32, device='cuda'),
            'high': torch.tensor(df['high'].values, dtype=torch.float32, device='cuda'),
            'low': torch.tensor(df['low'].values, dtype=torch.float32, device='cuda'),
            'open': torch.tensor(df['open'].values, dtype=torch.float32, device='cuda'),
        }
    except: return None

def main():
    symbols = get_all_krw_symbols()
    # 상위 30개 정도로 우선 타겟팅 (너무 많으면 API 리밋 걸릴 수 있음)
    target_symbols = symbols[:35] 
    
    print("\n" + "="*80)
    print(f"  🚀 RTX 3080 MARKET-WIDE SCAN: {len(target_symbols)} SYMBOLS ON CRUISE")
    print("="*80)

    results = []
    start_total = time.time()

    for symbol in target_symbols:
        print(f"Analyzing {symbol}...", end=" ", flush=True)
        data = fetch_gpu_data(symbol, days=60)
        if data is None:
            print("Skip.")
            continue
        
        closes = data['close']
        opens = data['open']
        highs = data['high']
        lows = data['low']
        volumes = data['volume']
        n = len(closes)
        holding = 4  # 4캔들(1시간) 보유

        # VPIN/OBI proxy 계산
        range_ = (highs - lows).clamp(min=1e-9)
        vpin = (closes - opens).abs() / range_
        obi = (closes - opens) / range_
        vol_mean = volumes.mean()

        # 진입 신호: vpin > 0.4, obi > 0, volume > mean
        signals = (vpin > 0.4) & (obi > 0) & (volumes > vol_mean)

        # forward return (holding 봉 후 청산)
        if n > holding:
            future_close = closes[holding:]
            entry_close = closes[:n - holding]
            fwd_ret = (future_close - entry_close) / entry_close.clamp(min=1e-9)
            active_signals = signals[:n - holding].float()
            n_trades = active_signals.sum().item()
            if n_trades > 0:
                trade_returns = active_signals * fwd_ret
                roi = trade_returns.sum().item() / n_trades * 100
                winning = (active_signals * (fwd_ret > 0).float()).sum().item()
                win_rate = winning / n_trades * 100
                # MDD: 누적 수익 곡선에서 최대 낙폭
                equity_curve = (1 + trade_returns).cumprod(dim=0)
                running_max = equity_curve.cummax(dim=0).values
                drawdowns = (equity_curve - running_max) / running_max.clamp(min=1e-9)
                mdd = drawdowns.min().item() * 100
            else:
                roi, mdd, win_rate, n_trades = 0.0, 0.0, 0.0, 0
        else:
            roi, mdd, win_rate, n_trades = 0.0, 0.0, 0.0, 0

        print(f"Done! ROI: {roi:+.1f}% WinRate: {win_rate:.0f}% Trades: {int(n_trades)}")

        results.append({
            "Symbol": symbol,
            "ROI_%": round(roi, 2),
            "MDD_%": round(mdd, 2),
            "WinRate_%": round(win_rate, 1),
            "Trades": int(n_trades),
        })
        time.sleep(0.05) # API Rate limit 방지

    # 결과 정렬 (수익률 높은 순)
    df = pd.DataFrame(results).sort_values(by="ROI_%", ascending=False)
    
    print("\n" + "="*80)
    print("  🏆 TOP 10 ALPHA OPPORTUNITIES (Found by RTX 3080)")
    print("="*80)
    print(df.head(10).to_string(index=False))
    print("="*80)
    
    total_duration = time.time() - start_total
    print(f"\n✅ Total {len(target_symbols)} symbols scanned in {total_duration:.1f}s.")
    print(f"💡 3080 Recommendation: 'Diversify into the Top 3 for maximum risk-adjusted return.'")

if __name__ == "__main__":
    main()
