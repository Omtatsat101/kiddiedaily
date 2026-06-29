#!/usr/bin/env python3
"""
KiddieDaily Extended Source Run — Afternoon Edition
Patches the morning scraper with 12 additional science/global RSS sources
and runs a second scrape session targeting afternoon publication (15:00 UTC).

How this works:
  1. Imports scrape_and_push (which has the core scraping engine)
  2. Extends SOURCES + SCIENCE_SOURCES with quality additions
  3. Raises MAX_ARTICLES to allow up to 5 afternoon articles
  4. Calls scrape_and_push.main() — fully reuses dedup, bias scoring,
     Claude rewrite, bias bar, manifest, and news index update logic

Deployed to repo root so GitHub Actions can find it next to scrape_and_push.py.
"""
import scrape_and_push as s

# ── Additional RSS sources (science, global neutral, educational) ─────────────
AFTERNOON_SOURCES = [
    # Neutral global news
    {"name": "Reuters",        "url": "https://feeds.reuters.com/reuters/topNews",                  "bias":  0.0, "icon": "\U0001f4f0"},  # 📰
    {"name": "PBS NewsHour",   "url": "https://www.pbs.org/newshour/feeds/rss/headlines",           "bias": -0.2, "icon": "\U0001f4fa"},  # 📺

    # Science publishers
    {"name": "PhysOrg",        "url": "https://phys.org/rss-feed/",                                "bias":  0.0, "icon": "⚛️"}, # ⚛️
    {"name": "Science News",   "url": "https://www.sciencenews.org/feed",                           "bias":  0.0, "icon": "\U0001f4d6"},  # 📖
    {"name": "MIT News",       "url": "https://news.mit.edu/rss/feed",                             "bias":  0.0, "icon": "\U0001f393"},  # 🎓
    {"name": "EurekAlert",     "url": "https://www.eurekalert.org/rss.xml",                        "bias":  0.0, "icon": "\U0001f52d"},  # 🔭
    {"name": "Wired Science",  "url": "https://www.wired.com/feed/category/science/latest/rss",    "bias": -0.3, "icon": "\U0001f4a1"},  # 💡

    # Space
    {"name": "NASA JPL",       "url": "https://www.jpl.nasa.gov/feeds/news",                       "bias":  0.0, "icon": "\U0001fa90"},  # 🪐
    {"name": "ESA News",       "url": "https://www.esa.int/rssfeed/Our_Activities/Space_Science",  "bias":  0.0, "icon": "\U0001f30c"},  # 🌌

    # Fun & educational
    {"name": "Mental Floss",   "url": "https://www.mentalfloss.com/rss.xml",                       "bias":  0.0, "icon": "\U0001f9e0"},  # 🧠
    {"name": "Atlas Obscura",  "url": "https://www.atlasobscura.com/feeds/latest",                 "bias":  0.0, "icon": "\U0001f5fa️"}, # 🗺️

    # Weather / environment
    {"name": "NOAA",           "url": "https://www.noaa.gov/media-advisory.rss",                   "bias":  0.0, "icon": "\U0001f30a"},  # 🌊
]

# Patch the module-level SOURCES list so main() picks up all sources
s.SOURCES = s.SOURCES + AFTERNOON_SOURCES

# Extend SCIENCE_SOURCES so afternoon science articles get the is_science=True flag
s.SCIENCE_SOURCES = s.SCIENCE_SOURCES | {
    "PhysOrg", "Science News", "MIT News", "EurekAlert", "NASA JPL", "ESA News", "Wired Science"
}

# Allow more articles per afternoon run (morning is capped at 3)
s.MAX_ARTICLES = 5

if __name__ == "__main__":
    s.main()
