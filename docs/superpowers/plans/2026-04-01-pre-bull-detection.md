# Pre-Bull Detection + Regime-Aware Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) 불장 시작 전 매집 시그널을 lab loop에서 실시간 추적하고, (2) 백테스트를 레짐(pre-bull/bull/bear/post-bull)별로 분리해서 알파 스코어의 진짜 예측력을 검증한다.

**Architecture:**
- `compute_batch_gpu`가 이미 rs_z, acc_z, cvd_z를 내부 계산하므로 DataFrame에 추가 컬럼으로 노출한다.
- lab loop 각 사이클마다 "가격은 약한데 매집만 올라오는 코인 수(stealth_acc_count)"를 `artifacts/pre-bull-signals.json`에 누적 저장한다.
- backtest에서 BTC 20봉 SMA + 기울기로 레짐을 태깅하고, 레짐별 알파 예측력을 분리 리포트한다.

**Tech Stack:** Python 3.12, PyTorch (CUDA), pandas, pyupbit, existing lab loop + backtest scripts

---

## File Map

| 파일 | 변경 내용 |
|------|----------|
| `scripts/autonomous_lab_loop.py` | `compute_batch_gpu` — rs_z/acc_z/cvd_z 컬럼 추가 반환; `get_alpha_scan_results` — pre-bull 지표 계산+저장 |
| `scripts/backtest_alpha_filter.py` | `detect_btc_regime()` 추가; `main()` 레짐별 분리 검증 + 리포트 |

---

## Task 1: compute_batch_gpu에 z-score 컬럼 추가

**Files:**
- Modify: `scripts/autonomous_lab_loop.py` (lines 114-124)

- [ ] **Step 1: df_out에 rs_z, acc_z, cvd_z 컬럼 추가**

`compute_batch_gpu` 함수 내 df_out 생성 부분을 아래로 교체:

```python
    df_out = pd.DataFrame({
        "Symbol": symbols,
        "Alpha":  alpha.cpu().numpy().round(4),
        "RS":     rs.cpu().numpy().round(4),
        "Acc":    acc.cpu().numpy().round(4),
        "CVD":    cvd_slope.cpu().numpy().round(4),
        "RS_z":   rs_z.cpu().numpy().round(4),
        "Acc_z":  acc_z.cpu().numpy().round(4),
        "CVD_z":  cvd_z.cpu().numpy().round(4),
    }).sort_values("Alpha", ascending=False)
```

- [ ] **Step 2: 변경 확인**

```bash
cd ~/workspace/crypto-trader && source .venv/bin/activate && python3 -c "
import pyupbit, torch
from scripts.autonomous_lab_loop import compute_batch_gpu
btc = pyupbit.get_ohlcv('KRW-BTC', interval='minute240', count=180)
data = {'KRW-BTC': btc, 'KRW-ETH': pyupbit.get_ohlcv('KRW-ETH', interval='minute240', count=180)}
df = compute_batch_gpu(data, btc)
print(df.columns.tolist())
print(df.head(2))
"
```

Expected output: columns에 `RS_z`, `Acc_z`, `CVD_z` 포함

- [ ] **Step 3: Commit**

```bash
git add scripts/autonomous_lab_loop.py
git commit -m "feat: expose rs_z/acc_z/cvd_z from compute_batch_gpu"
```

---

## Task 2: lab loop에 pre-bull 시그널 추적 추가

**Files:**
- Modify: `scripts/autonomous_lab_loop.py` (`get_alpha_scan_results` 함수 및 `main` 루프)

- [ ] **Step 1: `get_alpha_scan_results` 반환값에 pre-bull 지표 추가**

`get_alpha_scan_results` 함수 시그니처와 반환부를 수정:

```python
def get_alpha_scan_results() -> tuple[str, float, dict]:
    """Returns: (scan_data_str, cal_threshold, pre_bull_signals)"""
```

함수 내 `df_result = compute_batch_gpu(...)` 호출 이후에 아래 코드 추가:

