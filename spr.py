import json
import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("EIA_API_KEY", "")
SERIES_URL = "https://api.eia.gov/v2/seriesid/PET.WCSSTUS1.W"  # weekly SPR stocks, thousand barrels

# Authorized DOE storage capacity, ~714 million barrels. This is a stable,
# rarely-changed policy figure (not weekly data), so it's a constant here
# rather than something we compute -- source: EIA / DOE public reporting.
CAPACITY_MILLION_BBL = 714

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spr_cache.json")
CACHE_HOURS = 24  # weekly data -- no value in checking more than once a day


def _read_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(result):
    data = {"result": result, "fetched_at": datetime.now(timezone.utc).isoformat()}
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except OSError as e:
        print("SPR: could not write cache ->", e)


def _cache_is_fresh(cache):
    if not cache or "fetched_at" not in cache:
        return False
    fetched_at = datetime.fromisoformat(cache["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def _fetch_live():
    if not API_KEY:
        print("SPR: no API key set (EIA_API_KEY env var is empty)")
        return None

    params = {
        "api_key": API_KEY,
        "frequency": "weekly",
        "length": 5000,  # pull full history (~2300 weeks since 1982) in one call
    }

    try:
        r = requests.get(SERIES_URL, params=params, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("SPR: request failed ->", e)
        return None

    try:
        data = r.json()
        series = data["response"]["data"]
    except (ValueError, KeyError):
        print("SPR: unexpected response format ->", r.text[:200])
        return None

    if not series:
        print("SPR: no data returned")
        return None

    try:
        # EIA reports thousand barrels; convert to million barrels throughout.
        values = [float(row["value"]) / 1000 for row in series if row.get("value") is not None]
    except (KeyError, TypeError, ValueError):
        print("SPR: could not parse values from response")
        return None

    if not values:
        return None

    current = values[0]  # newest first, same ordering assumption as oil.py
    previous = values[1] if len(values) > 1 else None
    week_over_week = (current - previous) if previous is not None else None

    all_time_high = max(values)
    all_time_low = min(values)
    utilization_pct = (current / CAPACITY_MILLION_BBL) * 100

    return {
        "current_million_bbl": round(current, 1),
        "capacity_million_bbl": CAPACITY_MILLION_BBL,
        "utilization_pct": round(utilization_pct, 1),
        "week_over_week_million_bbl": round(week_over_week, 2) if week_over_week is not None else None,
        "all_time_high_million_bbl": round(all_time_high, 1),
        "all_time_low_million_bbl": round(all_time_low, 1),
        "all_time_high_pct": round((all_time_high / CAPACITY_MILLION_BBL) * 100, 1),
        "all_time_low_pct": round((all_time_low / CAPACITY_MILLION_BBL) * 100, 1),
    }


def get_spr_status(force_refresh: bool = False):
    """
    Returns current SPR level plus all-time high/low, computed from the
    full available EIA weekly history. Cached to disk for 24h since this
    is weekly data. Falls back to stale cache if a live fetch fails.
    """
    cache = _read_cache()

    if not force_refresh and _cache_is_fresh(cache):
        return cache["result"]

    result = _fetch_live()

    if result is not None:
        _write_cache(result)
        return result

    if cache is not None:
        print(f"SPR: live fetch failed, using stale cache from {cache['fetched_at']}")
        return cache["result"]

    return None


if __name__ == "__main__":
    print(get_spr_status())
