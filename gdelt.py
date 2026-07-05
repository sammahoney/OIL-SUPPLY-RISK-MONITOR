import time
import requests

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Keywords aimed at catching Hormuz / Gulf shipping disruption coverage.
# Tune this as you see what triggers false positives vs real signal.
HORMUZ_QUERY = (
    '("Strait of Hormuz" OR "Hormuz tanker" OR "Gulf shipping" OR '
    '"tanker attack" OR "oil tanker seized")'
)


def _fetch_timeline(query: str, mode: str, timespan: str = "1d"):
    """
    Low-level GDELT DOC 2.0 API call. No API key needed.
    mode: "timelinevolraw" (article counts) or "timelinetone" (avg sentiment)
    Returns the raw JSON, or None on failure.
    """
    params = {
        "query": query,
        "mode": mode,
        "format": "json",
        "timespan": timespan,
    }

    for attempt in range(2):
        try:
            r = requests.get(GDELT_URL, params=params, timeout=15)
            if r.status_code == 429:
                print(f"GDELT: rate limited ({mode}), waiting before retry...")
                time.sleep(5)
                continue
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            print(f"GDELT: request failed ({mode}) ->", e)
            return None
        except ValueError:
            print(f"GDELT: response was not valid JSON ({mode})")
            return None

    print(f"GDELT: still rate limited ({mode}) after retry, giving up for now")
    return None


def _latest_value(gdelt_json, series_key="timeline"):
    """Pull the most recent data point out of a GDELT timeline response."""
    if not gdelt_json:
        return None
    try:
        series = gdelt_json[series_key][0]["data"]
        if not series:
            return None
        return series[-1]["value"]
    except (KeyError, IndexError, TypeError):
        return None


def get_news_signal(query: str = HORMUZ_QUERY, timespan: str = "1d"):
    """
    Returns a dict with the latest article volume and average tone for
    the query, or None values for anything that failed to fetch.

    volume: raw count of matching articles in the timespan
    tone: average sentiment, roughly -100 (very negative) to +100 (very positive)
    """
    vol_json = _fetch_timeline(query, "timelinevolraw", timespan)
    time.sleep(2)  # space the two calls out to avoid tripping the rate limit
    tone_json = _fetch_timeline(query, "timelinetone", timespan)

    volume = _latest_value(vol_json)
    tone = _latest_value(tone_json)

    if volume is None:
        print("GDELT: could not read article volume from response")
    if tone is None:
        print("GDELT: could not read tone from response")

    return {"volume": volume, "tone": tone}


def news_stress_score(query: str = HORMUZ_QUERY, timespan: str = "1d",
                       baseline_volume: float = 20.0):
    """
    Converts raw GDELT volume + tone into a 0-100 stress score.

    baseline_volume: rough "normal day" article count for this query.
    You should tune this by running get_news_signal() for a week or two
    during a calm period and averaging the volume you see.

    Logic: more articles than baseline = stress. More negative tone = stress.
    Missing data returns None so callers can degrade gracefully.
    """
    signal = get_news_signal(query, timespan)
    volume, tone = signal["volume"], signal["tone"]

    if volume is None and tone is None:
        return None

    volume_score = None
    if volume is not None:
        volume_score = min(100, max(0, (volume / baseline_volume) * 50))

    tone_score = None
    if tone is not None:
        # tone is typically -10 to +10 in practice; very negative = high stress
        tone_score = min(100, max(0, (-tone + 5) * 10))

    parts = [s for s in (volume_score, tone_score) if s is not None]
    if not parts:
        return None

    return sum(parts) / len(parts)


if __name__ == "__main__":
    print(get_news_signal())
    print("Stress score:", news_stress_score())