```python
    # Pre-bull 시그널: 가격은 약한데(RS_z < 0) 매집은 강한(Acc_z > 1.0 AND CVD_z > 0.5) 코인 수
    stealth_mask = (df_result["RS_z"] < 0) & (df_result["Acc_z"] > 1.0) & (df_result["CVD_z"] > 0.5)
    stealth_acc_count = int(stealth_mask.sum())
    total_coins = len(df_result)
    avg_acc_z = float(df_result["Acc_z"].mean().round(3))
    avg_cvd_z = float(df_result["CVD_z"].mean().round(3))
    avg_rs_z  = float(df_result["RS_z"].mean().round(3))
    # pre_bull_score: Acc+CVD 상승 + RS 하락 = 매집 중인 하락장 신호
    pre_bull_score = round(avg_acc_z + avg_cvd_z - avg_rs_z, 3)

    pre_bull_signals = {
        "stealth_acc_count": stealth_acc_count,
        "stealth_acc_ratio": round(stealth_acc_count / max(total_coins, 1), 3),
        "avg_rs_z": avg_rs_z,
        "avg_acc_z": avg_acc_z,
        "avg_cvd_z": avg_cvd_z,
        "pre_bull_score": pre_bull_score,
        "total_coins_scanned": total_coins,
    }
```

기존 `return scan_data, cal_threshold` 를 `return scan_data, cal_threshold, pre_bull_signals` 로 변경.

- [ ] **Step 2: main() 루프에서 pre-bull 신호 저장 및 출력**

`main()` 함수 내 `scan_data, cal_threshold = get_alpha_scan_results()` 라인을:

```python
            scan_data, cal_threshold, pre_bull = get_alpha_scan_results()
```

로 변경 후, watchlist 저장 블록 다음에 추가:

```python
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
                f"(RS_z={pre_bull['avg_rs_z']:+.2f} Acc_z={pre_bull['avg_acc_z']:+.2f} CVD_z={pre_bull['avg_cvd_z']:+.2f})"
            )
```

- [ ] **Step 3: 동작 확인 (lab loop 단일 사이클 실행)**

```bash
cd ~/workspace/crypto-trader && source .venv/bin/activate && python3 -c "
import sys; sys.path.insert(0, 'src')
# 단일 사이클 실행
from scripts.autonomous_lab_loop import get_alpha_scan_results
scan_data, threshold, pre_bull = get_alpha_scan_results()
print('Pre-bull:', pre_bull)
import json; print(open('artifacts/pre-bull-signals.json').read())
"
```

Expected: `pre-bull-signals.json` 생성, `pre_bull_score`, `stealth_acc_count` 값 출력

- [ ] **Step 4: Commit**

```bash
git add scripts/autonomous_lab_loop.py
git commit -m "feat: add pre-bull stealth accumulation signal tracking to lab loop"
```

---

## Task 3: backtest에 BTC 레짐 감지 함수 추가

**Files:**
- Modify: `scripts/backtest_alpha_filter.py`

- [ ] **Step 1: `detect_btc_regime()` 함수 추가**

`import` 블록 아래, `fetch_symbol` 함수 위에 추가:

```python
def detect_btc_regime(btc_df: pd.DataFrame, sma_period: int = 20) -> pd.Series:
    """
    BTC 가격 기반 레짐 감지.
    Returns pd.Series[str]: 인덱스=시간, 값='bull'|'bear'|'pre_bull'|'post_bull'
    
    - bull: SMA 위 + SMA 기울기 양수
    - bear: SMA 아래 + SMA 기울기 음수  
    - pre_bull: SMA 아래이지만 SMA 기울기가 최근 전환(기울기 > -0.5σ)
    - post_bull: SMA 위이지만 SMA 기울기 하락 전환
    """
    closes = btc_df['close']
    sma = closes.rolling(sma_period).mean()
    # SMA 기울기: sma 변화율 (%)
    sma_slope = sma.pct_change(5).fillna(0)  # 5봉 변화율
    slope_std = sma_slope.std()

    regime = pd.Series(index=closes.index, dtype=str)
    above_sma = closes > sma
    slope_pos = sma_slope > 0
    slope_recovering = sma_slope > -0.5 * slope_std  # 기울기가 바닥권 탈출 중

    regime[above_sma & slope_pos] = "bull"
    regime[above_sma & ~slope_pos] = "post_bull"
    regime[~above_sma & ~slope_recovering] = "bear"
    regime[~above_sma & slope_recovering] = "pre_bull"
    regime = regime.fillna("bear")
    return regime
```

- [ ] **Step 2: 레짐 감지 단독 테스트**

```bash
cd ~/workspace/crypto-trader && source .venv/bin/activate && python3 -c "
import pyupbit
from scripts.backtest_alpha_filter import detect_btc_regime
btc = pyupbit.get_ohlcv('KRW-BTC', interval='minute240', count=500)
regime = detect_btc_regime(btc)
print(regime.value_counts())
print(regime.tail(10))
"
```

