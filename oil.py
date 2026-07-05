import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("EIA_API_KEY", "")


def get_oil_price():

    if not API_KEY:
        print("EIA: no API key set (EIA_API_KEY env var is empty)")
        return None

    url = "https://api.eia.gov/v2/seriesid/PET.RWTC.D"

    params = {
        "api_key": API_KEY,
        "frequency": "daily"
    }

    try:
        r = requests.get(url, params=params, timeout=15)
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


if __name__ == "__main__":
    print("Oil price:", get_oil_price())
