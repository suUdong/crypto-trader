"""Tests for compute_macro_bonus.

The reference implementation lives in scripts/market_scan_loop.py, which has
heavy top-level imports (torch, pyupbit, pandas) unsuitable for CI install.
We inline the function here so tests stay portable. If the upstream behavior
changes, update both copies.
"""


def compute_macro_bonus(payload: dict | None) -> float:
    """Mirror of scripts/market_scan_loop.py::compute_macro_bonus.

    Bonuses:
      VIX trend falling   -> +0.2
      DXY trend falling   -> +0.1
      expansionary regime -> +0.3
    Returns 0.0 on None payload or overall_confidence < 0.3.
    """
    if payload is None:
        return 0.0
    confidence = float(payload.get("overall_confidence", 0.0))
    if confidence < 0.3:
        return 0.0
    bonus = 0.0
    try:
        us_signals = payload["layers"]["us"]["signals"]
        vix_trend = str(us_signals.get("vix_trend", ""))
        dxy_trend = str(us_signals.get("dxy_trend", ""))
        if "falling" in vix_trend.lower():
            bonus += 0.2
        if "falling" in dxy_trend.lower():
            bonus += 0.1
    except (KeyError, TypeError):
        pass
    if payload.get("overall_regime") == "expansionary":
        bonus += 0.3
    return round(bonus, 3)


def test_macro_bonus_vix_falling():
    payload = {
        "overall_regime": "neutral",
        "overall_confidence": 0.5,
        "layers": {
            "us": {
                "signals": {
                    "vix_trend": "-17.5% (falling)",
                    "dxy_trend": "-0.6% (falling)",
                }
            }
        },
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # vix_falling(0.2) + dxy_falling(0.1)


def test_macro_bonus_expansionary():
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.6,
        "layers": {"us": {"signals": {"vix_trend": "stable", "dxy_trend": "stable"}}},
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # expansionary(0.3)


def test_macro_bonus_low_confidence_returns_zero():
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.2,
        "layers": {"us": {"signals": {"vix_trend": "-20% (falling)", "dxy_trend": "-1% (falling)"}}},
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.0


def test_macro_bonus_server_down():
    bonus = compute_macro_bonus(None)
    assert bonus == 0.0