Expected: bull/bear/pre_bull/post_bull 4가지 값이 분포, 현재(하락장)는 bear/pre_bull 다수

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_alpha_filter.py
git commit -m "feat: add detect_btc_regime for regime-aware backtest segmentation"
```

---

## Task 4: backtest 레짐별 분리 검증 + 리포트

**Files:**
- Modify: `scripts/backtest_alpha_filter.py` (`main()` 함수, 리포트 저장 부분)

- [ ] **Step 1: main()에서 레짐 태깅 및 per-regime 데이터 분리**

기존 `btc_df = pyupbit.get_ohlcv(...)` 라인 이후에 레짐 감지 추가:

```python
    btc_regime = detect_btc_regime(btc_df)
    regime_counts = btc_regime.value_counts().to_dict()
    print(f"레짐 분포: {regime_counts}")
```

기존 `validate_alpha_predictiveness` 호출 루프를 레짐별로 분리:

```python
    # 레짐별 결과 수집
    regime_results: dict[str, list[dict]] = {"bull": [], "bear": [], "pre_bull": [], "post_bull": []}
    components_by_regime: dict[str, list] = {"bull": [], "bear": [], "pre_bull": [], "post_bull": []}
    fwd_by_regime: dict[str, list] = {"bull": [], "bear": [], "pre_bull": [], "post_bull": []}

    for symbol, df in all_data.items():
        alpha_df = compute_alpha_series(df, btc_df)
        if alpha_df is None or len(alpha_df) < 20:
            continue

        # 레짐 인덱스 정렬
        common_idx = alpha_df.index.intersection(btc_regime.index)
        if len(common_idx) < 20:
            continue

        for regime_name in regime_results:
            regime_idx = common_idx[btc_regime[common_idx] == regime_name]
            if len(regime_idx) < 15:
                continue

            regime_alpha = alpha_df.loc[regime_idx, "alpha"]
            regime_closes = df['close'].reindex(regime_idx)
            regime_fwd = regime_closes.shift(-6) / regime_closes - 1  # 6봉 forward

            result = validate_alpha_predictiveness(
                df.loc[regime_idx],
                alpha_df.loc[regime_idx],
                symbol,
            )
            regime_results[regime_name].append(result)
            components_by_regime[regime_name].append(alpha_df.loc[regime_idx, ["rs_z", "acc_z", "cvd_z"]])
            fwd_by_regime[regime_name].append(regime_fwd)

        print(f"  {symbol}: done")
```

- [ ] **Step 2: 레짐별 요약 통계 및 리포트 저장**

기존 리포트 저장 부분을 아래로 교체:

```python
    # 전체 요약
    all_results = []
    for r_list in regime_results.values():
        all_results.extend(r_list)

    df_sum = pd.DataFrame(all_results).set_index("symbol") if all_results else pd.DataFrame()

    # 레짐별 평균 상관계수
    regime_summary = {}
    for regime_name, r_list in regime_results.items():
        if not r_list:
            regime_summary[regime_name] = "데이터 없음"
            continue
        rdf = pd.DataFrame(r_list)
        corr_cols = [c for c in rdf.columns if c.startswith("corr_")]
        edge_cols = [c for c in rdf.columns if c.startswith("edge_")]
        regime_summary[regime_name] = {
            "n_symbols": len(rdf),
            "avg_corr_6b": round(rdf["corr_6b"].mean(), 3) if "corr_6b" in rdf else None,
            "avg_edge_6b": round(rdf["edge_6b_%"].mean(), 3) if "edge_6b_%" in rdf else None,
        }

    # 최적 파라미터 (전체 기준)
    all_components = [c for clist in components_by_regime.values() for c in clist]
    all_fwd = [f for flist in fwd_by_regime.values() for f in flist]
    if all_components and all_fwd:
        rs_w, acc_w, cvd_w, threshold, best_edge, best_corr = find_optimal_params(all_components, all_fwd)
    else:
        rs_w, acc_w, cvd_w, threshold, best_edge, best_corr = 0.4, 0.3, 0.3, 1.0, 0.0, 0.0

    # verdict
    bull_edge = regime_summary.get("bull", {}).get("avg_edge_6b", None)
    if isinstance(bull_edge, float) and bull_edge > 0.3:
        verdict = "valid_in_bull"
    elif best_edge > 0.3:
        verdict = "valid"
    elif best_edge > 0.0:
        verdict = "weak"
    else:
        verdict = "invalid"

    # calibration 저장
    cal_data = {
        "rs_weight": rs_w, "acc_weight": acc_w, "cvd_weight": cvd_w,
        "threshold": threshold, "best_edge": best_edge, "best_corr": best_corr,
        "verdict": verdict,
    }
    Path("artifacts/alpha-calibration.json").write_text(json.dumps(cal_data, indent=2))

    # 리포트 저장
    out_path = Path("artifacts/alpha-backtest-result.md")
    lines = [
        "# Alpha Score 예측력 검증 결과\n",
        f"실행: {datetime.now().isoformat()}\n",
        f"## 레짐 분포\n```\n{regime_counts}\n```\n",
        "## 레짐별 성과 (6봉=24h 기준)\n",
    ]
    for rname, rdata in regime_summary.items():
        if isinstance(rdata, dict):
            lines.append(f"### {rname}\n")
            lines.append(f"- 종목 수: {rdata['n_symbols']}\n")
            lines.append(f"- 평균 상관계수(6b): {rdata['avg_corr_6b']}\n")
            lines.append(f"- 평균 엣지(6b): {rdata['avg_edge_6b']}%\n\n")
        else:
            lines.append(f"### {rname}: {rdata}\n\n")
    lines.append(f"## 최적 파라미터\n")
    lines.append(f"- 가중치: RS={rs_w} / Acc={acc_w} / CVD={cvd_w}\n")
    lines.append(f"- 임계값: {threshold}\n")
    lines.append(f"- 평균 엣지(6봉): {best_edge:+.3f}%\n")
    lines.append(f"- **Verdict: {verdict}**\n")
    out_path.write_text("".join(lines))
    print(f"  Report saved → {out_path}")
