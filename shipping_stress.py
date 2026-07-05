SHIPPING_STRESS_VERSION = "hormuz-only-v2"

from gdelt import news_stress_score
from vessel_api import get_hormuz_vessel_count
from chokepoints import get_tanker_stress

# Redesign: freight rate (manual input, never had a free live source) and
# Suez transit are both dropped. Shipping stress is now just Hormuz transit
# vs its own 180-day baseline (IMF PortWatch) + GDELT news signal.
# VesselAPI's live vessel count stays as a display-only spot check (see
# app.py) -- it has no baseline to compare against and is quota-limited to
# 150 calls/month, so it was never used to feed the score.


def shipping_stress_breakdown():
    """
    Returns a dict with each raw component, each component's score, and the
    final combined score -- so the dashboard can show what's actually
    driving the number instead of one opaque figure.
    """
    gdelt_score = news_stress_score()
    hormuz = get_tanker_stress("Strait of Hormuz")

    weights_and_scores = [
        ("hormuz_transit", 0.6, hormuz["score"]),
        ("news", 0.4, gdelt_score),
    ]

    valid = [(w, s) for _, w, s in weights_and_scores if s is not None]

    combined = None
    if valid:
        total_weight = sum(w for w, _ in valid)
        weighted_sum = sum(w * s for w, s in valid)
        combined = weighted_sum / total_weight

    return {
        "combined": combined,
        "hormuz_transit_score": hormuz["score"],
        "hormuz_transit_latest": hormuz["latest"],
        "hormuz_transit_baseline": hormuz["baseline"],
        "hormuz_transit_pct_change": hormuz["pct_change"],
        "hormuz_live_vessel_count": get_hormuz_vessel_count(),  # display only, not scored
        "news_score": gdelt_score,
    }


def shipping_stress():
    """
    Combined shipping stress score (0-100): Hormuz transit stress vs
    180-day baseline (IMF PortWatch, ~7 day lag) + GDELT news volume/tone.
    Returns None only if both components are unavailable.
    """
    return shipping_stress_breakdown()["combined"]


if __name__ == "__main__":
    print("Shipping stress breakdown:", shipping_stress_breakdown())
