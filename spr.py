import json
import os
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("EIA_API_KEY", "")
SERIES_URL = "https://api.eia.gov/v2/seriesid/PET.WCSSTUS1.W"  # weekly SPR stocks, thousand barrels

# Authorized DOE storage capacity, ~714 million barrels. Stable, rarely
# changed policy figure, not weekly data -- a constant here rather than
# something we compute. Source: EIA / DOE public reporting.
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
    # Guard against a cache file written by an older version of this
    # module with a different result shape (e.g. missing "series" after
    # this function was added) -- treat a shape mismatch as stale rather
    # than trusting it and crashing downstream.
    if "series" not in cache.get("result", {}):
        return False
    fetched_at = datetime.fromisoformat(cache["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def _fetch_full_data():
    """
    Single fetch that returns everything: the full weekly series since
    1982 (for charting and for computing genuine all-time high/low) plus
    the derived summary stats. Cached as one object so get_spr_status()
    and get_spr_history() don't need separate API calls or cache entries.
    """
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
        series_raw = data["response"]["data"]
    except (ValueError, KeyError):
        print("SPR: unexpected response format ->", r.text[:200])
        return None

    if not series_raw:
        print("SPR: no data returned")
        return None

    # EIA reports thousand barrels; convert to million barrels throughout.
    # series_raw is newest-first (same ordering assumption as oil.py).
    series = []
    for row in series_raw:
        period = row.get("period")
        value = row.get("value")
        if period is None or value is None:
            continue
        try:
            series.append({"date": period, "value_million_bbl": float(value) / 1000})
        except (TypeError, ValueError):
            continue

    if not series:
        return None

    series.sort(key=lambda r: r["date"])  # oldest first, for charting

    values = [r["value_million_bbl"] for r in series]
    current = series[-1]["value_million_bbl"]
    previous = series[-2]["value_million_bbl"] if len(series) > 1 else None
    week_over_week = (current - previous) if previous is not None else None

    all_time_high = max(values)
    all_time_low = min(values)
    utilization_pct = (current / CAPACITY_MILLION_BBL) * 100

    return {
        "series": series,  # full history, oldest first
        "current_million_bbl": round(current, 1),
        "capacity_million_bbl": CAPACITY_MILLION_BBL,
        "utilization_pct": round(utilization_pct, 1),
        "week_over_week_million_bbl": round(week_over_week, 2) if week_over_week is not None else None,
        "all_time_high_million_bbl": round(all_time_high, 1),
        "all_time_low_million_bbl": round(all_time_low, 1),
        "all_time_high_pct": round((all_time_high / CAPACITY_MILLION_BBL) * 100, 1),
        "all_time_low_pct": round((all_time_low / CAPACITY_MILLION_BBL) * 100, 1),
    }


def _get_cached_full_data(force_refresh: bool = False):
    cache = _read_cache()

    if not force_refresh and _cache_is_fresh(cache):
        return cache["result"]

    result = _fetch_full_data()

    if result is not None:
        _write_cache(result)
        return result

    if cache is not None:
        print(f"SPR: live fetch failed, using stale cache from {cache['fetched_at']}")
        return cache["result"]

    return None


def get_spr_status(force_refresh: bool = False):
    """
    Returns current SPR level plus all-time high/low. Same shape as
    before (callers that only used the summary fields are unaffected by
    the addition of a "series" key).
    """
    return _get_cached_full_data(force_refresh=force_refresh)


def get_spr_history(years: int = 3, force_refresh: bool = False):
    """
    Returns {"series": [{"date", "value_million_bbl"}, ...]} for the
    trailing `years` years, plus the genuine all-time high/low (computed
    from the FULL history, not just the windowed slice -- the real
    all-time high was in 2009, well outside any recent window).
    """
    data = _get_cached_full_data(force_refresh=force_refresh)
    if not data:
        return None

    cutoff = (datetime.utcnow() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    windowed = [r for r in data["series"] if r["date"] >= cutoff]

    return {
        "series": windowed,
        "all_time_high_million_bbl": data["all_time_high_million_bbl"],
        "all_time_low_million_bbl": data["all_time_low_million_bbl"],
    }


if __name__ == "__main__":
    status = get_spr_status()
    print("Status:", {k: v for k, v in status.items() if k != "series"})
    history = get_spr_history(years=3)
    print(f"History: {len(history['series'])} weekly points, "
          f"all-time high {history['all_time_high_million_bbl']}M, "
          f"all-time low {history['all_time_low_million_bbl']}M")
