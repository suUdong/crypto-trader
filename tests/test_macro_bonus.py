import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

def test_macro_bonus_vix_falling():
    from autonomous_lab_loop import compute_macro_bonus
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
        }
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # vix_falling(0.2) + dxy_falling(0.1)

def test_macro_bonus_expansionary():
    from autonomous_lab_loop import compute_macro_bonus
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.6,
        "layers": {"us": {"signals": {"vix_trend": "stable", "dxy_trend": "stable"}}}
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.3  # expansionary(0.3)

def test_macro_bonus_low_confidence_returns_zero():
    from autonomous_lab_loop import compute_macro_bonus
    payload = {
        "overall_regime": "expansionary",
        "overall_confidence": 0.2,
        "layers": {"us": {"signals": {"vix_trend": "-20% (falling)", "dxy_trend": "-1% (falling)"}}}
    }
    bonus = compute_macro_bonus(payload)
    assert bonus == 0.0

def test_macro_bonus_server_down():
    from autonomous_lab_loop import compute_macro_bonus
    bonus = compute_macro_bonus(None)
    assert bonus == 0.0
