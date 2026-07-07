import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("EIA_API_KEY", "")
SERIES_URL = "https://api.eia.gov/v2/seriesid/PET.RWTC.D"


def get_oil_price():

    if not API_KEY:
        print("EIA: no API key set (EIA_API_KEY env var is empty)")
        return None

    params = {
        "api_key": API_KEY,
        "frequency": "daily"
    }

    try:
        r = requests.get(SERIES_URL, params=params, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("EIA: request failed ->", e)
        return None

    try:
        data = r.json()
        series = data["response"]["data"]
    except (ValueError, KeyError):
        print("EIA: unexpected response format ->", r.text[:200])
        return None

    if not series:
        print("EIA: no oil price data returned")
        return None

    latest = series[0]

    try:
        return float(latest["value"])
    except (KeyError, TypeError, ValueError):
        print("EIA: could not parse price value from response")
        return None


def get_oil_price_history(days: int = 365):
    """
    Returns a list of {"date": "YYYY-MM-DD", "price": float} for the last
    `days` days, oldest first. WTI has no weekend/holiday data, so a
    365-day window is roughly ~250 rows, not 365.
    """
    if not API_KEY:
        print("EIA: no API key set (EIA_API_KEY env var is empty)")
        return []

    params = {
        "api_key": API_KEY,
        "frequency": "daily",
        "length": 500,  # comfortably more than a year of trading days
    }

    try:
        r = requests.get(SERIES_URL, params=params, timeout=15)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("EIA: request failed ->", e)
        return []

    try:
        data = r.json()
        series = data["response"]["data"]
    except (ValueError, KeyError):
        print("EIA: unexpected response format ->", r.text[:200])
        return []

    if not series:
        return []

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    records = []
    for row in series:
        period = row.get("period")
        value = row.get("value")
        if period is None or value is None or period < cutoff:
            continue
        try:
            records.append({"date": period, "price": float(value)})
        except (TypeError, ValueError):
            continue

    records.sort(key=lambda r: r["date"])
    return records


if __name__ == "__main__":
    print("Oil price:", get_oil_price())
    history = get_oil_price_history()
    print(f"History: {len(history)} records, "
          f"{history[0] if history else None} .. {history[-1] if history else None}")
