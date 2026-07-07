import json
import os
import requests
from datetime import datetime, timedelta, timezone

BASE_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"

# PortWatch has a ~7 day publication lag (confirmed by checking date gaps),
# so there's no value in re-querying more than once a day.
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".chokepoint_cache.json")
CACHE_HOURS = 24


def _read_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except OSError as e:
        print("PortWatch: could not write cache ->", e)


def _cache_entry_is_fresh(entry):
    if not entry or "fetched_at" not in entry:
        return False
    fetched_at = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def list_chokepoint_names(match: str):
    """
    Run this first to discover the exact 'portname' string PortWatch uses
    for a chokepoint, e.g. list_chokepoint_names('Suez') or ('Hormuz').
    Avoids guessing the exact spelling/casing before querying real data.
    """
    params = {
        "where": f"portname LIKE '%{match}%'",
        "outFields": "portid,portname",
        "returnDistinctValues": "true",
        "f": "json",
    }
    r = requests.get(BASE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if "error" in data:
        print("PortWatch API error:", data["error"])
        return []

    names = [f["attributes"] for f in data.get("features", [])]
    for n in names:
        print(n)
    return names


def get_chokepoint_history(portname: str, days: int = 180):
    """
    Fetches daily transit records for a chokepoint over the last `days`
    days. portname must match exactly what list_chokepoint_names() showed
    you (case-sensitive).

    Returns a list of dicts sorted by date, each with n_total, n_tanker,
    n_cargo, etc. for that day.
    """
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "where": f"portname = '{portname}' AND date >= DATE '{since}'",
        "outFields": "date,portname,n_total,n_tanker,n_cargo,n_container,n_dry_bulk,n_general_cargo,n_roro",
        "orderByFields": "date ASC",
        "f": "json",
        "resultRecordCount": 2000,  # comfortably above 180 days of records
    }

    r = requests.get(BASE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if "error" in data:
        print("PortWatch API error:", data["error"])
        return []

    records = [f["attributes"] for f in data.get("features", [])]
    return records


def get_history_table(portname: str, days: int = 90, force_refresh: bool = False):
    """
    Returns the raw daily records for a chokepoint, cached alongside the
    stress calculation cache. Used for table/chart display rather than
    the single-number stress score.
    """
    cache = _read_cache()
    cache_key = f"{portname}_table_{days}"
    entry = cache.get(cache_key)

    if not force_refresh and _cache_entry_is_fresh(entry):
        return entry["result"]

    records = get_chokepoint_history(portname, days=days)
    records = [r for r in records if r.get("date") is not None]

    cache[cache_key] = {"result": records, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write_cache(cache)

    return records


def get_transit_comparison(portname: str, baseline_days: int = 180, force_refresh: bool = False):
    """
    Compares the most recent day's tanker transit count against the
    trailing average (excluding that most recent day). Returns the raw
    numbers only -- no manufactured 0-100 "stress score", since whether
    a given % change counts as concerning is a judgment call, not a fact.
    Cached on disk for CACHE_HOURS since PortWatch data only updates
    roughly daily. Falls back to None if data is missing.
    """
    cache = _read_cache()
    cache_key = f"{portname}_comparison"
    entry = cache.get(cache_key)

    if not force_refresh and _cache_entry_is_fresh(entry):
        return entry["result"]

    records = get_chokepoint_history(portname, days=baseline_days)
    records = [r for r in records if r.get("n_tanker") is not None]

    if len(records) < 8:
        print(f"PortWatch: not enough data for {portname} ({len(records)} valid days)")
        result = {"latest": None, "baseline": None, "pct_change": None}
    else:
        latest_record = records[-1]
        baseline_records = records[:-1]

        latest = latest_record["n_tanker"]
        baseline = sum(r["n_tanker"] for r in baseline_records) / len(baseline_records)

        if baseline == 0:
            result = {"latest": latest, "baseline": baseline, "pct_change": None}
        else:
            pct_change = ((latest - baseline) / baseline) * 100
            result = {
                "latest": latest,
                "latest_date": latest_record.get("date"),
                "baseline": round(baseline, 1),
                "pct_change": round(pct_change, 1),
            }

    cache[cache_key] = {"result": result, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write_cache(cache)

    return result


def get_tanker_transit_history(match: str, days: int = 180):
    """
    Returns [(date_str, n_tanker), ...] for a chokepoint, matched loosely
    by name (e.g. match="Suez" or match="Hormuz") so this doesn't break
    on exact-casing/spelling assumptions. Sorted oldest -> newest.
    """
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = {
        "where": f"portname LIKE '%{match}%' AND date >= DATE '{since}'",
        "outFields": "date,portname,n_tanker",
        "orderByFields": "date ASC",
        "f": "json",
        "resultRecordCount": 2000,
    }

    r = requests.get(BASE_URL, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()

    if "error" in data:
        print("PortWatch API error:", data["error"])
        return []

    results = []
    for f in data.get("features", []):
        attrs = f["attributes"]
        ts_ms = attrs.get("date")
        n_tanker = attrs.get("n_tanker")
        if ts_ms is None or n_tanker is None:
            continue
        date_str = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
        results.append((date_str, n_tanker))

    return results


if __name__ == "__main__":
    print("--- Searching for 'Suez' ---")
    list_chokepoint_names("Suez")

    print("\n--- Searching for 'Hormuz' ---")
    list_chokepoint_names("Hormuz")

    print("\n--- Suez Canal transit comparison ---")
    print(get_transit_comparison("Suez Canal"))

    print("\n--- Strait of Hormuz transit comparison ---")
    print(get_transit_comparison("Strait of Hormuz"))
