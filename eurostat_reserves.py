import json
import os
from datetime import datetime, timezone, timedelta

import requests

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_stk_oem"

# Countries shown in the comparison chart: Croatia + a handful of EU
# neighbors, matching the mockup legend (Germany, France, Croatia, Italy,
# Hungary).
COUNTRIES = ["DE", "FR", "HR", "IT", "HU"]

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".eurostat_cache.json")
CACHE_HOURS = 24  # monthly data with a multi-month publication lag -- no need to check often


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
        print("Eurostat: could not write cache ->", e)


def _cache_entry_is_fresh(entry):
    if not entry or "fetched_at" not in entry:
        return False
    fetched_at = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def discover_dimensions():
    """
    RUN THIS FIRST. nrg_stk_oem is a multi-dimensional "cube" dataset
    (JSON-stat format), not a flat table -- it has dimensions like
    stock indicator (siec) and flow type (stk_flow) whose exact codes
    aren't guessable from the outside. This fetches the dataset filtered
    to just Croatia, with NO other filters, so the response's dimension
    metadata shows every valid code. Print output tells you what to plug
    into STK_FLOW_CODE / PRODUCT_CODE below.
    """
    params = {"geo": "HR", "format": "JSON", "lang": "EN"}

    try:
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print("Eurostat: request failed ->", e)
        return None
    except ValueError:
        print("Eurostat: response was not valid JSON")
        return None

    if "error" in data:
        print("Eurostat API error:", data["error"])
        return None

    dims = data.get("dimension", {})
    for dim_id, dim_data in dims.items():
        categories = dim_data.get("category", {}).get("label", {})
        print(f"\nDimension: {dim_id}")
        for code, label in categories.items():
            print(f"  {code} = {label}")

    return dims


# Discovered via discover_dimensions() -- this dataset has no product
# (siec) breakdown at all, just stk_flow + unit + geo + time.
# STK_EUE_DIR = "Emergency Stocks held by the MS in accordance with the EU
# Directive (in Days Equivalent)" -- exactly the days-of-cover metric we want.
# unit=NR selects the "Number" (days) version, not THS_T (thousand tonnes).
STK_FLOW_CODE = "STK_EUE_DIR"
UNIT_CODE = "NR"


def _parse_jsonstat(data):
    """
    Minimal JSON-stat cube parser: turns the sparse 'value' dict into
    {geo: {time: value}} using the dimension order/size arrays.
    """
    dim_ids = data["id"]
    sizes = data["size"]
    dims = data["dimension"]

    # category index (0,1,2...) -> actual code, per dimension
    index_to_code = {}
    for dim_id in dim_ids:
        cat_index = dims[dim_id]["category"]["index"]
        index_to_code[dim_id] = {v: k for k, v in cat_index.items()}

    geo_dim_pos = dim_ids.index("geo")
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

        geo_code = index_to_code[dim_ids[geo_dim_pos]][coords[geo_dim_pos]]
        time_code = index_to_code[dim_ids[time_dim_pos]][coords[time_dim_pos]]

        result.setdefault(geo_code, {})[time_code] = value

    return result


def get_reserves_history(months: int = 9, force_refresh: bool = False):
    """
    Returns {country_code: {month_str: value}} for COUNTRIES, over the
    last `months` months. Requires STK_FLOW_CODE and PRODUCT_CODE to be
    set (run discover_dimensions() first).
    """
    if STK_FLOW_CODE is None or UNIT_CODE is None:
        print("Eurostat: STK_FLOW_CODE / UNIT_CODE not set yet -- "
              "run discover_dimensions() and fill them in before calling this.")
        return None

    cache_key = f"reserves_{months}"
    cache = _read_cache()
    entry = cache.get(cache_key)

    if not force_refresh and _cache_entry_is_fresh(entry):
        return entry["result"]

    params = {
        "format": "JSON",
        "lang": "EN",
        "stk_flow": STK_FLOW_CODE,
        "unit": UNIT_CODE,
        "sinceTimePeriod": (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m"),
        "geo": COUNTRIES,  # requests repeats geo= for each list item
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print("Eurostat: request failed ->", e)
        return entry["result"] if entry else None
    except ValueError:
        print("Eurostat: response was not valid JSON")
        return entry["result"] if entry else None

    if "error" in data:
        print("Eurostat API error:", data["error"])
        return entry["result"] if entry else None

    try:
        result = _parse_jsonstat(data)
    except (KeyError, IndexError, ValueError) as e:
        print("Eurostat: could not parse JSON-stat response ->", e)
        return entry["result"] if entry else None

    cache[cache_key] = {"result": result, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write_cache(cache)

    return result


if __name__ == "__main__":
    print("--- Discovering valid dimension codes for nrg_stk_oem ---")
    discover_dimensions()
    print(f"\nUsing STK_FLOW_CODE={STK_FLOW_CODE!r}, UNIT_CODE={UNIT_CODE!r}")
    print("\n--- Testing get_reserves_history() ---")
    print(get_reserves_history())