```

- [ ] **Step 3: 전체 backtest 실행 테스트**

```bash
cd ~/workspace/crypto-trader && source .venv/bin/activate && nohup python3 scripts/backtest_alpha_filter.py > /tmp/backtest-regime.log 2>&1 &
echo "PID: $!"
# ~2분 후 확인
sleep 120 && tail -30 /tmp/backtest-regime.log
cat artifacts/alpha-backtest-result.md
```

Expected: bull/pre_bull/bear/post_bull 별 avg_corr, avg_edge 출력. bull 구간 엣지 > bear 구간 엣지

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest_alpha_filter.py
git commit -m "feat: regime-aware backtest — bull/pre_bull/bear/post_bull segmented alpha validation"
```

---

## Task 5: lab loop 재시작으로 pre-bull 시그널 활성화

- [ ] **Step 1: 현재 lab loop 종료 후 재시작**

```bash
kill $(pgrep -f autonomous_lab_loop)
sleep 2
cd ~/workspace/crypto-trader && source .venv/bin/activate
nohup python3 -u scripts/autonomous_lab_loop.py >> logs/lab-stable.log 2>&1 &
echo "PID: $!"
```

- [ ] **Step 2: 첫 사이클에서 pre-bull 출력 확인**

```bash
tail -f logs/lab-stable.log | grep -E "Pre-Bull|Watchlist|Cycle"
```

Expected:
```
--- [Cycle 15 START] ---
[Pre-Bull] score=+X.XXX stealth=N/244 (RS_z=... Acc_z=... CVD_z=...)
Watchlist saved: ['KRW-RAY', 'KRW-ZBT']
--- [Cycle 15 DONE] ---
```

- [ ] **Step 3: pre-bull-signals.json 확인**

```bash
cat artifacts/pre-bull-signals.json
```

Expected: `latest.pre_bull_score`, `latest.stealth_acc_count`, `history` 배열 포함

---

## Pre-Bull Score 해석 가이드

| score 범위 | 시장 상태 | 의미 |
|-----------|----------|------|
| < -1.0 | 강한 하락장 | RS 강하, 매집 없음 |
| -1.0 ~ 0 | 하락/횡보 | 현재 상태 |
| 0 ~ 1.0 | **매집 시작** | 주의 깊게 모니터링 |
| > 1.0 | **강한 pre-bull 신호** | 포지션 준비 고려 |
| > 2.0 | 불장 초입 또는 과열 | |

`stealth_acc_count`가 전체 대비 10% 이상이고 `pre_bull_score > 0.5`이면 불장 전환 시그널로 볼 수 있음.
