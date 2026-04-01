import torch
import time
import json
import subprocess
import threading
import pyupbit
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

from crypto_trader.strategy.alpha_calibrator import AlphaCalibration, load_calibration

STATE_FILE = Path("ralph-loop.state.json")
RESEARCH_DIR = Path("../crypto-strategy-research/research")

FETCH_WORKERS = 5       # 업비트 rate limit 고려 (10 req/s)
INTERVAL = "minute240"  # 4시간봉
COUNT = 180             # 단일 요청으로 30일치 커버
RECENT_WINDOW = 6       # 최근 윈도우 (6봉 = 24시간)


def fetch_single(symbol: str) -> tuple[str, pd.DataFrame | None]:
    try:
        df = pyupbit.get_ohlcv(symbol, interval=INTERVAL, count=COUNT)
        if df is None or len(df) < 50:
            return symbol, None
        return symbol, df
    except Exception:
        return symbol, None


def fetch_all_parallel(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """업비트 API를 병렬로 조회해서 전체 종목 데이터를 수집합니다."""
    results = {}
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = {executor.submit(fetch_single, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, df = future.result()
            if df is not None:
                results[symbol] = df
    return results


def compute_batch_gpu(all_data: dict[str, pd.DataFrame], btc_df: pd.DataFrame, cal: AlphaCalibration | None = None) -> pd.DataFrame:
    """
    수집된 전체 종목 데이터를 GPU 배치 연산으로 한 번에 처리합니다.
    RS / Acc / CVD 를 행렬 연산으로 계산 후 z-score 정규화.
    """
    symbols = list(all_data.keys())
    n = len(symbols)
    if n == 0:
        return pd.DataFrame()

    # 공통 길이 맞추기
    common_len = min(len(df) for df in all_data.values())
    common_len = min(common_len, len(btc_df))

    btc_closes = torch.tensor(
        btc_df['close'].values[-common_len:], device='cuda', dtype=torch.float32
    )  # (common_len,)

    # 종목 × 시간 행렬 구성 (전부 GPU로 올리기)
    closes_mat  = torch.zeros(n, common_len, device='cuda', dtype=torch.float32)
    opens_mat   = torch.zeros(n, common_len, device='cuda', dtype=torch.float32)
    highs_mat   = torch.zeros(n, common_len, device='cuda', dtype=torch.float32)
    lows_mat    = torch.zeros(n, common_len, device='cuda', dtype=torch.float32)
    vols_mat    = torch.zeros(n, common_len, device='cuda', dtype=torch.float32)

    for i, sym in enumerate(symbols):
        df = all_data[sym].iloc[-common_len:]
        closes_mat[i]  = torch.tensor(df['close'].values,  dtype=torch.float32)
        opens_mat[i]   = torch.tensor(df['open'].values,   dtype=torch.float32)
        highs_mat[i]   = torch.tensor(df['high'].values,   dtype=torch.float32)
        lows_mat[i]    = torch.tensor(df['low'].values,    dtype=torch.float32)
        vols_mat[i]    = torch.tensor(df['volume'].values, dtype=torch.float32)

    # ── 1. Relative Strength (n, common_len) → 마지막 값 (n,) ──────────────
    sym_norm = closes_mat / closes_mat[:, 0:1].clamp(min=1e-9)   # (n, T)
    btc_norm = (btc_closes / btc_closes[0].clamp(min=1e-9))       # (T,)
    rs = (sym_norm / btc_norm.unsqueeze(0))[:, -1]                # (n,)

    # ── 2. Accumulation Score (VPIN proxy) — GPU 벡터화 ────────────────────
    price_range = (highs_mat - lows_mat).clamp(min=1e-9)          # (n, T)
    vpin_mat    = (closes_mat - opens_mat).abs() / price_range     # (n, T)
    acc = vpin_mat[:, -RECENT_WINDOW:].mean(dim=1) / vpin_mat[:, :-RECENT_WINDOW].mean(dim=1).clamp(min=1e-9)  # (n,)

    # ── 3. CVD Slope — GPU 벡터화 ──────────────────────────────────────────
    direction = torch.where(closes_mat >= opens_mat,
                            torch.ones_like(vols_mat),
                            torch.full_like(vols_mat, -1.0))
    cvd = (vols_mat * direction).cumsum(dim=1)                    # (n, T)
    vol_mean = vols_mat.mean(dim=1).clamp(min=1e-9)               # (n,)
    cvd_slope = (cvd[:, -1] - cvd[:, -RECENT_WINDOW]) / vol_mean   # (n,)

    # ── Extended features ─────────────────────────────────────────────────
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from gpu_features import compute_gpu_features
    ext = compute_gpu_features(closes_mat, opens_mat, highs_mat, lows_mat, vols_mat)

    # ── z-score 정규화 ────────────────────────────────────────────────────
    def zscore(t: torch.Tensor) -> torch.Tensor:
        return (t - t.mean()) / (t.std() + 1e-9)

    rs_z    = zscore(rs)
    acc_z   = zscore(acc)
    cvd_z   = zscore(cvd_slope)
    rsi_z   = zscore(ext["rsi"])
    macd_z  = zscore(ext["macd"])
    atr_z   = zscore(ext["atr_norm"])
    obv_z   = zscore(ext["obv_slope"])
    bb_z    = zscore(ext["bb_pos"])

    # calibration weights
    rs_w   = cal.rs_weight   if cal else 0.4
    acc_w  = cal.acc_weight  if cal else 0.3
    cvd_w  = cal.cvd_weight  if cal else 0.3
    rsi_w  = cal.rsi_weight  if cal else 0.0
    macd_w = cal.macd_weight if cal else 0.0
    atr_w  = cal.atr_weight  if cal else 0.0
    obv_w  = cal.obv_weight  if cal else 0.0
    bb_w   = cal.bb_weight   if cal else 0.0

    alpha = (
        rs_z * rs_w + acc_z * acc_w + cvd_z * cvd_w
        + rsi_z * rsi_w + macd_z * macd_w
        + atr_z * atr_w + obv_z * obv_w + bb_z * bb_w
    )

    df_out = pd.DataFrame({
        "Symbol":  symbols,
        "Alpha":   alpha.cpu().numpy().round(4),
        "RS":      rs.cpu().numpy().round(4),
        "Acc":     acc.cpu().numpy().round(4),
        "CVD":     cvd_slope.cpu().numpy().round(4),
        "RS_z":    rs_z.cpu().numpy().round(4),
        "Acc_z":   acc_z.cpu().numpy().round(4),
        "CVD_z":   cvd_z.cpu().numpy().round(4),
        "RSI_z":   rsi_z.cpu().numpy().round(4),
        "MACD_z":  macd_z.cpu().numpy().round(4),
        "ATR_z":   atr_z.cpu().numpy().round(4),
        "OBV_z":   obv_z.cpu().numpy().round(4),
        "BB_z":    bb_z.cpu().numpy().round(4),
    }).sort_values("Alpha", ascending=False)

    return df_out


def get_alpha_scan_results() -> tuple[str, float, dict]:
    """Returns: (scan_data_str, cal_threshold, pre_bull_signals)"""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is NOT available.")

    t0 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Phase 1: Parallel API fetch...")
    symbols = pyupbit.get_tickers(fiat="KRW")
    btc_df  = pyupbit.get_ohlcv("KRW-BTC", interval=INTERVAL, count=COUNT)

    all_data = fetch_all_parallel(symbols)
    t1 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetched {len(all_data)} symbols in {t1-t0:.1f}s")

    cal = load_calibration()
    verdict_tag = f"[cal:{cal.verdict} th={cal.threshold:.2f}]" if cal.verdict != "unknown" else "[cal:default]"
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Phase 2: Batch GPU computation... {verdict_tag}")
    df_result = compute_batch_gpu(all_data, btc_df, cal=cal if cal.is_usable else None)
    t2 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] GPU done in {t2-t1:.2f}s | Total: {t2-t0:.1f}s")
    cal_threshold = cal.threshold if cal.is_usable else 1.0

    # Pre-bull 시그널: RAW 값 기반 시장 매집 강도
    # stealth: 가격은 약한데(RS < 1.0) 매집은 강한(Acc > 1.0 AND CVD > 0) 코인
    stealth_mask = (df_result["RS"] < 1.0) & (df_result["Acc"] > 1.0) & (df_result["CVD"] > 0)
    stealth_acc_count = int(stealth_mask.sum())
    total_coins = len(df_result)
    pct_pos_acc  = float(round((df_result["Acc"] > 1.0).sum() / max(total_coins, 1), 3))
    pct_pos_cvd  = float(round((df_result["CVD"] > 0).sum() / max(total_coins, 1), 3))
    pct_weak_rs  = float(round((df_result["RS"] < 1.0).sum() / max(total_coins, 1), 3))
    # 중립=0, 강한 매집(불장 전조)=+2.0
    pre_bull_score = round(pct_pos_acc + pct_pos_cvd + pct_weak_rs - 1.0, 3)

    pre_bull_signals = {
        "stealth_acc_count": stealth_acc_count,
        "stealth_acc_ratio": round(stealth_acc_count / max(total_coins, 1), 3),
        "pct_pos_acc": pct_pos_acc,
        "pct_pos_cvd": pct_pos_cvd,
        "pct_weak_rs": pct_weak_rs,
        "pre_bull_score": pre_bull_score,
        "total_coins_scanned": total_coins,
    }

    return df_result.head(15).to_string(index=False), cal_threshold, pre_bull_signals, all_data


def update_state(cycle: int, note: str) -> None:
    try:
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        state: dict = {"current_cycle": cycle, "history": []}
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
            except Exception:
                pass
        state["current_cycle"] = cycle
        state["history"].append({"cycle": cycle, "note": note, "timestamp": datetime.now().isoformat()})
        if len(state["history"]) > 30:
            state["history"] = state["history"][-30:]
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"State update failed: {e}")


def _backtest_worker() -> None:
    """6시간마다 Alpha 예측력 백테스트를 백그라운드에서 실행합니다."""
    backtest_script = _project_root / "scripts" / "backtest_alpha_filter.py"
    while True:
        time.sleep(6 * 3600)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Running GPU Alpha backtest...")
        try:
            result = subprocess.run(
                [sys.executable, str(backtest_script)],
                timeout=600,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest done. See artifacts/alpha-backtest-result.md")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest error: {result.stderr[-200:]}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [BG] Backtest failed: {e}")


def main() -> None:
    print("♾️ Lab Mode: PARALLEL ALPHA HUNTER (RTX 3080 Batch) Engaged.")
    # 백그라운드 GPU 백테스트 스레드 시작 (6시간마다)
    bg = threading.Thread(target=_backtest_worker, daemon=True)
    bg.start()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Background GPU backtest thread started (6h interval).")
    while True:
        try:
            current = 0
            if STATE_FILE.exists():
                try:
                    with open(STATE_FILE) as f:
                        current = json.load(f).get("current_cycle", 0)
                except Exception:
                    pass

            cycle = current + 1
            print(f"\n--- [Cycle {cycle} START] ---")

            scan_data, cal_threshold, pre_bull, all_data = get_alpha_scan_results()

            report_path = RESEARCH_DIR / f"Cycle-{cycle:03d}-alpha-report.md"
            with report_path.open("w") as f:
                f.write(f"# 🧪 Cycle {cycle} Report: Parallel Alpha Scan\n\n")
                f.write(f"Fetched all KRW symbols in parallel → RTX 3080 batch computation.\n\n")
                f.write(f"```\n{scan_data}\n```\n\n---\nAuto-generated by Ralph Lab.")

            # alpha-watchlist.json 저장 — calibrated threshold 기준 필터링
            top_symbols = []
            for line in scan_data.splitlines()[1:]:
                parts = line.split()
                if not parts:
                    continue
                try:
                    sym, alpha_val = parts[0], float(parts[1])
                    if alpha_val >= cal_threshold:
                        top_symbols.append({"symbol": sym, "alpha": alpha_val})
                    if len(top_symbols) >= 5:
                        break
                except (IndexError, ValueError):
                    pass
            watchlist_path = Path("artifacts/alpha-watchlist.json")
            watchlist_path.parent.mkdir(exist_ok=True)
            with watchlist_path.open("w") as f:
                json.dump({
                    "updated_at": datetime.now().isoformat(),
                    "cycle": cycle,
                    "top_symbols": top_symbols,
                }, f, indent=2)
            print(f"Watchlist saved: {[s['symbol'] for s in top_symbols]}")

            # Pre-bull 시그널 저장 (시계열 누적)
            prebull_path = Path("artifacts/pre-bull-signals.json")
            history = []
            if prebull_path.exists():
                try:
                    history = json.loads(prebull_path.read_text()).get("history", [])
                except Exception:
                    pass
            history.append({"cycle": cycle, "ts": datetime.now().isoformat(), **pre_bull})
            history = history[-168:]  # 최대 168사이클(7일) 보관
            prebull_path.write_text(json.dumps({
                "updated_at": datetime.now().isoformat(),
                "latest": pre_bull,
                "history": history,
            }, indent=2))
            print(
                f"[Pre-Bull] score={pre_bull['pre_bull_score']:+.3f} "
                f"stealth={pre_bull['stealth_acc_count']}/{pre_bull['total_coins_scanned']} "
                f"(acc%={pre_bull['pct_pos_acc']:.0%} cvd%={pre_bull['pct_pos_cvd']:.0%} weak_rs%={pre_bull['pct_weak_rs']:.0%})"
            )

            # Correlation matrix (rotation detection)
            try:
                sys.path.insert(0, str(_project_root / "scripts"))
                from gpu_correlation import compute_correlation_matrix
                corr_result = compute_correlation_matrix(all_data, window=30)
                corr_path = Path("artifacts/correlation-matrix.json")
                with corr_path.open("w") as _f:
                    json.dump({
                        "updated_at": datetime.now().isoformat(),
                        "cycle": cycle,
                        "avg_corr": corr_result["avg_corr"],
                        "leaders": corr_result["leaders"],
                    }, _f, indent=2)
                print(
                    f"[Corr] avg={corr_result['avg_corr']:.3f} "
                    f"leaders={corr_result['leaders'][:3]}"
                )
            except Exception as e:
                print(f"[Corr] skipped: {e}")

            update_state(cycle, f"Cycle {cycle} archived.")
            print(f"--- [Cycle {cycle} DONE] ---")

            time.sleep(3600)  # 1시간 주기 (4h봉 데이터 갱신 주기에 맞춤)
        except SystemExit:
            break
        except Exception as e:
            print(f"LOOP ERROR: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
