"""
Alpha Calibrator — backtest 결과 기반 파라미터 자동 조정 모듈

backtest_alpha_filter.py가 생성한 artifacts/alpha-calibration.json을 읽어서
lab loop와 daemon이 최적화된 가중치/임계값을 사용할 수 있게 합니다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

CALIBRATION_PATH = Path("artifacts/alpha-calibration.json")

_logger = logging.getLogger(__name__)


@dataclass
class AlphaCalibration:
    """백테스트로 도출된 Alpha Score 최적 파라미터."""
    rs_weight: float = 0.4
    acc_weight: float = 0.3
    cvd_weight: float = 0.3
    rsi_weight: float = 0.0
    macd_weight: float = 0.0
    atr_weight: float = 0.0
    obv_weight: float = 0.0
    bb_weight: float = 0.0
    threshold: float = 1.0          # watchlist 필터 기준
    verdict: str = "unknown"        # "valid" | "weak" | "invalid" | "unknown"
    avg_edge_6b_pct: float = 0.0    # Alpha>threshold vs 나머지 수익률 차이 (%)
    avg_corr_6b: float = 0.0        # Alpha ↔ 6봉 후 수익률 상관계수
    sample_size: int = 0
    updated_at: str = ""

    @property
    def is_valid(self) -> bool:
        return self.verdict == "valid"

    @property
    def is_usable(self) -> bool:
        """valid 또는 weak이면 사용 (invalid면 기본값 유지)."""
        return self.verdict in ("valid", "weak")

    def to_dict(self) -> dict:
        return asdict(self)


def load_calibration(path: Path = CALIBRATION_PATH) -> AlphaCalibration:
    """calibration JSON 로드. 파일 없으면 기본값 반환."""
    if not path.exists():
        return AlphaCalibration()
    try:
        with path.open() as f:
            data = json.load(f)
        cal = AlphaCalibration(
            rs_weight=float(data.get("rs_weight", 0.4)),
            acc_weight=float(data.get("acc_weight", 0.3)),
            cvd_weight=float(data.get("cvd_weight", 0.3)),
            rsi_weight=float(data.get("rsi_weight", 0.0)),
            macd_weight=float(data.get("macd_weight", 0.0)),
            atr_weight=float(data.get("atr_weight", 0.0)),
            obv_weight=float(data.get("obv_weight", 0.0)),
            bb_weight=float(data.get("bb_weight", 0.0)),
            threshold=float(data.get("threshold", 1.0)),
            verdict=str(data.get("verdict", "unknown")),
            avg_edge_6b_pct=float(data.get("avg_edge_6b_pct", 0.0)),
            avg_corr_6b=float(data.get("avg_corr_6b", 0.0)),
            sample_size=int(data.get("sample_size", 0)),
            updated_at=str(data.get("updated_at", "")),
        )
        _logger.info(
            "AlphaCalibration loaded: verdict=%s threshold=%.2f "
            "weights=(rs=%.2f acc=%.2f cvd=%.2f) edge_6b=%.3f%%",
            cal.verdict, cal.threshold,
            cal.rs_weight, cal.acc_weight, cal.cvd_weight,
            cal.avg_edge_6b_pct,
        )
        return cal
    except Exception as exc:
        _logger.warning("AlphaCalibration load failed (%s), using defaults.", exc)
        return AlphaCalibration()


def save_calibration(cal: AlphaCalibration, path: Path = CALIBRATION_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(cal.to_dict(), f, indent=2)
    _logger.info("AlphaCalibration saved: %s", path)
