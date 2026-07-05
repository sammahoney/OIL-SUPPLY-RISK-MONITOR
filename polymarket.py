import json
import os
import requests
from datetime import datetime, timedelta, timezone

GAMMA_URL = "https://gamma-api.polymarket.com/events"

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".polymarket_cache.json")
CACHE_HOURS = 2  # prediction markets move fast, shorter cache than the daily sources

KEYWORDS = ["hormuz", "iran", "strait", "oil", "tanker"]


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
        print("Polymarket: could not write cache ->", e)


def _cache_is_fresh(entry):
    if not entry or "fetched_at" not in entry:
        return False
    fetched_at = datetime.fromisoformat(entry["fetched_at"])
    return datetime.now(timezone.utc) - fetched_at < timedelta(hours=CACHE_HOURS)


def find_relevant_markets(keywords=None, scan_limit=500, force_refresh=False):
    """
    Pulls the top-volume active events (paginated, since the API caps
    each request at 100 regardless of the limit param) and returns any
    whose title matches one of the keywords, with each market's implied
    "Yes" probability. No API key needed -- fully public endpoint.
    """
    keywords = keywords or KEYWORDS
    cache = _read_cache()
    entry = cache.get("relevant_markets")

    if not force_refresh and _cache_is_fresh(entry):
        return entry["result"]

    events = []
    for offset in range(0, scan_limit, 100):
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume24hr",  # NOT volume_24hr -- matches the JSON field name exactly
            "ascending": "false",
            "limit": 100,
            "offset": offset,
        }
        try:
            r = requests.get(GAMMA_URL, params=params, timeout=15)
            r.raise_for_status()
            batch = r.json()
        except requests.exceptions.RequestException as e:
            print("Polymarket: request failed ->", e)
            batch = []
        except ValueError:
            print("Polymarket: response was not valid JSON")
            batch = []

        if not batch:
            break
        events.extend(batch)

    if not events:
        if entry:
            print("Polymarket: using stale cache")
            return entry["result"]
        return []

    matches = []
    for event in events:
        title = (event.get("title") or "").lower()
        if not any(k in title for k in keywords):
            continue

        for market in event.get("markets", []):
            try:
                outcomes = json.loads(market.get("outcomes", "[]"))
                prices = json.loads(market.get("outcomePrices", "[]"))
            except (json.JSONDecodeError, TypeError):
                continue

            if "Yes" in outcomes:
                yes_price = float(prices[outcomes.index("Yes")])
            elif prices:
                yes_price = float(prices[0])
            else:
                continue

            matches.append({
                "event_title": event.get("title"),
                "market_question": market.get("question"),
                "yes_probability": round(yes_price * 100, 1),
                "volume_24hr": event.get("volume24hr"),
            })

    cache["relevant_markets"] = {"result": matches, "fetched_at": datetime.now(timezone.utc).isoformat()}
    _write_cache(cache)

    return matches


def market_stress_score(force_refresh=False):
    """
    Converts the most relevant, highest-probability matching market into
    a 0-100 stress score. Returns None if nothing relevant is currently
    an active, tradable market (which itself is informative -- it means
    the market doesn't see this as a live risk right now).
    """
    matches = find_relevant_markets(force_refresh=force_refresh)

    if not matches:
        return None

    # Use the single highest implied probability as the score -- if any
    # one market thinks disruption is likely, that's the signal worth
    # surfacing, not an average that dilutes it against unrelated markets.
    top = max(matches, key=lambda m: m["yes_probability"])
    return top["yes_probability"], top


if __name__ == "__main__":
    matches = find_relevant_markets()
    print(f"Found {len(matches)} relevant markets:")
    for m in matches:
        print(f"  {m['yes_probability']}% - {m['market_question']} (24h vol: {m['volume_24hr']})")

    result = market_stress_score()
    if result:
        score, top = result
        print(f"\nTop signal: {score}% - {top['market_question']}")
    else:
        print("\nNo relevant active markets found right now.")
