"""
Historical candle data loader for Upbit bulk-downloaded ZIP files.

Directory structure:
  data/historical/monthly/{ctype}/{year}/KRW-{SYMBOL}_candle-{ctype}_{YYYYMM}.zip

Usage:
  from scripts.historical_loader import load_historical
  df = load_historical("KRW-BTC", "240m", "2022-01-01", "2026-12-31")
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from datetime import datetime

import pandas as pd

HISTORICAL_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"


def load_historical(
    market: str,
    ctype: str,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load candle data from monthly ZIP files into a DataFrame.

    Args:
        market: e.g. "KRW-BTC"
        ctype:  candle type, e.g. "240m", "day", "60m"
        start:  ISO date string, e.g. "2022-01-01"
        end:    ISO date string, e.g. "2026-12-31"

    Returns:
        DataFrame indexed by UTC datetime with columns:
        open, high, low, close, volume
    """
    start_dt = pd.Timestamp(start) if start else pd.Timestamp("2000-01-01")
    end_dt = pd.Timestamp(end) if end else pd.Timestamp.now(tz="UTC").tz_localize(None)

    base = HISTORICAL_DIR / "monthly" / ctype
    if not base.exists():
        raise FileNotFoundError(f"No data directory: {base}")

    frames: list[pd.DataFrame] = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name)
        except ValueError:
            continue
        if year < start_dt.year or year > end_dt.year:
            continue

        pattern = f"{market}_candle-{ctype}_{year}*.zip"
        for zpath in sorted(year_dir.glob(pattern)):
            # Extract YYYYMM from filename to skip out-of-range months early
            stem = zpath.stem  # e.g. KRW-BTC_candle-240m_202401
            yyyymm = stem.rsplit("_", 1)[-1]
            if len(yyyymm) == 6:
                month_start = pd.Timestamp(f"{yyyymm[:4]}-{yyyymm[4:6]}-01")
                if month_start > end_dt or month_start.replace(day=28) < start_dt.replace(day=1):
                    continue

            try:
                with zipfile.ZipFile(zpath) as zf:
                    csv_name = zf.namelist()[0]
                    with zf.open(csv_name) as f:
                        df = pd.read_csv(f, parse_dates=["date_time_utc"])
                        df = df.rename(columns={
                            "date_time_utc": "datetime",
                            "acc_trade_volume": "volume",
                        })
                        df = df.set_index("datetime")[["open", "high", "low", "close", "volume"]]
                        frames.append(df)
            except Exception:
                continue

    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    result = pd.concat(frames).sort_index()
    result = result[~result.index.duplicated(keep="first")]
    if start:
        result = result[result.index >= start_dt]
    if end:
        result = result[result.index <= end_dt]
    return result


def get_available_symbols(ctype: str = "240m", year: int = 2024) -> list[str]:
    """Return KRW symbols that have historical data for given ctype and year."""
    base = HISTORICAL_DIR / "monthly" / ctype / str(year)
    if not base.exists():
        return []
    seen: set[str] = set()
    for zpath in base.iterdir():
        if zpath.suffix != ".zip":
            continue
        market = zpath.name.split("_candle-")[0]
        seen.add(market)
    return sorted(seen)


if __name__ == "__main__":
    import sys
    market = sys.argv[1] if len(sys.argv) > 1 else "KRW-BCH"
    ctype = sys.argv[2] if len(sys.argv) > 2 else "240m"
    df = load_historical(market, ctype, "2022-01-01")
    print(f"{market} {ctype}: {len(df)} rows")
    print(df.head(3))
    print(df.tail(3))
