import json
import os
from datetime import datetime, timezone, timedelta

import requests

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_ti_oilm"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".eurostat_trade_cache.json")
CACHE_HOURS = 24

# Confirmed via discover_dimensions():
SIEC_CRUDE_OIL = "O4100_TOT"       # "Crude oil"
UNIT_CODE = "THS_T"                # thousand tonnes, the only option
EU_GEO = "EU27_2020"               # EU as a whole (the importing bloc)

# US and KZ are inferred by pattern (every other country in the 174-entry
# partner list uses plain ISO2), not directly confirmed -- Eurostat is
# known to deviate from ISO2 in a few cases (EL for Greece, UK for the
# United Kingdom, both visible in that same list). If either of these is
# wrong, get_import_history() prints a clear "no data" warning for that
# specific partner rather than failing silently.
PARTNERS = {
    "TOTAL": "EU Total",
    "US": "United States",
    "RU": "Russia",
    "NO": "Norway",
    "KZ": "Kazakhstan",
    "LY": "Libya",
    "SA": "Saudi Arabia",
    "NG": "Nigeria",
    "IQ": "Iraq",
}


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
        print("Eurostat trade: could not write cache ->", e)


def _cache_entry_is_fresh(entry):
    if not entry or "fetched_at" not in entry:
        return False
    fetched_at = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def discover_dimensions():
    """
    Discovery helper -- already run once, codes above are confirmed.
    Kept here in case you need to re-check anything (e.g. if a partner
    code stops returning data after an Eurostat schema change).
    """
    params = {
        "geo": "EU27_2020",
        "format": "JSON",
        "lang": "EN",
        "sinceTimePeriod": "2026-04",
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print("Eurostat trade: request failed ->", e)
        return None
    except ValueError:
        print("Eurostat trade: response was not valid JSON")
        return None

    if "error" in data:
        print("Eurostat trade API error:", data["error"])
        return None

    dims = data.get("dimension", {})
    for dim_id, dim_data in dims.items():
        categories = dim_data.get("category", {}).get("label", {})
        print(f"\nDimension: {dim_id} ({len(categories)} options)")
        items = list(categories.items())
        for code, label in items[:60]:
            print(f"  {code} = {label}")
        if len(items) > 60:
            print(f"  ... and {len(items) - 60} more")

    return dims


def get_import_history(months: int = 9, force_refresh: bool = False):
    """
    Returns {partner_code: {month_str: value_thousand_tonnes}} for
    PARTNERS, over the last `months` months. Crude oil only.
    """
    cache_key = f"imports_{months}"
    cache = _read_cache()
    entry = cache.get(cache_key)

    if not force_refresh and _cache_entry_is_fresh(entry):
        return entry["result"]

    params = {
        "format": "JSON",
        "lang": "EN",
        "geo": EU_GEO,
        "siec": SIEC_CRUDE_OIL,
        "unit": UNIT_CODE,
        "sinceTimePeriod": (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m"),
        "partner": list(PARTNERS.keys()),
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print("Eurostat trade: request failed ->", e)
        return entry["result"] if entry else None
    except ValueError:
        print("Eurostat trade: response was not valid JSON")
        return entry["result"] if entry else None

    if "error" in data:
        print("Eurostat trade API error:", data["error"])
        return entry["result"] if entry else None

    try:
        dim_ids = data["id"]
        sizes = data["size"]
        dims = data["dimension"]

        index_to_code = {}
        for dim_id in dim_ids:
            cat_index = dims[dim_id]["category"]["index"]
            index_to_code[dim_id] = {v: k for k, v in cat_index.items()}

        partner_dim_pos = dim_ids.index("partner")
        time_dim_pos = dim_ids.index("time")

        strides = [1] * len(dim_ids)
        for i in range(len(dim_ids) - 2, -1, -1):
            strides[i] = strides[i + 1] * sizes[i + 1]

        result = {}
        raw_values = data.get("value", {})

        for flat_key, value in raw_values.items():
            flat_index = int(flat_key)
            remaining = flat_index
            coords = []
            for stride in strides:
                coords.append(remaining // stride)
                remaining = remaining % stride

            partner_code = index_to_code[dim_ids[partner_dim_pos]][coords[partner_dim_pos]]
            time_code = index_to_code[dim_ids[time_dim_pos]][coords[time_dim_pos]]

            result.setdefault(partner_code, {})[time_code] = value

    except (KeyError, IndexError, ValueError) as e:
        print("Eurostat trade: could not parse JSON-stat response ->", e)
        return entry["result"] if entry else None

    # Flag any partner that came back with nothing -- likely means the
    # inferred code (US/KZ) was wrong, not that trade volume is zero.
    for code, name in PARTNERS.items():
        if code not in result or not result[code]:
            print(f"Eurostat trade: no data returned for partner '{code}' ({name}) "
                  f"-- code may be wrong, worth double-checking against the full "
                  f"partner list if this line is missing from the chart.")

    cache[cache_key] = {"result": result, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write_cache(cache)

    return result


if __name__ == "__main__":
    print(get_import_history())
