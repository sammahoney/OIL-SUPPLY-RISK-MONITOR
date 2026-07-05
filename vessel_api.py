import json
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.vesselapi.com"
API_KEY = os.environ.get("VESSELAPI_KEY", "")

# Strait of Hormuz chokepoint. VesselAPI caps boxes at |dLat| + |dLon| <= 4,
# so this is tighter than the old AISStream box (which summed to 6 and
# would be rejected outright here).
BBOX = {
    "lonLeft": 56.0,
    "lonRight": 57.0,
    "latBottom": 26.0,
    "latTop": 27.0,
}

# Disk cache so the count survives your app being relaunched (a fresh
# Python process has no memory of previous calls). This is the main
# defense against burning through the 150/month quota.
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".vessel_cache.json")

# 150 calls/month ≈ 5/day. Caching for 8 hours caps you at 3 calls/day
# (~90/month) with headroom for manual refreshes and the odd retry.
CACHE_HOURS = 8


def _read_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(count):
    data = {
        "count": count,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except OSError as e:
        print("VesselAPI: could not write cache file ->", e)


def _cache_is_fresh(cache):
    if not cache or "fetched_at" not in cache:
        return False
    fetched_at = datetime.fromisoformat(cache["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def _fetch_live_count():
    if not API_KEY:
        print("VesselAPI: no API key set (VESSELAPI_KEY env var is empty)")
        return None

    now = datetime.now(timezone.utc)
    params = {
        "filter.lonLeft": BBOX["lonLeft"],
        "filter.lonRight": BBOX["lonRight"],
        "filter.latBottom": BBOX["latBottom"],
        "filter.latTop": BBOX["latTop"],
        "time.from": (now - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time.to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pagination.limit": 50,
    }
    headers = {"Authorization": f"Bearer {API_KEY}"}

    try:
        r = requests.get(
            f"{BASE_URL}/v1/location/vessels/bounding-box",
            params=params,
            headers=headers,
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        print("VesselAPI: request failed ->", e)
        return None

    remaining = r.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        print(f"VesselAPI: calls remaining this month: {remaining}")

    if r.status_code == 429:
        print("VesselAPI: rate limited (monthly quota likely exhausted) ->", r.text[:200])
        return None
    if r.status_code == 403:
        retry_after = r.headers.get("Retry-After", "unknown")
        print(f"VesselAPI: key temporarily suspended, retry after {retry_after}")
        return None
    if r.status_code != 200:
        print(f"VesselAPI: unexpected status {r.status_code} ->", r.text[:200])
        return None

    try:
        data = r.json()
        vessels = data.get("vessels", [])
    except (json.JSONDecodeError, AttributeError):
        print("VesselAPI: could not parse response JSON")
        return None

    # NOTE: pagination.limit caps this at 50 per call. If you need a true
    # total beyond 50, you'd have to page through nextToken -- but that
    # burns extra quota fast, so for a stress *indicator* (not a precise
    # census) capping at 50 is the right tradeoff here.
    return len(vessels)


def get_hormuz_vessel_count(force_refresh: bool = False):
    """
    Returns the vessel count for the Hormuz bounding box, using an
    8-hour disk cache to conserve the 150 calls/month free tier.
    Returns None if no live or cached data is available.
    """
    cache = _read_cache()

    if not force_refresh and _cache_is_fresh(cache):
        print(f"VesselAPI: using cached count from {cache['fetched_at']}")
        return cache["count"]

    count = _fetch_live_count()

    if count is not None:
        _write_cache(count)
        return count

    # Live fetch failed (rate limited, network issue, etc.) -- fall back
    # to a stale cache rather than returning nothing, if one exists.
    if cache is not None:
        print(f"VesselAPI: live fetch failed, using stale cache from {cache['fetched_at']}")
        return cache["count"]

    return None


if __name__ == "__main__":
    print("Vessel count:", get_hormuz_vessel_count())
