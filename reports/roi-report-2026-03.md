# ROI Report 2026-03

- Generated: `2026-03-27T22:26:47.935480+00:00`
- Timezone: `Asia/Seoul`
- Live wallets in checkpoint: `10`

## Executive Read

- Live runtime ROI is `-2,145 KRW` (`-0.020%`) using the current-assets basis `10,697,855 KRW` against runtime initial equity `10,700,000 KRW`.
- The checked-in config currently budgets `11,000,000 KRW`, which would imply `-302,145 KRW` (`-2.747%`) if used as the denominator.
- Decision-useful interpretation: the running deployment is effectively flat, while the newer 11.0M config budget is not yet the authoritative live baseline.

## Starting Capital Check

| Baseline | Amount (KRW) | Source | Comment |
|----------|--------------:|--------|---------|
| Runtime initial equity | 10,700,000 | `reports/roi-report-2026-03.snapshot.json` | Live session baseline used for headline ROI |
| Config capital | 11,000,000 | `config/daemon.toml` | Planned allocation in repo, currently ahead of the live checkpoint |
| Checkpoint observed equity | 10,697,612.89 | `reports/roi-report-2026-03.snapshot.json` | Latest artifact-backed total equity snapshot |
| Current assets override | 10,697,855 | User input | Used as the current-assets basis for the headline ROI |
| Reconciliation delta | +242.11 | Current assets - checkpoint equity | Small delta between user basis and checkpoint snapshot |

## Strategy Contribution

| Strategy | Wallets | Start Capital | Current Equity | PnL | Realized | Unrealized | Return | Contribution |
|----------|--------:|--------------:|---------------:|----:|---------:|-----------:|-------:|-------------:|
| volatility_breakout | 1 | 1,500,000 | 1,498,207.54 | -1,792.46 | -1,792.46 | +0.00 | -0.119% | +75.1% |
| vpin | 3 | 3,500,000 | 3,499,506.58 | -493.42 | +0.00 | -493.42 | -0.014% | +20.7% |
| mean_reversion | 1 | 200,000 | 199,898.77 | -101.23 | +0.00 | -101.23 | -0.051% | +4.2% |
| momentum | 4 | 4,400,612 | 4,400,612.00 | +0.00 | +0.00 | +0.00 | +0.000% | -0.0% |
| volume_spike | 1 | 1,099,388 | 1,099,388.00 | +0.00 | +0.00 | +0.00 | +0.000% | -0.0% |

## Daily Profit Curve

| Date | Equity | PnL vs Runtime Start | Return |
|------|-------:|---------------------:|-------:|
| 2026-03-27 | 10,700,000.00 | +0.00 | +0.000% |
| 2026-03-28 | 10,697,855.00 | -2,145.00 | -0.020% |

## Weekly Profit Curve

| Week | Equity | PnL vs Runtime Start | Return |
|------|-------:|---------------------:|-------:|
| 2026-W13 | 10,697,855.00 | -2,145.00 | -0.020% |

## Session Curve

| Time | Equity | PnL vs Runtime Start | Return |
|------|-------:|---------------------:|-------:|
| 2026-03-27 16:50 start | 10,700,000.00 | +0.00 | +0.000% |
| 2026-03-28 07:06 | 10,699,652.24 | -347.76 | -0.003% |
| 2026-03-28 07:06 | 10,699,574.75 | -425.25 | -0.004% |
| 2026-03-28 07:07 | 10,699,429.09 | -570.91 | -0.005% |
| 2026-03-28 07:07 | 10,699,381.61 | -618.39 | -0.006% |
| 2026-03-28 07:08 | 10,699,405.35 | -594.65 | -0.006% |
| 2026-03-28 07:11 | 10,699,623.84 | -376.16 | -0.004% |
| 2026-03-28 07:12 | 10,699,478.18 | -521.82 | -0.005% |
| 2026-03-28 07:12 | 10,699,466.31 | -533.69 | -0.005% |
| 2026-03-28 07:15 | 10,699,611.98 | -388.02 | -0.004% |
| 2026-03-28 07:15 | 10,699,600.11 | -399.89 | -0.004% |
| 2026-03-28 07:17 | 10,699,672.94 | -327.06 | -0.003% |
| 2026-03-28 07:17 | 10,699,684.81 | -315.19 | -0.003% |
| 2026-03-28 07:18 | 10,699,611.98 | -388.02 | -0.004% |
| 2026-03-28 07:18 | 10,699,600.11 | -399.89 | -0.004% |
| 2026-03-28 07:19 | 10,699,672.94 | -327.06 | -0.003% |
| 2026-03-28 07:20 | 10,699,818.60 | -181.40 | -0.002% |
| 2026-03-28 07:20 | 10,699,806.73 | -193.27 | -0.002% |
| 2026-03-28 07:22 | 10,699,588.24 | -411.76 | -0.004% |
| 2026-03-28 07:22 | 10,699,600.11 | -399.89 | -0.004% |
| 2026-03-28 07:23 | 10,699,527.27 | -472.73 | -0.004% |
| 2026-03-28 07:23 | 10,699,515.41 | -484.59 | -0.005% |
| 2026-03-28 07:24 | 10,699,733.90 | -266.10 | -0.002% |
| 2026-03-28 07:24 | 10,699,722.03 | -277.97 | -0.003% |
| 2026-03-28 07:26 current | 10,697,855.00 | -2,145.00 | -0.020% |

## Assumptions

- Operational ROI baseline uses the live runtime checkpoint initial equity, not the newer config budget.
- Config capital is shown separately because config/daemon.toml currently differs from the running checkpoint.
- Daily and weekly curves are reconstructed from strategy-run snapshots plus current open-position sizes because no historical pnl-snapshots.jsonl file is present.
- The default runtime checkpoint rolled to a different live session during report generation, so this report is anchored to the last frozen snapshot that matched the requested current-assets basis.
- Daily and weekly coverage is short because the relevant deployment snapshot only spans the latest live session window.
- The user-provided current assets differ slightly from the checkpoint equity; the difference is reported as a reconciliation delta.