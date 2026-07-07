import requests

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Keywords aimed at catching Hormuz / Gulf shipping disruption coverage.
HORMUZ_QUERY = (
    '("Strait of Hormuz" OR "Hormuz tanker" OR "Gulf shipping" OR '
    '"tanker attack" OR "oil tanker seized")'
)


def get_recent_headlines(query: str = HORMUZ_QUERY, limit: int = 8, timespan: str = "3d"):
    """
    Returns up to `limit` recent headlines matching the query -- just
    title, source, and date, no links (this is for a quick glance at
    what's being said, not for reading articles) and no scoring. GDELT's
    'artlist' mode returns actual article records instead of an
    aggregated volume/tone number.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "timespan": timespan,
        "maxrecords": limit,
        "sort": "datedesc",
    }

    try:
        r = requests.get(GDELT_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        print("GDELT: request failed ->", e)
        return []
    except ValueError:
        print("GDELT: response was not valid JSON")
        return []

    articles = data.get("articles", [])

    headlines = []
    for a in articles[:limit]:
        headlines.append({
            "title": a.get("title"),
            "source": a.get("domain"),
            "date": a.get("seendate"),
        })

    return headlines


if __name__ == "__main__":
    for h in get_recent_headlines():
        print(f"[{h['date']}] {h['source']}: {h['title']}")
