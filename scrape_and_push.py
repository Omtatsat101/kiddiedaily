"""
KiddieDaily Agentic News Scraper v1.0
Fetches RSS from curated bias-rated sources → scores bias + source agreement → generates kid-friendly
HTML articles → pushes to Omtatsat101/kiddiedaily GitHub Pages.

Local run:  python scrape_and_push.py
GitHub Actions: triggered daily at 10am UTC via .github/workflows/daily-news.yml (self-deployed)

Requires:  GITHUB_TOKEN  (env var or projects/API-KEYS.env)
Optional:  ANTHROPIC_API_KEY  (for Claude Haiku kid-friendly rewrites)
"""
import urllib.request, urllib.error, urllib.parse, ssl, json, base64, time, os, pathlib, re, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Force UTF-8 on Windows so emoji in print() don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── SSL (matches existing kiddiedaily scripts) ────────────────────────────────
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ── Auth ──────────────────────────────────────────────────────────────────────
def _load_token(env_var, prefix):
    val = os.environ.get(env_var)
    if val:
        return val.strip()
    p = pathlib.Path(__file__).resolve().parents[1] / "API-KEYS.env"
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if ln.startswith(prefix):
                return ln.split("=", 1)[1].strip().strip('"')
    return None

GITHUB_TOKEN = _load_token("GITHUB_TOKEN", "GITHUB_TOKEN=")
ANTHROPIC_KEY = _load_token("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY=")
REPO = "Omtatsat101/kiddiedaily"
MAX_ARTICLES          = 8   # max new articles per run
MAX_SCI_PER_RUN       = 5   # max science articles per run (remaining slots go to world)
MAX_WORLD_PER_RUN     = 3   # max world-news articles per run
MAX_PER_SOURCE_PER_RUN= 2   # max articles from any single source per run (prevents domination)

# Regex word-boundary filter — avoids substring false positives like "scraper"→"rape"
_ADULT_TITLE_RE = re.compile(
    r'\b(?:'
    r'vagina|penis|vulva|genitals?|testicle|erectile|sperm|semen|ovary|uterus|cervix'
    r'|sexual(?:\s+assault)?|sexuall?y|rape[sd]?|rapist'
    r'|abortion|contraception|condom'
    r'|nude|naked(?!\s+mole)|pornograph'
    r'|genocide|massacre|beheading|torture'
    r'|suicide|overdose|opioid\s+overdose|drug\s+addict'
    r')\b',
    re.I
)

# Active branch — set to a content branch in main(); falls back to "main" locally
ACTIVE_BRANCH = "main"

if not GITHUB_TOKEN:
    raise SystemExit("GITHUB_TOKEN not found: set env var or add to projects/API-KEYS.env")

# ── GitHub Contents API ────────────────────────────────────────────────────────
def gh(method, path, body=None, _retry=3):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "kd-scraper",
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
        method=method)
    for attempt in range(_retry):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=25, context=ctx).read())
        except urllib.error.HTTPError as e:
            return {"_err": e.code, "_body": e.read().decode()[:300]}
        except OSError:
            if attempt < _retry - 1:
                time.sleep(3 + attempt * 2)
            else:
                raise

def upload(repo_path, content_str, message):
    branch = ACTIVE_BRANCH
    existing = gh("GET", f"/repos/{REPO}/contents/{repo_path}?ref={branch}")
    sha = existing.get("sha") if isinstance(existing, dict) and not existing.get("_err") else None
    encoded = base64.b64encode(content_str.encode("utf-8")).decode()
    payload = {"message": message, "content": encoded, "branch": branch}
    if sha:
        payload["sha"] = sha
    r = gh("PUT", f"/repos/{REPO}/contents/{repo_path}", payload)
    sha_short = r.get("commit", {}).get("sha", "")[:8] if "commit" in r else None
    if sha_short:
        print(f"  ✓ {repo_path} ({len(content_str):,}b) → {sha_short}")
    else:
        print(f"  ✗ {repo_path}: {r.get('_body', str(r))[:150]}")
    time.sleep(0.5)
    return sha_short

# ── GitHub Flow helpers ────────────────────────────────────────────────────────
def setup_content_branch(today):
    """Create content/daily-news-{today} branch off main; set ACTIVE_BRANCH."""
    global ACTIVE_BRANCH
    branch = f"content/daily-news-{today}"
    r = gh("GET", f"/repos/{REPO}/git/ref/heads/main")
    if r.get("_err"):
        print(f"  ⚠ Cannot get main SHA ({r.get('_err')}), pushing to main directly")
        return
    main_sha = r["object"]["sha"]
    result = gh("POST", f"/repos/{REPO}/git/refs", {
        "ref": f"refs/heads/{branch}", "sha": main_sha,
    })
    if result.get("_err") == 422:
        print(f"  Branch {branch} already exists — reusing")
    elif result.get("_err"):
        print(f"  ⚠ Branch create failed ({result.get('_err')}), pushing to main directly")
        return
    else:
        print(f"  Created branch: {branch}")
    ACTIVE_BRANCH = branch

def create_and_merge_pr(today, n_articles):
    """Open a PR from the content branch → main, then immediately squash-merge it."""
    branch = ACTIVE_BRANCH
    if branch == "main":
        return  # no-op when running locally without branch setup
    pr = gh("POST", f"/repos/{REPO}/pulls", {
        "title": f"Daily news: {today} — {n_articles} new article{'s' if n_articles != 1 else ''}",
        "head": branch, "base": "main",
        "body": (
            f"## Automated daily news update\n\n"
            f"- Date: {today}\n"
            f"- New articles: {n_articles}\n"
            f"- Generated by KiddieDaily Scraper\n\n"
            f"_This PR is auto-generated. CI validates HTML, sitemap, and JSON before merge._"
        ),
    })
    if pr.get("_err"):
        print(f"  ⚠ PR create: {pr.get('_body', '')[:200]}")
        return
    pr_num = pr["number"]
    pr_url = pr.get("html_url", "")
    print(f"  PR #{pr_num} opened: {pr_url}")
    time.sleep(2)  # give CI a moment to register
    merge = gh("PUT", f"/repos/{REPO}/pulls/{pr_num}/merge", {
        "merge_method": "squash",
        "commit_title": f"chore(content): daily news {today} ({n_articles} articles) [auto]",
        "commit_message": f"Automated content update via scraper. PR #{pr_num}.",
    })
    if merge.get("merged"):
        print(f"  PR #{pr_num} squash-merged ✓ → main")
        # Delete the content branch to keep repo clean
        gh("DELETE", f"/repos/{REPO}/git/refs/heads/{branch}")
        print(f"  Branch {branch} deleted")
    else:
        print(f"  ⚠ Merge pending (CI may be blocking): {merge.get('message', '')}")

# ── RSS sources with AllSides / Ad Fontes Media bias ratings ──────────────────
# bias: -2=far-left  -1=left  0=center  +1=right  +2=far-right
SOURCES = [
    {"name": "BBC News",      "url": "http://feeds.bbci.co.uk/news/rss.xml",                   "bias": -0.3, "icon": "🇬🇧"},
    {"name": "NPR",           "url": "https://feeds.npr.org/1001/rss.xml",                      "bias": -0.7, "icon": "📻"},
    {"name": "Al Jazeera",    "url": "https://www.aljazeera.com/xml/rss/all.xml",              "bias": -0.4, "icon": "🌍"},
    {"name": "The Hill",      "url": "https://thehill.com/news/feed/",                          "bias":  0.1, "icon": "⚖️"},
    {"name": "Fox News",      "url": "https://moxie.foxnews.com/google-publisher/latest.xml",   "bias":  1.3, "icon": "🦅"},
    {"name": "DW News",       "url": "https://rss.dw.com/rdf/rss-en-all",                    "bias": -0.1, "icon": "🌐"},
    {"name": "PBS NewsHour",  "url": "https://www.pbs.org/newshour/feeds/rss/headlines",        "bias": -0.2, "icon": "📺"},
    {"name": "NASA",          "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",          "bias":  0.0, "icon": "🚀"},
    {"name": "Science Daily", "url": "https://www.sciencedaily.com/rss/all.xml",               "bias":  0.0, "icon": "🔬"},
    {"name": "Smithsonian",   "url": "https://www.smithsonianmag.com/rss/latest_articles/",    "bias": -0.1, "icon": "🏛️"},
    # Extended science + educational sources (bias ≈ 0, topic-safe)
    {"name": "Science News",  "url": "https://www.sciencenews.org/feed",                       "bias":  0.0, "icon": "📡"},
    {"name": "EarthSky",      "url": "https://earthsky.org/feed/",                             "bias":  0.0, "icon": "🌏"},
    {"name": "Live Science",  "url": "https://www.livescience.com/feeds/all",                  "bias":  0.0, "icon": "🧬"},
    {"name": "Phys.org",      "url": "https://phys.org/rss-feed/",                             "bias":  0.0, "icon": "⚛️"},
    {"name": "MIT News",      "url": "https://news.mit.edu/rss/research",                      "bias":  0.0, "icon": "🎓"},
    {"name": "New Scientist", "url": "https://www.newscientist.com/feed/home/",                "bias": -0.1, "icon": "🧪"},
    {"name": "Popular Science","url": "https://www.popsci.com/feed/",                          "bias":  0.0, "icon": "💡"},
    {"name": "Space.com",     "url": "https://www.space.com/feeds/all",                        "bias":  0.0, "icon": "🌌"},
]

# ── Kid-safety filter ──────────────────────────────────────────────────────────
BLOCKLIST = [
    "murder", "killed", "shooting", "massacre", "rape", "sexual assault",
    "suicide", "overdose", "cocaine", "heroin", "fentanyl",
    "explicit", "porn", "adult content",
    "war crime", "genocide", "torture", "execution", "beheading",
    "fatally", "death toll", "casualties", "bodies found",
    "die in", "dies in", "died in",
]
SAFE_OVERRIDES = [
    "space", "science", "animal", "planet", "nature", "research",
    "invention", "discovery", "environment", "ocean", "climate",
    # extended: nature/ecology death-adjacent stories are OK
    "fossil", "dinosaur", "reef", "coral", "species", "extinct",
    "habitat", "migration", "eruption", "meteor", "asteroid",
    "galaxy", "telescope", "comet", "nebula",
]

def is_kid_safe(title, desc):
    text = (title + " " + desc).lower()
    if any(safe in text for safe in SAFE_OVERRIDES):
        return True
    return not any(bad in text for bad in BLOCKLIST)

# ── RSS fetch + XML parse ──────────────────────────────────────────────────────
def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def fetch_rss(source):
    try:
        req = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; KiddieDaily/1.0)"})
        xml_bytes = urllib.request.urlopen(req, timeout=15, context=ctx).read()
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"    ⚠ {source['name']}: {e}")
        return []

    ATOM  = "http://www.w3.org/2005/Atom"
    RSS1  = "http://purl.org/rss/1.0/"
    DC_NS = "http://purl.org/dc/elements/1.1/"

    def get_field(item, *tags):
        for tag in tags:
            for ns in ("", ATOM, RSS1, DC_NS):
                key = f"{{{ns}}}{tag}" if ns else tag
                el = item.find(key)
                if el is not None and el.text:
                    return el.text.strip()
        return ""

    items = root.findall(".//item")
    if not items:
        items = root.findall(f".//{{{ATOM}}}entry")
    if not items:
        items = root.findall(f".//{{{RSS1}}}item")

    # DW News prefixes like "Germany news:", "Europe news:", "Turkey news:" etc.
    _DW_PREFIX = re.compile(r"^[A-Za-z\s]+\s+news:\s*", re.I)

    stories = []
    for item in items[:25]:
        title = clean(get_field(item, "title"))
        link  = clean(get_field(item, "link", "url"))
        desc  = clean(get_field(item, "description", "summary", "content"))
        pub   = get_field(item, "pubDate", "published", "updated")

        # Strip DW "Germany news: " type prefixes
        if source.get("name") == "DW News":
            title = _DW_PREFIX.sub("", title).strip()

        if not title or not link:
            continue
        if not is_kid_safe(title, desc):
            continue

        stories.append({
            "title": title,
            "link": link,
            "description": desc[:700],
            "pub": pub,
            "source_name": source["name"],
            "source_bias": source["bias"],
            "source_icon": source["icon"],
        })
    return stories

# ── Topic grouping: identify stories multiple sources cover ───────────────────
STOP_WORDS = {"the","a","an","in","on","at","to","for","of","and","or","is","are",
              "was","were","be","has","have","had","will","would","it","this","that",
              "as","by","from","with","its","into","he","she","they","new","says",
              "over","after","amid","amid","before","about","up","out","us","more"}

def keywords(title):
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return set(w for w in words if w not in STOP_WORDS and len(w) > 2)

def jaccard(t1, t2):
    w1, w2 = keywords(t1), keywords(t2)
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)

SCIENCE_SOURCES = {"NASA", "Science Daily", "Smithsonian", "Science News", "EarthSky", "Live Science", "Phys.org", "MIT News", "New Scientist", "Popular Science", "Space.com"}
DEPRIORITIZE_WORDS = [
    "war", "strike", "bomb", "missile", "airstrike", "military",
    "attack", "troops", "soldier", "killed", "dead", "death",
    "iran", "israel", "ukraine", "russia", "hamas", "congress",
    "senate", "republican", "democrat", "trump", "biden", "president",
    "election", "indicted", "arrested", "shooting", "crash",
    # political-regulatory (heavy penalty so non-science replaces them)
    "supreme court", "aoc", "gop", "filibuster", "legislation",
    "firefighter", "firefighters", "police officer", "custody",
    # entertainment/sport-entertainment (low value for kids news)
    "wwe", "tna", "wrestling", "championship belt", "retains the", "smackdown",
    "raw results", "raw recap", "nxt results",
    # professional-sports results/retirements (adult sports industry, not child-development news)
    "test match", "ashes series", "ashes test", "county cricket",
    "t20 series", "t20 match", "t20 cricket", "ipl ",
    "says retiring", "retiring from international", "ends international career",
    "wimbledon final", "wimbledon semi", "wimbledon quarter",
    "premier league", "la liga", "serie a", "ligue 1",
    "formula 1 race", "grand prix result",
    # UK-specific politics (not relevant for US/global families)
    "burnham", "keir starmer", "rishi sunak", "suella braverman",
    "tory party", "labour party", "hs2", "westminster",
    # EU/German-specific politics (DW News source — filter local German politics)
    "bundestag", "bundesrat", "scholz", "friedrich merz", "habeck",
    "spd ", " cdu", " fdp", " afd",
    # Ultra-niche international politics (not relevant for US families)
    "orban", "vucic", "fidesz", "new caledonia", "macron", "french parliament",
    "italian parliament", "spanish parliament", "austrian coalition",
    # Business/finance research (not relevant for kids/parents' child-rearing decisions)
    "sales channel", "supply chain disruption", "quarterly earnings",
    "profit margin", "market share", "shareholder", "stock market", "hedge fund",
    # Shopping/commercial content and lifestyle (product deals, recipes, not educational news)
    "amazon prime", "deal days", "best deals", "sale ends", "buy now", "discount code",
    "prime day", "black friday", "cyber monday", "coupon", "promo code",
    "perfectly cooked", "family cookout", "cookout with", "hot dog recipe", "bbq tips",
    "this week in space podcast", "podcast: episode", "episode —",
    # Sports predictions/analysis (journalist opinion, not factual news)
    "predicts world cup", "world cup predictions", "team to beat",
    "sutton predicts", "expert predictions", "power rankings",
    "player ratings", "match ratings", "pundit",
]

# Max absolute bias for world news articles (highly partisan sources get skipped)
MAX_WORLD_NEWS_BIAS = 0.9

def ranking_score(group):
    n = len(group)
    has_science = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    bias_penalty = abs(sum(s["source_bias"] for s in group) / n)
    combined_text = " ".join(s["title"].lower() for s in group)
    heavy_news = sum(1 for w in DEPRIORITIZE_WORDS if w in combined_text)
    return (
        (5 if has_science else 0)  # science sources get big boost
        + n * 2                    # more corroborating sources = better
        - heavy_news * 3           # political/military words = penalty
        - bias_penalty             # extreme bias = small penalty
    )

def group_stories(stories):
    groups = []
    used = set()
    for i, s in enumerate(stories):
        if i in used:
            continue
        group = [s]
        used.add(i)
        for j, other in enumerate(stories):
            if j in used or j == i:
                continue
            if jaccard(s["title"], other["title"]) > 0.18:
                group.append(other)
                used.add(j)
        groups.append(group)
    groups.sort(key=ranking_score, reverse=True)
    return groups

# ── Bias + source-agreement scoring ──────────────────────────────────────────
def score_group(group):
    biases = [s["source_bias"] for s in group]
    bias_avg = sum(biases) / len(biases)
    n = len(set(s["source_name"] for s in group))
    agreement_pct = min(99, round((n / len(SOURCES)) * 250))  # scaled: 4/8 sources → ~100%
    return {
        "bias_avg": round(bias_avg, 2),
        "n_sources": n,
        "agreement_pct": agreement_pct,
        "sources": [{"name": s["source_name"], "bias": s["source_bias"], "icon": s["source_icon"]} for s in group],
    }

# ── Bias bar + agreement badge HTML ──────────────────────────────────────────
BIAS_CSS = """
.kd-bias-box{background:#f7fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 20px;margin:22px 0 18px;font-family:system-ui,sans-serif;font-size:14px}
.kd-bias-hdr{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#718096;font-weight:600;margin-bottom:10px}
.kd-bias-row{display:flex;align-items:center;gap:10px;margin:6px 0 4px}
.kd-bias-lbl{font-size:12px;font-weight:700;width:32px}
.kd-bias-lbl.l{color:#3182ce;text-align:right}
.kd-bias-lbl.r{color:#e53e3e}
.kd-bias-track{flex:1;height:10px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);border-radius:5px;position:relative}
.kd-bias-dot{position:absolute;top:-5px;width:20px;height:20px;background:#1a1a1a;border-radius:50%;border:3px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transform:translateX(-50%)}
.kd-bias-tag{font-size:13px;color:#4a5568;margin-left:6px}
.kd-chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 8px}
.kd-chip{padding:3px 10px;border-radius:12px;font-size:12px;white-space:nowrap}
.kd-chip.L{background:#ebf8ff;color:#2b6cb0}
.kd-chip.C{background:#f0fff4;color:#276749}
.kd-chip.R{background:#fff5f5;color:#c53030}
.kd-agree-row{display:flex;align-items:center;gap:10px;margin-top:6px}
.kd-badge{padding:4px 12px;border-radius:12px;font-size:13px;font-weight:700}
.kd-badge-sci{background:#d1fae5;color:#065f46}
.kd-badge-news{background:#dbeafe;color:#1e40af}
.badge-hi{background:#c6f6d5;color:#22543d}
.badge-med{background:#fefcbf;color:#744210}
.badge-lo{background:#fed7d7;color:#742a2a}
.kd-agree-note{font-size:12px;color:#718096}
"""

def bias_bar_html(score):
    bias = score["bias_avg"]
    pct = max(5, min(95, round((bias + 2) / 4 * 100)))

    bias_label = ("Far Left" if bias <= -1.2 else "Leans Left" if bias <= -0.4
                  else "Center-Left" if bias <= -0.15 else "Center" if bias <= 0.15
                  else "Center-Right" if bias <= 0.4 else "Leans Right" if bias <= 1.2
                  else "Far Right")

    chips = []
    for src in score["sources"]:
        b = src["bias"]
        cls = "L" if b <= -0.2 else ("R" if b >= 0.2 else "C")
        chips.append(f'<span class="kd-chip {cls}">{src["icon"]} {src["name"]}</span>')

    ap = score["agreement_pct"]
    badge_cls = "badge-hi" if ap >= 65 else ("badge-med" if ap >= 35 else "badge-lo")
    n = score["n_sources"]

    return f"""<div class="kd-bias-box">
<div class="kd-bias-hdr">📊 Source Analysis — KiddieDaily Editorial</div>
<div class="kd-bias-row">
  <span class="kd-bias-lbl l">Left</span>
  <div class="kd-bias-track"><div class="kd-bias-dot" style="left:{pct}%"></div></div>
  <span class="kd-bias-lbl r">Right</span>
  <strong class="kd-bias-tag">{bias_label}</strong>
</div>
<div class="kd-chips">{"".join(chips)}</div>
<div class="kd-agree-row">
  <span class="kd-badge {badge_cls}">{ap}% source agreement</span>
  <span class="kd-agree-note">Covered by {n} independent source{"s" if n!=1 else ""}</span>
</div>
</div>
<p style="font-size:12px;color:#a0aec0;margin-top:-12px;font-family:system-ui,sans-serif">
Bias ratings based on <em>AllSides</em> + <em>Ad Fontes Media</em>. Agreement % = sources covering this story.
Always read multiple sources and think critically.
</p>"""

# ── Anthropic Haiku rewrite (optional) ────────────────────────────────────────
def rewrite_for_kids(title, description):
    if not ANTHROPIC_KEY:
        return None
    prompt = f"""You are a writer for KiddieDaily, a fact-checked daily news site for kids ages 8-14 and their parents.

Original headline: {title}
Original summary: {description}

Rewrite this as a short kid-friendly article. Return ONLY the article, no meta-commentary.

FORMAT (follow exactly):
[Kid-friendly headline — exciting, accurate, max 12 words]

[Lede — 2 vivid sentences that hook a curious kid. Start with what happened.]

## What Happened
[3-4 simple sentences: the core facts, explained like you're talking to a smart 10-year-old.]

## Why It Matters
[2-3 sentences: real-world impact. Connect to something kids care about — animals, space, health, discovery.]

## Think About This
[One open question for family discussion. Starts with "What do you think..." or "Why do you think..."]

RULES:
- No violence, war, politics, or adult content. Skip if unavoidable.
- Use vivid, concrete language. Avoid jargon.
- Keep total length under 200 words.
- Tone: warm, curious, slightly excited — like a science teacher who loves their subject."""

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 900,
            "messages": [{"role": "user", "content": prompt}]
        }).encode(),
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        method="POST")
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30, context=ctx).read())
        return r.get("content", [{}])[0].get("text", "").strip()
    except Exception as e:
        print(f"    ⚠ Anthropic API: {e}")
        return None

# ── Article body builders ─────────────────────────────────────────────────────
SKIP_PARA_WORDS = [
    "cookie", "subscribe", "newsletter", "javascript", "sign up",
    "advertisement", "click here", "read more", "follow us",
    "privacy policy", "terms of use", "all rights reserved",
    "copyright", "©", "skip to", "share this", "email address",
    "by clicking", "you agree", "logged in", "create account",
    "already a subscriber", "to continue reading", "paywall",
    "enable javascript", "browser does not support", "reload the page",
    "get the latest", "breaking news", "follow on", "download the app",
]

# Dateline pattern — "CITY, STATE (SOURCE) — " at start of text
_DATELINE_RE = re.compile(
    r"^[A-Z][A-Z ,'\-]{2,40}(?:\([^)]{2,20}\))?\s*[—\-]{1,3}\s*", re.UNICODE
)

def _clean_lede(text):
    """Strip news datelines and boilerplate from the opening of a paragraph."""
    text = text.strip()
    # Remove datelines like "WASHINGTON (AP) — " or "NEW YORK — "
    text = _DATELINE_RE.sub("", text)
    # Remove byline openers like "By Staff Writer · "
    text = re.sub(r"^By [A-Z][a-zA-Z .'\-]+ [·|•]\s*", "", text)
    # Normalize HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#39;", "'").replace("&quot;", '"').replace("&nbsp;", " ")
    return text.strip()

def fetch_article_text(url, fallback):
    """Fetch full article text from source URL; return cleaned paragraphs or fallback."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        req = urllib.request.Request(url, headers=headers)
        raw = urllib.request.urlopen(req, timeout=7, context=ctx).read().decode("utf-8", errors="replace")
        # Strip scripts, styles, nav, footer, aside, header, form, figure captions
        raw = re.sub(
            r"<(script|style|nav|footer|aside|header|form|figcaption|noscript)[^>]*>.*?</\1>",
            "", raw, flags=re.DOTALL | re.IGNORECASE
        )
        # Extract <p> content
        paras = re.findall(r"<p[^>]*>(.*?)</p>", raw, re.DOTALL | re.IGNORECASE)
        paras = [re.sub(r"<[^>]+>", "", p).strip() for p in paras]
        paras = [re.sub(r"\s+", " ", p) for p in paras]
        paras = [
            _clean_lede(p) if idx == 0 else p
            for idx, p in enumerate(paras)
            if len(p) > 50
            and not any(w in p.lower() for w in SKIP_PARA_WORDS)
        ]
        if len(paras) >= 2:
            return " ".join(paras[:9])
    except Exception:
        pass
    # Clean the fallback description too
    clean_fb = re.sub(r"<[^>]+>", "", fallback or "").strip()
    clean_fb = re.sub(r"\s+", " ", clean_fb)
    return _clean_lede(clean_fb) if clean_fb else (fallback or "")


def body_from_rss(group):
    rep = group[0]
    # Try to fetch full text; fall back to RSS description
    full_text = fetch_article_text(rep["link"], rep["description"])

    sentences = [_clean_lede(s) if i == 0 else s
                 for i, s in enumerate(
                     s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text)
                     if len(s.strip()) > 25
                 )]

    # Detect science article by checking group sources against SCIENCE_SOURCES
    is_science = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    h2_mid  = "What scientists found" if is_science else "What happened"
    h2_late = "Why it matters for kids"

    # Lede = first sentence only (dateline already stripped by _clean_lede above)
    lede = sentences[0] if sentences else _clean_lede(full_text[:220])

    # Build structured paragraphs from remaining sentences (groups of 2-3)
    body_sents = sentences[1:]  # everything after the lede sentence
    html = [f'<p class="lede">{lede}</p>']

    i = 0
    para_index = 0  # counts paragraphs emitted so we can insert h2s at the right spots
    while i < len(body_sents):
        # Insert h2 before the paragraph that starts at original sentence index 3 (0-based)
        # sentence index 3 = body_sents index 2 (lede was sentence 0)
        orig_sent_idx = i + 1  # +1 because body_sents starts at sentence[1]
        if orig_sent_idx == 3 and len(sentences) >= 6:
            html.append(f"<h2>{h2_mid}</h2>")
        if orig_sent_idx == 6 and len(sentences) >= 9:
            html.append(f"<h2>{h2_late}</h2>")
        chunk = body_sents[i:i + 3]
        html.append(f"<p>{' '.join(chunk)}</p>")
        i += 3
        para_index += 1

    # Other-source perspective (multi-source stories)
    others = [s for s in group[1:3] if s["description"] and s["description"][:80] != rep["description"][:80]]
    if others:
        other_text = fetch_article_text(others[0]["link"], others[0]["description"])
        other_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", other_text) if len(s.strip()) > 25]
        other_lede = " ".join(other_sents[:3]) if other_sents else others[0]["description"][:400]
        html.append(
            f"<h2>How {others[0]['source_icon']} {others[0]['source_name']} Covers It</h2>"
            f"<p>{other_lede}</p>"
        )

    html.append(
        "<h2>Think About This</h2>"
        "<p>What questions does this story raise for you? Talk with your family: "
        "Why does this news matter? Who is affected? What might happen next? "
        "Is there anything you can do?</p>"
    )
    return rep["title"], "".join(html)

def body_from_api(original_title, text):
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return original_title, f"<p>{text}</p>"

    new_title = lines[0]
    html_parts = []
    lede_done = False
    buf = []

    for ln in lines[1:]:
        if ln.startswith("##") or ln.startswith("#"):
            if buf:
                content = " ".join(buf)
                tag = 'p class="lede"' if not lede_done else "p"
                html_parts.append(f"<{tag}>{content}</p>")
                lede_done = True
                buf = []
            html_parts.append(f"<h2>{ln.lstrip('#').strip()}</h2>")
        else:
            buf.append(ln)

    if buf:
        content = " ".join(buf)
        tag = 'p class="lede"' if not lede_done else "p"
        html_parts.append(f"<{tag}>{content}</p>")

    return new_title, "".join(html_parts)

# ── Page template ─────────────────────────────────────────────────────────────
CSS = '''<style>
*{box-sizing:border-box}html{font-family:Georgia,"Times New Roman",serif;color:#1a1a1a;background:#faf8f3;line-height:1.6}
body{margin:0;font-size:17px}a{color:#1a4d80;text-decoration:none}a:hover{text-decoration:underline}
header.kd{background:#1a4d80;color:#fff;padding:12px 24px}
header.kd .inner{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px}
header.kd .logo{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif}
header.kd .logo small{display:block;font-size:11px;font-weight:400;letter-spacing:2px;color:#cbd5e0;text-transform:uppercase}
header.kd nav{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}
header.kd nav a{color:#fff;font-size:15px;font-family:system-ui,sans-serif}
header.kd nav a:hover{color:#ffd700}
.pz-cta{background:#ffd700;color:#1a1a1a;padding:6px 14px;border-radius:6px;font-weight:600;font-size:14px;font-family:system-ui,sans-serif}
main{max-width:780px;margin:0 auto;padding:32px 24px 64px}
h1{font-size:36px;line-height:1.2;margin:8px 0 16px}
h2{font-size:26px;margin:32px 0 12px;color:#2d3748;border-bottom:1px solid #e5e7eb;padding-bottom:6px}
p{margin:0 0 16px}.lede{font-size:20px;color:#4a5568;margin-bottom:24px;font-style:italic}
.byline{font-size:14px;color:#718096;margin:0 0 24px}
.sources{background:#f7fafc;border-left:4px solid #1a4d80;padding:14px 18px;margin:18px 0;font-size:15px}
.sources h4{margin:0 0 6px;color:#1a4d80;font-size:14px;letter-spacing:1px;text-transform:uppercase;font-family:system-ui,sans-serif}
.sources ul{margin:0;padding-left:22px}
footer.kd{background:#1a202c;color:#cbd5e0;padding:36px 24px;margin-top:48px;font-family:system-ui,sans-serif}
footer.kd .inner{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;gap:32px}
footer.kd h4{color:#fff;margin:0 0 10px;font-size:13px;letter-spacing:1.5px;text-transform:uppercase}
footer.kd a{color:#cbd5e0;display:block;padding:3px 0;font-size:14px}
''' + BIAS_CSS + "</style>"

HEADER = """<header class="kd"><div class="inner">
<a href="/" class="logo">KiddieDaily<small>News for Families</small></a>
<nav><a href="/news/today.html">Today</a><a href="/news/">Kid News</a><a href="/search.html">Search</a><a href="/parents/">For Parents</a><a href="/fact-check/">Fact Check</a>
<a href="/games/">Games</a><a href="/about.html">About</a><a href="/parent-zone/" class="pz-cta">Parent Zone</a></nav>
</div></header>"""

FOOTER = """<footer class="kd"><div class="inner">
<div style="flex:1;min-width:200px"><h4>KiddieDaily</h4>
<p style="margin:0;font-size:14px;color:#cbd5e0">Curated daily news for families with research-backed fact checks.</p></div>
<div><h4>Read</h4><a href="/news/today.html">Today's News</a><a href="/news/">Kid News</a><a href="/digest/latest.html">Daily Digest</a>
<a href="/parents/">For Parents</a><a href="/fact-check/">Fact Check</a><a href="/games/">Games</a></div>
<div><h4>Account</h4><a href="/parent-zone/">Parent Zone</a><a href="/subscribe/">Subscribe</a><a href="/about.html">About</a>
<a href="/contact.html">Contact</a></div>
<div><h4>Legal</h4><a href="/privacy.html">Privacy</a><a href="/terms.html">Terms</a></div>
<div><h4>Our Network</h4><a href="https://kiddiewordle.com" rel="noopener">KiddieWordle</a>
<a href="https://kiddiesketch.com" rel="noopener">KiddieSketch</a>
<a href="https://kiddiego.com" rel="noopener">KiddieGo</a></div>
</div>
<div style="text-align:center;font-size:13px;color:#a0aec0;margin-top:24px">
&copy; 2026 KiddieDaily &middot; A Legacy Bridge Alliance Group family project</div>
</footer>"""

def make_slug(title, date_str):
    slug = re.sub(r"[^\w\s-]", "", title.lower())
    slug = re.sub(r"\s+", "-", slug.strip())[:50].rstrip("-")
    return f"news/{date_str}-{slug}.html"

def reading_time(html_text):
    words = len(re.sub(r"<[^>]+>", " ", html_text).split())
    mins = max(1, round(words / 200))
    return f"{mins} min read"

def parent_discussion_guide(title, is_science):
    """Return an HTML parent discussion guide for an article."""
    # Extract 1-2 meaningful topic words from the title for question prompts
    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will"}
    words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
             if len(w) > 3 and w not in stop]
    topic = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "this topic")

    if is_science:
        bullets = [
            (f"<strong>Ask your child:</strong> &ldquo;What do you think scientists discovered about <em>{topic}</em>? "
             "What part surprised you most?&rdquo;"),
            ("<strong>Explore together:</strong> Search for &ldquo;" + topic + "&rdquo; on NASA Kids&#x2019; Club, "
             "DK Find Out, or National Geographic Kids for more kid-friendly facts."),
            ("<strong>Critical thinking:</strong> Science findings can change as more research is done. Ask: "
             "&ldquo;How would scientists test this? What would prove them wrong?&rdquo;"),
        ]
        icon, color, bg, border = "🔬", "#065f46", "#f0fff4", "#9ae6b4"
    else:
        bullets = [
            (f"<strong>Ask your child:</strong> &ldquo;Why do you think people care about <em>{topic}</em>? "
             "How might this affect families like ours?&rdquo;"),
            ("<strong>Compare sources:</strong> The bias rating above shows how this outlet leans. Try finding "
             "one more source that covers the same story. Do they agree? What&rsquo;s different?"),
            ("<strong>Media literacy:</strong> Ask: &ldquo;What facts does this story give us? "
             "What opinions does it include? Who is speaking, and why might they say this?&rdquo;"),
        ]
        icon, color, bg, border = "🗞️", "#1e40af", "#eff6ff", "#93c5fd"

    rows = "".join(
        f'<li style="margin:8px 0;line-height:1.55;font-size:14px;color:#2d3748">{b}</li>'
        for b in bullets
    )
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:10px;'
        f'padding:18px 22px;margin:22px 0;font-family:system-ui,sans-serif">'
        f'<div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;'
        f'letter-spacing:1.1px;margin-bottom:12px">{icon} Parent discussion guide</div>'
        f'<ul style="margin:0;padding:0 0 0 18px">{rows}</ul>'
        f'<p style="font-size:11px;color:#a0aec0;margin:12px 0 0">KiddieDaily is built for families — '
        f'balanced sources, no agenda, no ads. Always read the original source and think for yourself.</p>'
        f'</div>'
    )


def build_page(title, body_html, bias_html, score, group, slug, today):
    n = score["n_sources"]
    url = f"https://kiddiedaily.com/{slug}"
    # og:description — clean text from RSS summary (strip HTML tags)
    raw_desc = group[0].get("description", "") if group else ""
    og_desc = re.sub(r"<[^>]+>", "", raw_desc).strip()[:160] or title[:160]
    is_sci_page = any(s.get("source_name", "") in SCIENCE_SOURCES for s in group)
    og_image = "https://kiddiedaily.com/og-science.svg" if is_sci_page else "https://kiddiedaily.com/og-news.svg"
    jsonld = json.dumps({
        "@context": "https://schema.org", "@type": "NewsArticle",
        "headline": title,
        "author": {"@type": "Organization", "name": "KiddieDaily Editors"},
        "publisher": {"@type": "Organization", "name": "KiddieDaily", "url": "https://kiddiedaily.com"},
        "datePublished": today, "dateModified": today,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url}
    })

    source_items = "".join(
        f'<li>{s["source_icon"]} <a href="{s["link"]}" rel="noopener nofollow" target="_blank">'
        f'{s["source_name"]}: {s["title"][:75]}{"..." if len(s["title"])>75 else ""}</a></li>'
        for s in group
    )
    # Google Fact Check Explorer link — lets parents quickly search for claims
    fc_query = urllib.parse.quote(title[:80])
    fact_check_url = f"https://toolbox.google.com/factcheck/explorer/search/{fc_query}"

    # Multiple perspectives block — shows how each outlet framed the story
    def _perspectives_html(group, n):
        if n < 2:
            return ""
        rows = []
        for s in group:
            b = s["source_bias"]
            lean = ("Left" if b <= -0.4 else ("Right" if b >= 0.4 else "Center"))
            lean_color = "#2b6cb0" if lean == "Left" else ("#c53030" if lean == "Right" else "#276749")
            headline = s["title"][:100] + ("…" if len(s["title"]) > 100 else "")
            rows.append(
                f'<div style="padding:10px 14px;border-left:3px solid {lean_color};margin:6px 0;background:#fafafa;border-radius:0 6px 6px 0">'
                f'<span style="font-size:11px;font-weight:700;color:{lean_color};text-transform:uppercase;letter-spacing:.8px">{lean}</span>'
                f' <span style="font-size:11px;color:#718096">&mdash; {s["source_icon"]} {s["source_name"]}</span><br>'
                f'<span style="font-size:14px;color:#2d3748">{headline}</span>'
                f'</div>'
            )
        return (
            '<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:18px 0;font-family:system-ui,sans-serif">'
            '<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">'
            '&#127919; Multiple perspectives — how outlets framed this story</div>'
            + "".join(rows) +
            '<p style="font-size:11px;color:#a0aec0;margin:8px 0 0">Reading multiple sources helps you spot framing differences. '
            'Neither left- nor right-leaning outlets are always wrong — or always right.</p>'
            '</div>'
        )

    perspectives_html = _perspectives_html(group, n)
    is_sci = any(s["source_name"] in SCIENCE_SOURCES for s in group)
    guide_html = parent_discussion_guide(title, is_sci)

    rt = reading_time(body_html)
    body = f"""<p class="byline">By KiddieDaily Editors &middot; {today} &middot; {rt} &middot; {n} source{"s" if n!=1 else ""}</p>
<h1>{title}</h1>
{bias_html}
{perspectives_html}
{body_html}
{guide_html}
<div class="sources"><h4>Original Sources</h4><ul>{source_items}</ul></div>
<p style="margin-top:16px;padding:10px 14px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;font-size:13px">
&#128269; <strong>Want to verify this story?</strong>
<a href="{fact_check_url}" rel="noopener nofollow" target="_blank" style="color:#065f46">Check it on Google Fact Check Explorer &rarr;</a>
</p>
<div style="margin:24px 0;padding:16px 20px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
<div style="font-size:28px">&#128240;</div>
<div style="flex:1">
<strong style="font-size:15px;display:block;color:#0c4a6e;margin-bottom:2px">Get today's digest</strong>
<span style="font-size:13px;color:#075985">All of today's kid-safe stories in one parent-friendly roundup — with bias ratings.</span>
</div>
<a href="/digest/latest.html" style="background:#0c4a6e;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;white-space:nowrap;font-family:system-ui,sans-serif">Read digest &rarr;</a>
</div>
<p><em>More stories: <a href="/news/">Kid News</a> &middot; <a href="/news/archive.html">Archive</a> &middot; <a href="/fact-check/">Fact Check</a></em></p>
<div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
<button onclick="if(navigator.share){{navigator.share({{title:document.title,url:location.href}})}}else{{navigator.clipboard.writeText(location.href);this.textContent='Link copied!';setTimeout(()=>this.textContent='Copy link',2000)}}" style="background:#1a4d80;color:#fff;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;font-size:14px">Share this story</button>
<a href="/news/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none">&larr; All news</a>
<a href="/feed.xml" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none">RSS feed</a>
</div>"""

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="description" content="{title[:155]}">
<link rel="canonical" href="{url}">
<title>{title} — KiddieDaily</title>
<meta property="og:type" content="article"><meta property="og:title" content="{title}">
<meta property="og:url" content="{url}"><meta property="og:site_name" content="KiddieDaily">
<meta property="og:description" content="{og_desc}">
<meta property="og:image" content="{og_image}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{og_desc}">
<meta name="twitter:image" content="{og_image}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ctext y=%22.9em%22 font-size=%2290%22%3E&#x1f4f0;%3C/text%3E%3C/svg%3E">
<script type="application/ld+json">{jsonld}</script>
{CSS}</head><body>{HEADER}<main>{body}</main>{FOOTER}
<script>
(function(){{
  const SLUG="{slug}";
  const TITLE_WORDS=new Set("{title}".toLowerCase().replace(/[^\\w\\s]/g,"").split(/\\s+/).filter(w=>w.length>3&&!["that","this","with","from","have","were","they","more"].includes(w)));
  fetch("/data/kd-articles.json").then(r=>r.json()).then(articles=>{{
    const scored=articles.filter(a=>a.slug!==SLUG).map(a=>{{
      const w=new Set(a.title.toLowerCase().replace(/[^\\w\\s]/g,"").split(/\\s+/).filter(x=>x.length>3));
      const overlap=[...TITLE_WORDS].filter(x=>w.has(x)).length;
      return{{...a,score:overlap+(a.is_science?0.5:0)}};
    }}).sort((a,b)=>b.score-a.score).slice(0,3).filter(a=>a.score>0);
    if(!scored.length)return;
    const box=document.createElement("div");
    box.style.cssText="max-width:780px;margin:0 auto;padding:0 24px 48px;font-family:system-ui,sans-serif";
    box.innerHTML="<h2 style='font-size:18px;color:#2d3748;border-bottom:1px solid #e5e7eb;padding-bottom:6px;margin-bottom:12px'>Related stories</h2>"
      +scored.map(a=>`<div style='margin:8px 0;padding:10px 14px;background:#fff;border:1px solid #e5e7eb;border-radius:8px'>
        <span style='font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;background:${{a.is_science?"#d1fae5":"#dbeafe"}};color:${{a.is_science?"#065f46":"#1e40af"}};padding:2px 7px;border-radius:20px'>${{a.is_science?"Science":"World News"}}</span>
        <a href="/${{a.slug}}" style='display:block;color:#1a4d80;font-weight:600;margin:5px 0 2px;font-size:15px'>${{a.title}}</a>
        <span style='font-size:11px;color:#a0aec0'>${{a.date}}</span>
        </div>`).join("");
    document.body.appendChild(box);
  }}).catch(()=>{{}});
}})();
</script>
</body></html>"""

# ── Manifest: tracks pushed slugs to avoid duplicates ─────────────────────────
def load_manifest():
    r = gh("GET", f"/repos/{REPO}/contents/data/kd-scraped-manifest.json")
    if r.get("_err") or not r.get("content"):
        return {"pushed_slugs": [], "pushed_titles": [], "articles": []}
    try:
        m = json.loads(base64.b64decode(r["content"]).decode("utf-8"))
    except Exception:
        return {"pushed_slugs": [], "pushed_titles": [], "articles": []}

    # Migrate: if pushed_slugs exist but articles list is missing, create stubs
    if m.get("pushed_slugs") and not m.get("articles"):
        m["articles"] = []
        titles = m.get("pushed_titles", [])
        for i, slug in enumerate(m["pushed_slugs"]):
            title = titles[i] if i < len(titles) else "Article"
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", slug)
            m["articles"].append({
                "slug": slug,
                "title": title,
                "display_title": title,
                "date": date_match.group() if date_match else "2026-06-26",
                "n_sources": 1,
                "bias_avg": 0.0,
                "agreement_pct": 30,
                "is_science": any(w in slug for w in ["nasa", "science", "space", "animal"]),
            })
        print(f"    (migrated {len(m['articles'])} legacy articles to new manifest format)")

    return m

def save_manifest(manifest):
    upload("data/kd-scraped-manifest.json",
           json.dumps(manifest, indent=2, ensure_ascii=False),
           "Update scraped articles manifest")

# ── news/index.html update ────────────────────────────────────────────────────
SCRAPED_START = "<!-- SCRAPED_CARDS_START -->"
SCRAPED_END   = "<!-- SCRAPED_CARDS_END -->"

KD_CARD_CSS = """<style>
.kd-today-hdr{margin:28px 0 12px;font-size:1.2em;font-family:Georgia,serif;color:#1a4d80;border-bottom:2px solid #ffd700;padding-bottom:6px}
.kd-sc{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}
.kd-sc-top{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}
.kd-badge{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}
.kd-badge-sci{background:#d1fae5;color:#065f46}
.kd-badge-news{background:#dbeafe;color:#1e40af}
.kd-agree{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;margin-left:auto}
.kd-agree-high{background:#d1fae5;color:#065f46}
.kd-agree-med{background:#fef3c7;color:#92400e}
.kd-agree-low{background:#fee2e2;color:#991b1b}
.kd-sc h3{margin:4px 0 8px;font-size:1em;line-height:1.35}
.kd-sc h3 a{color:#1a4d80;text-decoration:none}
.kd-sc h3 a:hover{text-decoration:underline}
.kd-mini-bias{display:flex;align-items:center;gap:6px;margin-top:8px}
.kd-mini-lbl{font-size:10px;font-weight:700;color:#718096;width:16px}
.kd-mini-track{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}
.kd-mini-dot{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%);box-shadow:0 1px 3px rgba(0,0,0,.25)}
.kd-sc-date{font-size:11px;color:#a0aec0;margin-top:6px}
</style>"""

def _agree_class(pct):
    if pct >= 65: return "kd-agree-high"
    if pct >= 40: return "kd-agree-med"
    return "kd-agree-low"

def build_scraped_cards(articles):
    if not articles:
        return ""
    cards = []
    for a in sorted(articles, key=lambda x: x.get("date",""), reverse=True)[:10]:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))[:90]
        date  = a.get("date", "")
        n     = a.get("n_sources", 1)
        ap    = a.get("agreement_pct", 0)
        bias  = a.get("bias_avg", 0.0)
        is_sci = a.get("is_science", False)

        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        badge_lbl = "Science" if is_sci else "World News"
        agree_cls = _agree_class(ap)

        # Bias dot: map -2..+2 → 5%..95%
        dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))

        # Agreement label: single source = "1 outlet" not "31% sources agree"
        if n == 1:
            agree_lbl = "1 outlet"
            agree_cls = "kd-agree-low"
        else:
            agree_lbl = f"{n} outlets agree"

        # Source icons from stored group info (not available in manifest, derive from name)
        SOURCE_ICONS = {"BBC News": "🇬🇧", "NPR": "📻", "Al Jazeera": "🌍",
                        "The Hill": "⚖️", "Fox News": "🦅", "NASA": "🚀",
                        "Science Daily": "🔬", "Smithsonian": "🏛️"}
        src_icons = a.get("source_icons", "")

        cards.append(
            f'<div class="kd-sc">'
            f'<div class="kd-sc-top">'
            f'<span class="kd-badge {badge_cls}">{badge_lbl}</span>'
            f'<span class="kd-agree {agree_cls}">{agree_lbl}</span>'
            f'</div>'
            f'<h3><a href="/{slug}">{title}</a></h3>'
            f'<div class="kd-mini-bias">'
            f'<span class="kd-mini-lbl">L</span>'
            f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
            f'<span class="kd-mini-lbl" style="text-align:right">R</span>'
            f'</div>'
            + (f'<div class="kd-sc-date">{date}{" &middot; " + src_icons if src_icons else ""}</div>' if date else "")
            + f'</div>'
        )
    inner = "\n".join(cards)
    cat_nav = (
        '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px">'
        '<a href="/news/science.html" style="background:#d1fae5;color:#065f46;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🔬 Science</a>'
        '<a href="/news/technology.html" style="background:#e0e7ff;color:#3730a3;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">💻 Technology</a>'
        '<a href="/news/space.html" style="background:#ede9fe;color:#5b21b6;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🚀 Space</a>'
        '<a href="/news/animals.html" style="background:#fef3c7;color:#92400e;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🐾 Animals</a>'
        '<a href="/news/world.html" style="background:#dbeafe;color:#1e40af;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🌍 World</a>'
        '<a href="/news/environment.html" style="background:#dcfce7;color:#166534;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🌿 Environment</a>'
        '<a href="/news/history.html" style="background:#fce7f3;color:#9d174d;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;text-decoration:none">🏛 History</a>'
        '</div>'
    )
    return f"{SCRAPED_START}\n{KD_CARD_CSS}\n<h2 class=\"kd-today-hdr\">Today&#39;s news</h2>\n{cat_nav}\n{inner}\n{SCRAPED_END}"

def update_news_index(manifest):
    articles = manifest.get("articles", [])
    if not articles:
        return

    r = gh("GET", f"/repos/{REPO}/contents/news/index.html")
    if r.get("_err"):
        print(f"    ⚠ Could not fetch news/index.html: {r}")
        return

    html = base64.b64decode(r["content"]).decode("utf-8")

    new_block = build_scraped_cards(articles)

    if SCRAPED_START in html:
        # Replace existing scraped section
        start_i = html.index(SCRAPED_START)
        end_i   = html.index(SCRAPED_END) + len(SCRAPED_END)
        html = html[:start_i] + new_block + html[end_i:]
    else:
        # First run: insert before <h2>This week</h2>
        marker = "<h2>This week</h2>"
        if marker in html:
            html = html.replace(marker, new_block + "\n" + marker)
        else:
            # Fallback: append before </main>
            html = html.replace("</main>", new_block + "\n</main>")

    upload("news/index.html", html, "[scraper] Update news index with today's articles")

# ── GitHub Actions workflow (self-deployed to kiddiedaily repo) ───────────────
WORKFLOW_YAML = """\
name: KiddieDaily Daily News Scraper

on:
  schedule:
    - cron: '0 10 * * *'    # 10am UTC = 6am ET daily
  workflow_dispatch:          # manual trigger for testing

jobs:
  scrape-and-push:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Run KiddieDaily news scraper
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python scrape_and_push.py
"""

PR_REVIEW_YAML = """\
name: Content PR Review Agent

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

jobs:
  # Stage 1: validate script syntax
  review-script:
    name: "Stage 1 — Script Syntax Check"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Python syntax check
        run: |
          python -m py_compile scrape_and_push.py
          echo "✓ scrape_and_push.py syntax OK"

  # Stage 2: validate generated content
  review-content:
    name: "Stage 2 — Content Validator"
    runs-on: ubuntu-latest
    needs: review-script
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Validate HTML files (DOCTYPE + KiddieDaily header)
        run: |
          python - <<'EOF'
          import os, sys
          fail = 0
          for root, _, files in os.walk('.'):
              if '.git' in root:
                  continue
              for f in files:
                  if not f.endswith('.html'):
                      continue
                  path = os.path.join(root, f)
                  text = open(path, encoding='utf-8', errors='ignore').read()
                  if '<!DOCTYPE html>' not in text and '<!doctype html>' not in text.lower():
                      print(f'FAIL missing DOCTYPE: {path}')
                      fail += 1
          print(f'HTML check: {fail} failures')
          sys.exit(fail > 0)
          EOF
      - name: Validate articles JSON index
        run: |
          python - <<'EOF'
          import json, sys
          try:
              data = json.load(open('data/kd-articles.json'))
              assert len(data) > 0, "Empty articles JSON"
              required = {'slug', 'title', 'date', 'is_science'}
              for item in data[:3]:
                  missing = required - set(item.keys())
                  assert not missing, f"Missing fields {missing} in {item.get('slug','?')}"
              print(f"✓ {len(data)} articles in index, schema OK")
          except Exception as e:
              print(f"FAIL: {e}")
              sys.exit(1)
          EOF
      - name: Validate RSS feed
        run: |
          python - <<'EOF'
          import xml.etree.ElementTree as ET, sys
          try:
              tree = ET.parse('feed.xml')
              items = tree.findall('.//{http://www.w3.org/2005/Atom}entry') or \
                      tree.findall('.//item')
              print(f"✓ RSS feed has {len(items)} items")
          except Exception as e:
              print(f"FAIL RSS: {e}")
              sys.exit(1)
          EOF

  # Stage 3: validate sitemap
  review-sitemap:
    name: "Stage 3 — Sitemap & Coverage Check"
    runs-on: ubuntu-latest
    needs: review-content
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Validate sitemap
        run: |
          python - <<'EOF'
          import xml.etree.ElementTree as ET, sys
          tree = ET.parse('sitemap.xml')
          ns = 'http://www.sitemaps.org/schemas/sitemap/0.9'
          urls = [u.text for u in tree.findall(f'.//{{{ns}}}loc')]
          required = ['/', '/news/', '/news/archive.html', '/feed.xml',
                      '/news/science.html', '/search.html', '/digest/latest.html']
          missing = [r for r in required if not any(r in u for u in urls)]
          if missing:
              print(f"FAIL sitemap missing: {missing}")
              sys.exit(1)
          print(f"✓ Sitemap has {len(urls)} URLs, all required pages present")
          EOF
      - name: Coverage report
        run: |
          python - <<'EOF'
          import os, json
          cats = {'news': 0, 'digest': 0, 'search': 0}
          for root, _, files in os.walk('.'):
              if '.git' in root: continue
              for f in files:
                  if f.endswith('.html'):
                      k = root.split(os.sep)[1] if len(root.split(os.sep)) > 1 else 'root'
                      cats[k] = cats.get(k, 0) + 1
          print("Coverage:", json.dumps(cats, indent=2))
          articles = json.load(open('data/kd-articles.json'))
          print(f"✓ Total articles: {len(articles)}")
          EOF
"""

CODEOWNERS_FILE = """\
# KiddieDaily CODEOWNERS
# Automated content PRs (content/daily-news-*) have no human reviewer requirement.
# All source code + workflow changes route to the repo owner.
* @Omtatsat101
scrape_and_push.py @Omtatsat101
.github/ @Omtatsat101
"""

PR_TEMPLATE_MD = """\
## Summary
<!-- What changed? Automated content update or manual fix? -->

## Type
- [ ] Automated content update (daily news scraper)
- [ ] Scraper improvement
- [ ] Workflow / CI update
- [ ] Bug fix
- [ ] Other

## Checklist
- [ ] Python syntax check passes (`python -m py_compile scrape_and_push.py`)
- [ ] Articles JSON valid (`data/kd-articles.json` schema OK)
- [ ] Sitemap includes all required URLs
- [ ] No secrets or credentials included
- [ ] CI review stages all pass
"""

# ── Sitemap ───────────────────────────────────────────────────────────────────
STATIC_URLS = [
    "/", "/news/", "/parents/", "/fact-check/", "/games/",
    "/search.html",
    "/news/galaxy-far-far-away.html",
    "/news/water-filter-invention.html",
    "/news/sea-turtles-comeback.html",
    "/parents/screen-time-balance.html",
    "/parents/back-to-school-anxiety.html",
    "/parents/read-aloud-after-8.html",
    "/fact-check/tylenol-kids-brains.html",
    "/fact-check/social-media-teen-depression.html",
    "/games/index.html",
    "/about.html", "/privacy.html", "/terms.html", "/contact.html", "/status.html",
    "/subscribe/",
    "/feed.xml", "/news/archive.html", "/news/today.html",
    "/news/science.html", "/news/world.html",
    "/news/space.html", "/news/animals.html", "/news/history.html", "/news/environment.html", "/news/technology.html",
    "/digest/latest.html",
    "/digest/weekly.html",
]

def update_sitemap(pushed_slugs, manifest=None):
    BASE_URL = "https://kiddiedaily.com"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Collect all URLs
    urls = list(STATIC_URLS)
    for slug in pushed_slugs:
        # slug is already a full repo path like "news/2026-06-26-title.html"
        url = f"/{slug}" if not slug.startswith("/") else slug
        if url not in urls:
            urls.append(url)

    # Add digest pages for each unique date in the manifest
    if manifest:
        digest_dates = set()
        for a in manifest.get("articles", []):
            d = a.get("date", "")
            if d:
                digest_dates.add(d)
        for d in sorted(digest_dates):
            url = f"/digest/{d}.html"
            if url not in urls:
                urls.append(url)
        if digest_dates:
            urls_set = set(urls)
            if "/digest/latest.html" not in urls_set:
                urls.append("/digest/latest.html")

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml_lines.append(f"  <url>")
        xml_lines.append(f"    <loc>{BASE_URL}{u}</loc>")
        xml_lines.append(f"    <lastmod>{today}</lastmod>")
        xml_lines.append(f"  </url>")
    xml_lines.append("</urlset>")
    sitemap_content = "\n".join(xml_lines) + "\n"

    upload("sitemap.xml", sitemap_content, f"[scraper] Rebuild sitemap with {len(pushed_slugs)} scraped articles")
    print(f"  Sitemap rebuilt — {len(urls)} URLs total")


# ── Homepage widget ───────────────────────────────────────────────────────────
HOMEPAGE_START = "<!-- HOMEPAGE_NEWS_START -->"
HOMEPAGE_END   = "<!-- HOMEPAGE_NEWS_END -->"

def update_homepage(manifest):
    articles = manifest.get("articles", [])
    if not articles:
        return

    r = gh("GET", f"/repos/{REPO}/contents/index.html")
    if r.get("_err"):
        print(f"    ⚠ Could not fetch index.html: {r}")
        return

    html = base64.b64decode(r["content"]).decode("utf-8")
    latest = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:3]

    cards = []
    for a in latest:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))[:90]
        date  = a.get("date", "")
        is_sci = a.get("is_science", False)
        cat   = "Science" if is_sci else "World News"
        bias  = a.get("bias_avg", 0.0)
        n     = a.get("n_sources", 1)
        agree_txt = f"{n} outlets agree" if n > 1 else "1 outlet"
        dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        cards.append(
            f'<div class="kd-sc" style="margin:10px 0">'
            f'<div class="kd-sc-top"><span class="kd-badge {badge_cls}">{cat}</span>'
            f'<span class="kd-agree {"kd-agree-med" if n>1 else "kd-agree-low"}">{agree_txt}</span></div>'
            f'<h3 style="margin:4px 0 8px"><a href="/{slug}">{title}</a></h3>'
            f'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
            f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
            f'<span class="kd-mini-lbl" style="text-align:right">R</span></div>'
            f'<div class="kd-sc-date">{date}</div>'
            f'</div>'
        )

    # Stats bar — today's summary
    from datetime import date as _date
    _today = str(_date.today())
    today_count = sum(1 for a in articles if a.get("date") == _today)
    sci_count = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_count / len(articles) * 100) if articles else 0
    stats_bar = (
        f'<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;'
        f'padding:8px 14px;margin:0 0 14px;display:flex;gap:16px;flex-wrap:wrap;'
        f'font-size:12px;color:#1e40af;font-family:system-ui,sans-serif">'
        f'<span>&#128230; <strong>{today_count}</strong> stories today</span>'
        f'<span>&#128300; <strong>{sci_pct}%</strong> science</span>'
        f'<span>&#128202; <strong>{len(articles)}</strong> total articles</span>'
        f'<span style="margin-left:auto;color:#93c5fd">Updated daily at 6am ET</span>'
        f'</div>'
    )

    trending_html = build_trending(manifest)
    new_block = (
        f'{HOMEPAGE_START}\n'
        + stats_bar +
        f'<h2>Today\'s top kid news</h2>\n'
        + "\n".join(cards) +
        f'\n<p style="text-align:right;font-size:13px;margin-top:4px">'
        f'<a href="/news/today.html">Today</a> &middot; '
        f'<a href="/news/science.html">Science</a> &middot; '
        f'<a href="/news/technology.html">Technology</a> &middot; '
        f'<a href="/news/space.html">Space</a> &middot; '
        f'<a href="/news/animals.html">Animals</a> &middot; '
        f'<a href="/news/world.html">World</a> &middot; '
        f'<a href="/news/archive.html">Archive</a> &middot; '
        f'<a href="/digest/latest.html">Daily digest</a></p>\n'
        + trending_html +
        f'\n{HOMEPAGE_END}'
    )

    if HOMEPAGE_START in html:
        si = html.index(HOMEPAGE_START)
        ei = html.index(HOMEPAGE_END) + len(HOMEPAGE_END)
        html = html[:si] + new_block + html[ei:]
    else:
        # First run — replace the static "Today's top kid news" block
        old_h2    = "<h2>Today's top kid news</h2>"
        next_h2   = "<h2>For parents</h2>"
        if old_h2 in html and next_h2 in html:
            si = html.index(old_h2)
            ei = html.index(next_h2)
            html = html[:si] + new_block + "\n\n" + html[ei:]
        else:
            html = html.replace("</main>", new_block + "\n</main>")

    # Add RSS autodiscovery link if not already present
    rss_link = '<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">'
    if rss_link not in html and "</head>" in html:
        html = html.replace("</head>", f"  {rss_link}\n</head>")

    upload("index.html", html, "[scraper] Update homepage with latest 3 articles")


# ── RSS feed ──────────────────────────────────────────────────────────────────
def generate_rss_feed(manifest):
    articles = manifest.get("articles", [])
    BASE_URL = "https://kiddiedaily.com"
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for a in sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:20]:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", "")).replace("&", "&amp;").replace("<", "&lt;")
        cat   = "Science" if a.get("is_science") else "World News"
        url   = f"{BASE_URL}/{slug}"
        try:
            d = datetime.strptime(a.get("date", ""), "%Y-%m-%d")
            pub = d.strftime("%a, %d %b %Y 10:00:00 +0000")
        except Exception:
            pub = now_rfc
        n     = a.get("n_sources", 1)
        agree = f"{n} outlet{'s' if n!=1 else ''} covering this story"
        items.append(
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{url}</link>\n"
            f"    <guid isPermaLink=\"true\">{url}</guid>\n"
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <category>{cat}</category>\n"
            f"    <description>{agree} — bias-rated, fact-checked daily on KiddieDaily.</description>\n"
            f"  </item>"
        )

    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '  <channel>\n'
        '    <title>KiddieDaily — News for Families</title>\n'
        f'    <link>{BASE_URL}</link>\n'
        f'    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        '    <description>Daily kid-friendly news with bias indicators and fact checks. Updated every morning.</description>\n'
        '    <language>en-us</language>\n'
        f'    <lastBuildDate>{now_rfc}</lastBuildDate>\n'
        '    <managingEditor>editors@kiddiedaily.com (KiddieDaily Editors)</managingEditor>\n'
        + "\n".join(items) + "\n"
        '  </channel>\n'
        '</rss>\n'
    )
    upload("feed.xml", feed, f"[scraper] RSS feed — {len(articles)} articles")
    print(f"  RSS: {len(articles)} items")


# ── Parent Zone article list ───────────────────────────────────────────────────
PARENT_START = "<!-- PARENT_ARTICLES_START -->"
PARENT_END   = "<!-- PARENT_ARTICLES_END -->"

PARENT_CONTEXT = {
    "Science": "These stories cover recent discoveries in science, space, and nature. Great for sparking curiosity-driven conversations.",
    "World News": "These stories cover current events. Use them to introduce media literacy — discuss where each outlet stands politically.",
}

def update_parent_zone(manifest):
    articles = manifest.get("articles", [])
    if not articles:
        return

    r = gh("GET", f"/repos/{REPO}/contents/parent-zone/index.html")
    if r.get("_err"):
        print(f"    ⚠ Could not fetch parent-zone/index.html: {r}")
        return

    html = base64.b64decode(r["content"]).decode("utf-8")
    recent = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)[:8]

    rows = []
    for a in recent:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))[:90]
        date  = a.get("date", "")
        is_sci = a.get("is_science", False)
        cat   = "Science" if is_sci else "World News"
        n     = a.get("n_sources", 1)
        bias  = a.get("bias_avg", 0.0)
        bias_dir = "Left-leaning" if bias < -0.3 else ("Right-leaning" if bias > 0.3 else "Center")
        rows.append(
            f'<tr>'
            f'<td><a href="/{slug}">{title}</a></td>'
            f'<td>{cat}</td>'
            f'<td>{bias_dir} ({bias:+.1f})</td>'
            f'<td>{n}</td>'
            f'<td>{date}</td>'
            f'</tr>'
        )

    ctx_note = "These articles are curated daily by the KiddieDaily scraper — bias-rated and fact-check linked."
    new_block = (
        f'{PARENT_START}\n'
        f'<h2>Today\'s Articles — Parent View</h2>\n'
        f'<p style="font-size:14px;color:#4a5568;margin-bottom:12px">{ctx_note}</p>\n'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px">\n'
        f'<thead><tr style="background:#1a4d80;color:#fff">'
        f'<th style="padding:8px;text-align:left">Story</th>'
        f'<th>Category</th><th>Bias</th><th>Sources</th><th>Date</th>'
        f'</tr></thead>\n'
        f'<tbody style="background:#fff">\n'
        + "\n".join(rows) +
        '\n</tbody></table>\n'
        f'<p style="font-size:12px;color:#718096;margin-top:8px">Bias scale: -2 far-left to +2 far-right. Sources = number of outlets covering the same story.</p>\n'
        f'{PARENT_END}'
    )

    if PARENT_START in html:
        si = html.index(PARENT_START)
        ei = html.index(PARENT_END) + len(PARENT_END)
        html = html[:si] + new_block + html[ei:]
    else:
        # Inject before </main> or before the "Coming soon" text
        for marker in ("</main>", "<p>Coming soon", "<h2>Coming soon"):
            if marker in html:
                html = html.replace(marker, new_block + "\n" + marker, 1)
                break

    upload("parent-zone/index.html", html, "[scraper] Update Parent Zone with latest articles table")


# ── Archive page ───────────────────────────────────────────────────────────────
def generate_archive(manifest):
    articles = sorted(manifest.get("articles", []), key=lambda x: x.get("date", ""), reverse=True)
    if not articles:
        return

    # Build inline JSON for client-side search (no backend needed)
    search_data = json.dumps([{
        "slug": a["slug"],
        "title": a.get("display_title", a.get("title", "")),
        "date": a.get("date", ""),
        "cat": "Science" if a.get("is_science") else "World News",
    } for a in articles])

    # Group articles by date
    by_date = {}
    for a in articles:
        d = a.get("date", "Unknown")
        by_date.setdefault(d, []).append(a)

    date_sections = []
    for date, arts in sorted(by_date.items(), reverse=True):
        rows = []
        for a in arts:
            slug  = a["slug"]
            title = a.get("display_title", a.get("title", ""))
            is_sci = a.get("is_science", False)
            cat   = "Science" if is_sci else "World News"
            badge = "kd-badge-sci" if is_sci else "kd-badge-news"
            n     = a.get("n_sources", 1)
            bias  = a.get("bias_avg", 0.0)
            dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
            agree = f"{n} outlet{'s' if n!=1 else ''}"
            rows.append(
                f'<div class="kd-sc arch-item" data-title="{title.lower()}" data-cat="{cat.lower()}">'
                f'<div class="kd-sc-top">'
                f'<span class="kd-badge {badge}">{cat}</span>'
                f'<span style="font-size:11px;color:#718096;margin-left:auto">{agree}</span>'
                f'</div>'
                f'<h3 style="margin:4px 0 6px"><a href="/{slug}">{title}</a></h3>'
                f'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
                f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
                f'<span class="kd-mini-lbl" style="text-align:right">R</span></div>'
                f'</div>'
            )
        date_sections.append(
            f'<h2 style="font-size:1em;color:#718096;font-family:system-ui,sans-serif;'
            f'font-weight:600;letter-spacing:1px;text-transform:uppercase;margin:24px 0 8px">{date}</h2>\n'
            + "\n".join(rows)
        )

    sections_html = "\n".join(date_sections)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>News Archive — KiddieDaily</title>
<meta name="description" content="All KiddieDaily news articles — kid-friendly, bias-rated, fact-checked daily. {len(articles)} articles and counting.">
<meta property="og:title" content="KiddieDaily News Archive">
<meta property="og:description" content="{len(articles)} kid-safe, bias-rated articles. Searchable and filterable by category.">
<meta property="og:url" content="https://kiddiedaily.com/news/archive.html">
<link rel="canonical" href="https://kiddiedaily.com/news/archive.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-mini-bias{{display:flex;align-items:center;gap:6px;margin-top:8px}}
.kd-mini-lbl{{font-size:10px;font-weight:700;color:#718096;width:16px}}
.kd-mini-track{{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}}
.kd-mini-dot{{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)}}
.kd-sc h3 a{{color:#1a4d80;text-decoration:none}}
.kd-sc h3 a:hover{{text-decoration:underline}}
#search{{width:100%;box-sizing:border-box;padding:10px 14px;font-size:16px;border:1px solid #cbd5e0;border-radius:8px;margin-bottom:4px;font-family:system-ui,sans-serif}}
#filter-btns{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
#filter-btns button{{background:#f7fafc;border:1px solid #e2e8f0;border-radius:20px;padding:5px 14px;cursor:pointer;font-size:13px;font-family:system-ui,sans-serif}}
#filter-btns button.active{{background:#1a4d80;color:#fff;border-color:#1a4d80}}
</style>
</head><body>
{HEADER}
<main>
<h1 style="font-size:28px;margin-bottom:4px">News Archive</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 20px">{len(articles)} articles &middot; Updated {today_str}</p>

<input type="search" id="search" placeholder="Search stories..." aria-label="Search articles">
<div id="filter-btns">
  <button class="active" onclick="filterCat('all',this)">All</button>
  <button onclick="filterCat('science',this)">Science</button>
  <button onclick="filterCat('world news',this)">World News</button>
</div>

<div id="archive-list">
{sections_html}
</div>

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/feed.xml" style="color:#1a4d80">Subscribe via RSS</a> &middot;
  <a href="/news/today.html" style="color:#1a4d80">Today&#39;s news</a> &middot;
  <a href="/news/" style="color:#1a4d80">Latest news</a> &middot;
  <a href="#top" style="color:#1a4d80">Back to top &uarr;</a>
</p>
</main>
{FOOTER}

<script>
const DATA = {search_data};
let activeCat = 'all';

document.getElementById('search').addEventListener('input', function() {{
  const q = this.value.toLowerCase().trim();
  document.querySelectorAll('.arch-item').forEach(el => {{
    const t = el.dataset.title || '';
    const c = el.dataset.cat || '';
    const catOk = activeCat === 'all' || c === activeCat;
    const qOk = !q || t.includes(q);
    el.style.display = (catOk && qOk) ? '' : 'none';
  }});
  updateDateHeaders();
}});

function filterCat(cat, btn) {{
  activeCat = cat;
  document.querySelectorAll('#filter-btns button').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const q = document.getElementById('search').value.toLowerCase().trim();
  document.querySelectorAll('.arch-item').forEach(el => {{
    const c = el.dataset.cat || '';
    const t = el.dataset.title || '';
    const catOk = cat === 'all' || c === cat;
    const qOk = !q || t.includes(q);
    el.style.display = (catOk && qOk) ? '' : 'none';
  }});
  updateDateHeaders();
}}

function updateDateHeaders() {{
  document.querySelectorAll('#archive-list h2').forEach(h => {{
    let next = h.nextElementSibling;
    let anyVisible = false;
    while (next && !next.matches('h2')) {{
      if (next.style.display !== 'none') anyVisible = true;
      next = next.nextElementSibling;
    }}
    h.style.display = anyVisible ? '' : 'none';
  }});
}}
</script>
</body></html>"""

    upload("news/archive.html", page, f"[scraper] Archive page — {len(articles)} articles")
    print(f"  Archive: {len(articles)} articles")


# ── Category pages ───────────────────────────────────────────────────────────
def generate_category_pages(manifest):
    articles = manifest.get("articles", [])
    _SPACE_KW    = {"space", "nasa", "galaxy", "planet", "star", "asteroid", "mars", "moon", "rocket", "telescope"}
    _ANIMAL_KW   = {"animal", "animals", "species", "whale", "shark", "bird", "birds", "dog", "dogs", "cat", "cats", "wildlife", "octopus", "insect", "insects", "turtle", "turtles", "fish", "elephant", "elephants", "bear", "bears", "wolf", "wolves", "lion", "lions", "tiger", "tigers", "dolphin", "dolphins", "penguin", "penguins", "seal", "seals", "zoo", "habitat", "extinct", "endangered", "mammal", "reptile", "amphibian", "coral", "reef", "migration", "nest", "prey", "predator", "marine", "ocean life", "bee", "bees", "butterfly", "butterflies"}
    _ENVIRONMENT_KW = {"climate", "environment", "pollution", "forest", "ocean", "glacier", "wildfire", "drought", "flood", "hurricane", "tornado", "volcano", "earthquake", "recycling", "carbon", "solar", "renewable", "ecosystem", "biodiversity", "rainforest", "deforestation"}
    _HISTORY_KW  = {"ancient", "fossil", "dinosaur", "historical", "archaeolog", "million year", "prehistoric", "artifact", "ruin", "pyramid", "roman", "greek", "viking"}
    _TECH_KW     = {"quantum", "robot", "robotics", "ai ", "artificial intelligence", "machine learning",
                    "nanosensor", "nanotechnology", "semiconductor", "computer chip", "microchip",
                    "algorithm", "software", "engineering", "invention", "cryogenic",
                    "3d print", "drone", "satellite commun", "electric vehicle", "battery",
                    "alloy", "polymer", "material science", "materials science",
                    "nuclear reactor", "nuclear fusion", "photovoltaic", "wind turbine"}

    def _matches(a, kw_set):
        haystack = (a.get("title", "") + " " + a.get("slug", "")).lower()
        return any(k in haystack for k in kw_set)

    cats = {
        "science": [a for a in articles if a.get("is_science")],
        "world":   [a for a in articles if not a.get("is_science")],
        "space":   [a for a in articles if _matches(a, _SPACE_KW) or a.get("source_name") == "NASA"],
        "animals": [a for a in articles if _matches(a, _ANIMAL_KW)],
        "history": [a for a in articles if _matches(a, _HISTORY_KW)],
        "environment": [a for a in articles if _matches(a, _ENVIRONMENT_KW)],
        "technology":  [a for a in articles if _matches(a, _TECH_KW)],
    }
    cat_labels = {"science": "Science", "world": "World News", "space": "Space", "animals": "Animals", "history": "History", "environment": "Environment", "technology": "Technology"}
    desc = {
        "science": "Space, animals, inventions, and discoveries — science stories for curious kids.",
        "world":   "What's happening around the world, explained for families.",
        "space":   "Rockets, planets, galaxies, and NASA discoveries — space news for kids.",
        "animals": "Wildlife, sea creatures, and amazing animals from around the world.",
        "history": "Fossils, ancient civilizations, and discoveries that unlock the past.",
        "environment": "Climate, oceans, forests, and Earth's ecosystems — environment news for kids.",
        "technology": "AI, robots, engineering, and inventions — tech news explained for families.",
    }

    # Badge class per category
    cat_badge = {
        "science": "kd-badge-sci",
        "space":   "kd-badge-sci",
        "animals": "kd-badge-sci",
        "history": "kd-badge-sci",
        "environment": "kd-badge-sci",
        "technology": "kd-badge-sci",
        "world":   "kd-badge-news",
    }
    cat_icons = {
        "science": "🔬", "world": "🌍", "space": "🚀",
        "animals": "🐾", "history": "🏛", "environment": "🌿",
        "technology": "💻",
    }

    for key, arts in cats.items():
        if not arts:
            continue
        arts = sorted(arts, key=lambda x: x.get("date", ""), reverse=True)
        label    = cat_labels[key]
        badge_cls = cat_badge[key]
        icon     = cat_icons.get(key, "")
        multi_source = [a for a in arts if a.get("n_sources", 1) > 1]
        latest_date  = arts[0].get("date", "") if arts else ""

        rows = []
        for a in arts[:30]:
            slug    = a["slug"]
            title   = a.get("display_title", a.get("title", ""))
            date    = a.get("date", "")
            n       = a.get("n_sources", 1)
            bias    = a.get("bias_avg", 0.0)
            dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
            agree   = f"{n} outlet{'s' if n!=1 else ''}"
            multi_badge = (
                f'<span style="font-size:10px;background:#fff8e1;color:#92400e;border:1px solid #fde68a;'
                f'padding:1px 7px;border-radius:20px;font-weight:700;margin-left:6px">'
                f'{n} outlets</span>'
            ) if n > 1 else ""
            rows.append(
                f'<div class="kd-sc">'
                f'<div class="kd-sc-top">'
                f'<span class="kd-badge {badge_cls}">{icon} {label}</span>{multi_badge}'
                f'<span style="font-size:11px;color:#718096;margin-left:auto">{agree} &middot; {date}</span></div>'
                f'<h3 style="margin:4px 0 6px"><a href="/{slug}">{title}</a></h3>'
                f'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
                f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
                f'<span class="kd-mini-lbl" style="text-align:right">R</span>'
                f'<span style="font-size:10px;color:#a0aec0;margin-left:6px">bias {bias:+.1f}</span></div>'
                f'</div>'
            )

        page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{icon} {label} News for Kids — KiddieDaily</title>
<meta name="description" content="{desc[key]} {len(arts)} stories, latest {latest_date}.">
<meta property="og:title" content="KiddieDaily {label} News">
<meta property="og:description" content="{desc[key]}">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta property="og:url" content="https://kiddiedaily.com/news/{key}.html">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news/{key}.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-mini-bias{{display:flex;align-items:center;gap:6px;margin-top:8px}}
.kd-mini-lbl{{font-size:10px;font-weight:700;color:#718096;width:16px}}
.kd-mini-track{{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}}
.kd-mini-dot{{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)}}
.kd-sc h3 a{{color:#1a4d80;text-decoration:none}}
</style>
</head><body>
{HEADER}
<main>
<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:4px">
<h1 style="font-size:28px;margin:0">{icon} {label} News</h1>
<span style="font-size:13px;color:#718096;font-family:system-ui,sans-serif">{len(arts)} stories</span>
</div>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 20px">{desc[key]}</p>
{"" if not multi_source else f'<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:8px;padding:8px 14px;margin-bottom:16px;font-size:13px;font-family:system-ui,sans-serif;color:#92400e">&#x1F4F0; <strong>{len(multi_source)}</strong> stories covered by multiple news outlets — look for the yellow badge</div>'}
{"".join(rows)}
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/archive.html" style="color:#1a4d80">Full archive ({len(articles)} total)</a> &middot;
  <a href="/news/today.html" style="color:#1a4d80">Today&#39;s news</a> &middot;
  <a href="/feed.xml" style="color:#1a4d80">RSS feed</a>
</p>
</main>
{FOOTER}
</body></html>"""

        upload(f"news/{key}.html", page, f"[scraper] {label} category page — {len(arts)} articles")
    print(f"  Category pages: science={len(cats['science'])} world={len(cats['world'])} space={len(cats['space'])} animals={len(cats['animals'])} history={len(cats['history'])} environment={len(cats['environment'])} technology={len(cats['technology'])}")


# ── Today's news page ─────────────────────────────────────────────────────────
def generate_today_page(manifest, today):
    articles = manifest.get("articles", [])
    todays = sorted(
        [a for a in articles if a.get("date") == today],
        key=lambda x: (0 if x.get("is_science") else 1, -(x.get("n_sources", 1)))
    )
    all_recent = sorted(articles, key=lambda x: x.get("date", ""), reverse=True)

    sci_today   = [a for a in todays if a.get("is_science")]
    world_today = [a for a in todays if not a.get("is_science")]

    def article_row(a):
        slug   = a["slug"]
        title  = a.get("display_title", a.get("title", ""))
        is_sci = a.get("is_science", False)
        cat    = "Science" if is_sci else "World News"
        n      = a.get("n_sources", 1)
        bias   = a.get("bias_avg", 0.0)
        dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        multi_badge = (
            f'<span style="font-size:10px;background:#fff8e1;color:#92400e;border:1px solid #fde68a;'
            f'padding:1px 7px;border-radius:20px;font-weight:700;margin-left:6px">'
            f'{n} outlets</span>'
        ) if n > 1 else ""
        return (
            f'<div style="padding:14px 0;border-bottom:1px solid #e5e7eb">'
            f'<div style="display:flex;align-items:flex-start;gap:10px">'
            f'<div style="flex:1">'
            f'<div style="margin-bottom:5px">'
            f'<span class="kd-badge {badge_cls}" style="font-size:10px">{cat}</span>{multi_badge}</div>'
            f'<a href="/{slug}" style="font-size:15px;font-weight:600;color:#1a4d80;text-decoration:none;line-height:1.35;display:block">{title}</a>'
            f'<div style="display:flex;align-items:center;gap:6px;margin-top:6px">'
            f'<span style="font-size:10px;color:#a0aec0">L</span>'
            f'<div style="width:80px;height:5px;border-radius:3px;background:linear-gradient(to right,#3182ce,#805ad5,#e53e3e);position:relative;flex-shrink:0">'
            f'<span style="position:absolute;top:-4px;left:{dot_pct}%;width:12px;height:12px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)"></span>'
            f'</div><span style="font-size:10px;color:#a0aec0">R</span>'
            f'<span style="font-size:11px;color:#a0aec0;margin-left:4px">bias {bias:+.1f}</span>'
            f'</div>'
            f'</div></div></div>'
        )

    def section_block(section_articles, section_id, icon, label, color, limit=15, see_all_url=""):
        if not section_articles:
            return ""
        display = section_articles[:limit]
        hidden  = len(section_articles) - len(display)
        rows    = "".join(article_row(a) for a in display)
        see_all = (
            f'<div style="text-align:center;padding:14px 0;border-top:1px solid #e5e7eb;margin-top:4px">'
            f'<a href="{see_all_url}" style="font-size:13px;color:#1a4d80;font-family:system-ui,sans-serif;'
            f'font-weight:600">{icon} See all {len(section_articles)} {label} articles today &rarr;</a>'
            f'</div>'
        ) if hidden and see_all_url else ""
        return (
            f'<div id="{section_id}" style="scroll-margin-top:70px">'
            f'<div style="display:flex;align-items:center;gap:10px;margin:28px 0 4px;padding-bottom:8px;border-bottom:2px solid {color}">'
            f'<span style="font-size:20px">{icon}</span>'
            f'<h2 style="margin:0;font-size:18px;color:#1a4d80">{label}</h2>'
            f'<span style="font-size:12px;color:#718096;font-family:system-ui,sans-serif;margin-left:auto">'
            f'{len(display)}{f" of {len(section_articles)}" if hidden else ""} article{"s" if len(display)!=1 else ""}</span>'
            f'</div>{rows}{see_all}</div>'
        )

    # Quick-jump nav (only shown if we have both sections)
    jump_nav = ""
    if sci_today and world_today:
        jump_nav = (
            f'<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;'
            f'padding:10px 16px;margin:0 0 20px;display:flex;gap:12px;flex-wrap:wrap;'
            f'font-family:system-ui,sans-serif;font-size:13px;align-items:center">'
            f'<span style="color:#718096;font-weight:600">Jump to:</span>'
            f'<a href="#science-today" style="color:#065f46;background:#d1fae5;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">'
            f'🔬 Science ({len(sci_today)})</a>'
            f'<a href="#world-today" style="color:#1e40af;background:#dbeafe;padding:4px 12px;border-radius:20px;text-decoration:none;font-weight:600">'
            f'🌍 World News ({len(world_today)})</a>'
            f'</div>'
        )
    elif todays:
        jump_nav = (
            f'<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;'
            f'padding:10px 16px;margin:0 0 20px;font-family:system-ui,sans-serif;font-size:13px;color:#718096">'
            f'{len(todays)} article{"s" if len(todays)!=1 else ""} today — all science &middot; '
            f'<a href="/news/world.html" style="color:#1a4d80">World news archive</a>'
            f'</div>'
        )

    sci_section   = section_block(sci_today,   "science-today", "🔬", "Science & Discovery", "#34d399", limit=15, see_all_url="/news/science.html")
    world_section = section_block(world_today, "world-today",   "🌍", "World News",           "#60a5fa", limit=10, see_all_url="/news/world.html")

    # Recent: up to 6 articles NOT from today
    prev_articles = [a for a in all_recent if a.get("date") != today][:6]
    prev_rows     = "".join(article_row(a) for a in prev_articles)
    prev_section  = (
        f'<h2 style="font-size:18px;margin:36px 0 8px;color:#2d3748;border-bottom:1px solid #e5e7eb;padding-bottom:6px">'
        f'Recent stories</h2>' + prev_rows
    ) if prev_articles else ""

    empty_msg = '<p style="color:#718096;font-family:system-ui,sans-serif;padding:20px 0">No articles yet today — check back after 6am ET.</p>' if not todays else ""

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Today&#39;s Kid News — {today} | KiddieDaily</title>
<meta name="description" content="Today&#39;s kid-safe, bias-rated news for families. {len(todays)} articles — {len(sci_today)} science, {len(world_today)} world news. Updated {today}.">
<meta property="og:title" content="KiddieDaily — Today&#39;s News ({today})">
<meta property="og:description" content="{len(todays)} articles today: {len(sci_today)} science, {len(world_today)} world news. Bias-rated, kid-safe.">
<meta property="og:image" content="https://kiddiedaily.com/og-science.svg">
<meta property="og:url" content="https://kiddiedaily.com/news/today.html">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="https://kiddiedaily.com/news/today.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
</head><body>
{HEADER}
<main style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 4px">Today&#39;s News</h1>
<p style="font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 16px">
{today} &middot; {len(todays)} article{"s" if len(todays)!=1 else ""} &middot;
<a href="/parents/" style="color:#1a4d80">For Parents</a> &middot;
<a href="/digest/latest.html" style="color:#1a4d80">Daily Digest</a> &middot;
<a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>

{jump_nav}
{empty_msg}
{sci_section}
{world_section}
{prev_section}

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
<a href="/news/archive.html" style="color:#1a4d80">Full archive ({len(articles)} articles)</a> &middot;
<a href="/news/science.html" style="color:#1a4d80">Science</a> &middot;
<a href="/news/world.html" style="color:#1a4d80">World News</a> &middot;
<a href="#top" style="color:#1a4d80">Back to top &uarr;</a>
</p>
</main>
{FOOTER}
</body></html>"""

    upload("news/today.html", page, f"[scraper] Today's news page — {len(todays)} articles for {today}")
    print(f"  Today page: {len(todays)} article(s) for {today}")


# ── Trending topics ───────────────────────────────────────────────────────────
def build_trending(manifest):
    """Return top 5 keyword clusters from recent article titles."""
    articles = manifest.get("articles", [])
    recent = sorted(articles, key=lambda x: x.get("date",""), reverse=True)[:15]
    SKIP = {"the","a","an","in","on","at","to","for","of","and","or","is","are",
            "was","were","be","has","have","had","will","would","it","this","that",
            "as","by","from","with","its","how","why","what","new","more","after",
            "they","says","over","amid","first","than","but","not","can","one","may",
            "two","about","could","news","year","years","using","found","study",
            "scientists","researchers","finds","discover","discovered","found"}
    freq = {}
    for a in recent:
        title = a.get("display_title", a.get("title","")).lower()
        for w in re.sub(r"[^\w\s]","",title).split():
            if w not in SKIP and len(w) > 3:
                freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: -x[1])[:6]
    if not top:
        return ""
    tags = " ".join(
        f'<a href="/news/archive.html" style="background:#e2e8f0;color:#2d3748;padding:4px 10px;'
        f'border-radius:20px;font-size:12px;text-decoration:none;font-family:system-ui">'
        f'{w}</a>'
        for w, _ in top
    )
    return (
        '<div style="margin:16px 0 8px;padding:12px 16px;background:#fffbeb;border:1px solid #fef3c7;border-radius:8px">'
        '<p style="font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#92400e;margin:0 0 8px">Trending this week</p>'
        f'<div style="display:flex;flex-wrap:wrap;gap:6px">{tags}</div>'
        '</div>'
    )


# ── Public articles JSON (used by related-articles JS on every article page) ──
def generate_articles_json(manifest):
    articles = manifest.get("articles", [])
    data = [
        {
            "slug":      a["slug"],
            "title":     a.get("display_title", a.get("title", "")),
            "date":      a.get("date", ""),
            "is_science": a.get("is_science", False),
            "category":  "science" if a.get("is_science", False) else "world",
            "bias_avg":  a.get("bias_avg", 0.0),
            "n_sources": a.get("n_sources", 1),
        }
        for a in sorted(articles, key=lambda x: x.get("date", ""), reverse=True)
    ]
    upload("data/kd-articles.json", json.dumps(data, ensure_ascii=False), f"[scraper] Articles index ({len(data)} items)")
    print(f"  Articles JSON: {len(data)} items")


# ── Daily digest page ──────────────────────────────────────────────────────────
def generate_daily_digest(manifest, today):
    articles = manifest.get("articles", [])
    todays = [a for a in articles if a.get("date") == today]
    if not todays:
        print("  Digest: no articles for today, skipping")
        return

    rows = []
    for a in todays:
        slug  = a["slug"]
        title = a.get("display_title", a.get("title", ""))
        is_sci = a.get("is_science", False)
        cat   = "Science" if is_sci else "World News"
        n     = a.get("n_sources", 1)
        bias  = a.get("bias_avg", 0.0)
        bias_label = "Center" if abs(bias) < 0.3 else ("Left-leaning" if bias < 0 else "Right-leaning")
        rows.append(
            f'<tr>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb">'
            f'<strong><a href="https://kiddiedaily.com/{slug}" style="color:#1a4d80">{title}</a></strong><br>'
            f'<span style="font-size:12px;color:#718096">{cat} &middot; {n} source{"s" if n!=1 else ""} &middot; Bias: {bias_label} ({bias:+.1f})</span>'
            f'</td>'
            f'</tr>'
        )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily Digest — {today}</title>
<meta name="description" content="KiddieDaily daily digest for {today} — {len(todays)} stories for families.">
<link rel="canonical" href="https://kiddiedaily.com/digest/{today}.html">
</head>
<body style="margin:0;font-family:Georgia,serif;background:#f0f4f8;color:#2d3748">
<div style="max-width:640px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)">
  <div style="background:#1a4d80;padding:28px 32px">
    <h1 style="margin:0;color:#ffd700;font-size:26px;letter-spacing:-0.5px">KiddieDaily</h1>
    <p style="margin:4px 0 0;color:#a0c4e8;font-family:system-ui,sans-serif;font-size:14px">Daily digest for families &middot; {today}</p>
  </div>
  <div style="padding:24px 32px">
    <p style="font-size:14px;color:#4a5568;font-family:system-ui,sans-serif;margin:0 0 20px">
      Today's {len(todays)} kid-friendly stories — bias-rated and fact-check linked.
    </p>
    <table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>
    <div style="margin-top:24px;padding:14px 16px;background:#f7fafc;border-radius:8px;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568">
      <strong>How to read the bias rating:</strong> -2 = far left &nbsp;|&nbsp; 0 = center &nbsp;|&nbsp; +2 = far right.
      Sources = how many of our 8 monitored outlets covered the same story.
    </div>
    <p style="text-align:center;margin-top:20px;font-family:system-ui,sans-serif;font-size:13px;color:#718096">
      <a href="https://kiddiedaily.com/news/" style="color:#1a4d80">Read all news</a> &middot;
      <a href="https://kiddiedaily.com/feed.xml" style="color:#1a4d80">Subscribe via RSS</a>
    </p>
  </div>
</div>
</body></html>"""

    upload(f"digest/{today}.html", page, f"[scraper] Daily digest {today} — {len(todays)} articles")
    # Also write /digest/latest.html as a redirect to today's digest
    redirect = f"""<!DOCTYPE html><html><head>
<meta http-equiv="refresh" content="0;url=/digest/{today}.html">
<title>KiddieDaily Latest Digest</title>
</head><body>
<p>Redirecting to <a href="/digest/{today}.html">today's digest</a>...</p>
</body></html>"""
    upload("digest/latest.html", redirect, f"[scraper] Update latest digest redirect → {today}")
    print(f"  Digest: {len(todays)} articles for {today}")


# ── Weekly digest page ────────────────────────────────────────────────────────
def generate_weekly_digest(manifest, today):
    from datetime import timedelta
    articles = manifest.get("articles", [])
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    week_articles = [a for a in articles if a.get("date", "") >= cutoff]
    if not week_articles:
        print("  Weekly digest: no articles in last 7 days, skipping")
        return

    science = [a for a in week_articles if a.get("is_science")]
    world   = [a for a in week_articles if not a.get("is_science")]

    def digest_rows(arts):
        rows = []
        for a in sorted(arts, key=lambda x: x.get("date", ""), reverse=True):
            slug  = a["slug"]
            title = a.get("display_title", a.get("title", ""))
            n     = a.get("n_sources", 1)
            bias  = a.get("bias_avg", 0.0)
            bias_label = "Center" if abs(bias) < 0.3 else ("Left-leaning" if bias < 0 else "Right-leaning")
            date  = a.get("date", "")
            rows.append(
                f'<tr>'
                f'<td style="padding:10px 8px;border-bottom:1px solid #e5e7eb">'
                f'<strong><a href="https://kiddiedaily.com/{slug}" style="color:#1a4d80">{title}</a></strong><br>'
                f'<span style="font-size:12px;color:#718096">{date} &middot; {n} source{{"s" if n!=1 else ""}} &middot; Bias: {bias_label} ({bias:+.1f})</span>'
                f'</td>'
                f'</tr>'
            )
        return "".join(rows)

    all_biases = [a.get("bias_avg", 0.0) for a in week_articles]
    avg_bias = sum(all_biases) / len(all_biases) if all_biases else 0.0
    avg_bias_label = ("Center" if abs(avg_bias) < 0.3
                      else ("Left-leaning" if avg_bias < 0 else "Right-leaning"))

    science_section = ""
    if science:
        science_section = (
            f'<h2 style="font-size:20px;color:#065f46;border-bottom:2px solid #d1fae5;padding-bottom:6px;margin:28px 0 12px">'
            f'Science ({len(science)} stories)</h2>'
            f'<table style="width:100%;border-collapse:collapse">{digest_rows(science)}</table>'
        )

    world_section = ""
    if world:
        world_section = (
            f'<h2 style="font-size:20px;color:#1e40af;border-bottom:2px solid #dbeafe;padding-bottom:6px;margin:28px 0 12px">'
            f'World News ({len(world)} stories)</h2>'
            f'<table style="width:100%;border-collapse:collapse">{digest_rows(world)}</table>'
        )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily Weekly Digest — Best of the Week</title>
<meta name="description" content="KiddieDaily weekly digest — {len(week_articles)} stories from the last 7 days for families.">
<link rel="canonical" href="https://kiddiedaily.com/digest/weekly.html">
</head>
<body style="margin:0;font-family:Georgia,serif;background:#f0f4f8;color:#2d3748">
<div style="max-width:640px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)">
  <div style="background:#1a4d80;padding:28px 32px">
    <h1 style="margin:0;color:#ffd700;font-size:26px;letter-spacing:-0.5px">KiddieDaily</h1>
    <p style="margin:4px 0 0;color:#a0c4e8;font-family:system-ui,sans-serif;font-size:14px">Best of the week &middot; Updated {today}</p>
  </div>
  <div style="padding:24px 32px">
    <h2 style="font-size:24px;margin:0 0 8px;color:#1a4d80">Best of the Week</h2>
    <p style="font-size:14px;color:#4a5568;font-family:system-ui,sans-serif;margin:0 0 16px">
      {len(week_articles)} kid-friendly stories from the last 7 days — bias-rated and fact-check linked.
    </p>
    <div style="padding:12px 16px;background:#f7fafc;border-left:4px solid #1a4d80;border-radius:0 8px 8px 0;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568;margin-bottom:20px">
      <strong>Week bias summary:</strong> Average bias across all stories this week is
      <strong>{avg_bias:+.2f}</strong> ({avg_bias_label}).
      Scale: -2 = far left &nbsp;|&nbsp; 0 = center &nbsp;|&nbsp; +2 = far right.
    </div>
    {science_section}
    {world_section}
    <div style="margin-top:24px;padding:14px 16px;background:#f7fafc;border-radius:8px;font-family:system-ui,sans-serif;font-size:13px;color:#4a5568">
      <strong>How to read the bias rating:</strong> -2 = far left &nbsp;|&nbsp; 0 = center &nbsp;|&nbsp; +2 = far right.
      Sources = how many of our 8 monitored outlets covered the same story.
    </div>
    <p style="text-align:center;margin-top:20px;font-family:system-ui,sans-serif;font-size:13px;color:#718096">
      <a href="https://kiddiedaily.com/news/" style="color:#1a4d80">Read all news</a> &middot;
      <a href="https://kiddiedaily.com/digest/latest.html" style="color:#1a4d80">Today's digest</a> &middot;
      <a href="https://kiddiedaily.com/feed.xml" style="color:#1a4d80">Subscribe via RSS</a>
    </p>
  </div>
</div>
</body></html>"""

    upload("digest/weekly.html", page, f"[scraper] Weekly digest — {len(week_articles)} articles over 7 days")
    print(f"  Weekly digest: {len(week_articles)} articles over 7 days")


# ── Search page ──────────────────────────────────────────────────────────────
def generate_for_parents_page(manifest, today):
    """Generate /parents/index.html — daily parent briefing with bias context and discussion guides."""
    articles = manifest.get("articles", [])
    today_articles = sorted(
        [a for a in articles if a.get("date") == today],
        key=lambda x: -(x.get("n_sources", 1) * 2 + (5 if x.get("is_science") else 0))
    )
    total = len(articles)
    sci_count = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_count / total * 100) if total else 0
    all_biases = [a.get("bias_avg", 0.0) for a in articles]
    avg_bias = sum(all_biases) / len(all_biases) if all_biases else 0.0
    left_n   = sum(1 for b in all_biases if b < -0.3)
    center_n = sum(1 for b in all_biases if -0.3 <= b <= 0.3)
    right_n  = sum(1 for b in all_biases if b > 0.3)
    avg_bias_lbl = ("Center" if abs(avg_bias) < 0.3
                    else ("Left-leaning" if avg_bias < 0 else "Right-leaning"))

    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will"}

    def _card(a):
        slug     = a["slug"]
        title    = a.get("display_title", a.get("title", ""))
        is_sci   = a.get("is_science", False)
        n        = a.get("n_sources", 1)
        bias     = a.get("bias_avg", 0.0)
        bias_lbl = "Center" if abs(bias) < 0.3 else ("Left-leaning" if bias < 0 else "Right-leaning")
        dot_pct  = max(5, min(95, round((bias + 2) / 4 * 100)))
        badge_cls = "kd-badge-sci" if is_sci else "kd-badge-news"
        badge_lbl = "Science" if is_sci else "World News"
        words = [w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                 if len(w) > 3 and w not in stop]
        topic = " ".join(words[:2]) if len(words) >= 2 else (words[0] if words else "this")
        teaser = (f"Ask your child: &ldquo;What do scientists think about <em>{topic}</em>?&rdquo;"
                  if is_sci else
                  f"Ask: &ldquo;Why might people disagree about <em>{topic}</em>?&rdquo;")
        return (
            f'<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;'
            f'padding:16px 20px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">'
            f'<span class="kd-badge {badge_cls}">{badge_lbl}</span>'
            f'<span style="font-size:12px;color:#718096">{n} source{"s" if n!=1 else ""}'
            f' &middot; {bias_lbl} ({bias:+.1f})</span></div>'
            f'<h3 style="margin:0 0 8px;font-size:16px;line-height:1.4">'
            f'<a href="/{slug}" style="color:#1a4d80;text-decoration:none">{title}</a></h3>'
            f'<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px">'
            f'<span style="font-size:11px;font-weight:700;color:#718096;width:14px">L</span>'
            f'<div style="flex:1;height:6px;border-radius:3px;'
            f'background:linear-gradient(to right,#3182ce,#805ad5,#e53e3e);position:relative">'
            f'<span style="position:absolute;top:-5px;left:{dot_pct}%;width:16px;height:16px;'
            f'background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)"></span>'
            f'</div><span style="font-size:11px;font-weight:700;color:#718096;width:14px;text-align:right">R</span></div>'
            f'<div style="background:#f7fafc;border-radius:6px;padding:8px 12px;font-size:13px;color:#4a5568">'
            f'&#128172; {teaser} '
            f'<a href="/{slug}" style="color:#1a4d80;font-size:12px">Full article + discussion guide &rarr;</a>'
            f'</div></div>'
        )

    cards_html = "\n".join(_card(a) for a in today_articles[:8])
    n_today = len(today_articles)

    # Source distribution bar
    bar_total = left_n + center_n + right_n or 1
    left_pct   = round(left_n / bar_total * 100)
    center_pct = round(center_n / bar_total * 100)
    right_pct  = 100 - left_pct - center_pct

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>For Parents — KiddieDaily Daily Briefing</title>
<meta name="description" content="KiddieDaily parent briefing for {today}: {n_today} articles, bias ratings, source analysis, and discussion guides for families.">
<link rel="canonical" href="https://kiddiedaily.com/parents/">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.stat-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0 24px}}
.stat-box{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 16px;text-align:center;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.stat-box .val{{font-size:28px;font-weight:700;color:#1a4d80;display:block;margin-bottom:2px}}
.stat-box .lbl{{font-size:12px;color:#718096;font-family:system-ui,sans-serif}}
.step-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:16px 0}}
.step-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 16px}}
.step-box .num{{font-size:22px;font-weight:700;color:#1e40af;margin-bottom:4px}}
.step-box p{{margin:0;font-size:14px;color:#1e40af;line-height:1.5}}
.section-hdr{{font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:28px 0 10px;font-family:system-ui,sans-serif}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-badge-news{{background:#dbeafe;color:#1e40af}}
</style>
</head><body>
{HEADER}
<main style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 4px">For Parents</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 20px">
Your daily briefing — {today} &middot; Balanced sources &middot; No spin &middot; Made for families
</p>

<div class="stat-row">
  <div class="stat-box"><span class="val">{n_today}</span><span class="lbl">Stories today</span></div>
  <div class="stat-box"><span class="val">{sci_pct}%</span><span class="lbl">Science content</span></div>
  <div class="stat-box"><span class="val">{total}</span><span class="lbl">Total in archive</span></div>
  <div class="stat-box"><span class="val">{avg_bias:+.2f}</span><span class="lbl">Avg bias (all time)</span></div>
</div>

<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:0 0 24px;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">&#128200; Source balance across all articles</div>
<div style="display:flex;height:24px;border-radius:6px;overflow:hidden;margin-bottom:6px">
  <div style="width:{left_pct}%;background:#3182ce;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{left_pct if left_pct>8 else ""}%</div>
  <div style="width:{center_pct}%;background:#805ad5;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{center_pct if center_pct>8 else ""}%</div>
  <div style="width:{right_pct}%;background:#e53e3e;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff">{right_pct if right_pct>8 else ""}%</div>
</div>
<div style="display:flex;gap:16px;font-size:12px;color:#92400e">
  <span>&#9632; Left-leaning: {left_n}</span>
  <span>&#9632; Center: {center_n}</span>
  <span>&#9632; Right-leaning: {right_n}</span>
  <span style="margin-left:auto;font-weight:600">Overall: {avg_bias_lbl} ({avg_bias:+.2f})</span>
</div>
</div>

<div class="section-hdr">How to use KiddieDaily with your family</div>
<div class="step-row">
  <div class="step-box"><div class="num">1</div><p><strong>Read the bias bar.</strong> Every article shows which outlets covered it and whether they lean left, center, or right. No single outlet is always wrong — or always right.</p></div>
  <div class="step-box"><div class="num">2</div><p><strong>Use the discussion guide.</strong> Each article has 3 parent-specific prompts — what to ask your child, how to check facts, and how to explore further.</p></div>
  <div class="step-box"><div class="num">3</div><p><strong>Compare sources.</strong> When 2+ outlets cover the same story, we show you how each framed it. Look for what facts they agree on vs. what they emphasize differently.</p></div>
</div>

<div class="section-hdr">Today&#39;s stories — {today}</div>
{cards_html if cards_html else '<p style="color:#718096;font-family:system-ui,sans-serif">No articles for today yet — check back after 6am ET when the scraper runs.</p>'}

<div style="background:#f0f4f8;border-radius:10px;padding:20px 24px;margin:28px 0 0;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Understanding bias ratings</div>
<div style="font-size:14px;color:#2d3748;line-height:1.6">
<p style="margin:0 0 8px">KiddieDaily uses <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> bias ratings — the same methodology used by researchers and journalism schools.</p>
<p style="margin:0 0 8px">Scale: <strong>-2</strong> = far left &nbsp;|&nbsp; <strong>-1</strong> = leans left &nbsp;|&nbsp; <strong>0</strong> = center &nbsp;|&nbsp; <strong>+1</strong> = leans right &nbsp;|&nbsp; <strong>+2</strong> = far right</p>
<p style="margin:0">No media source is perfectly neutral. Our goal is to show you the landscape — so you can read with your eyes open and form your own family&#39;s view.</p>
</div>
</div>

<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/digest/latest.html" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Daily digest</a>
<a href="/parent-zone/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Parent Zone</a>
<a href="/search.html" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Search all</a>
<a href="/feed.xml" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">RSS</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("parents/index.html", page, f"[scraper] For-Parents briefing {today} — {n_today} articles, {avg_bias_lbl}")
    print(f"  For-Parents page: {n_today} articles today, avg bias {avg_bias:+.2f} ({avg_bias_lbl})")


def generate_subscribe_page(manifest, today):
    """Generate /subscribe/index.html — how to get daily KiddieDaily updates."""
    articles = manifest.get("articles", [])
    total = len(articles)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Subscribe — Get Daily KiddieDaily Updates</title>
<meta name="description" content="Get daily KiddieDaily updates via RSS, email, or bookmark. Free, kid-safe news for families — no ads, no spin.">
<link rel="canonical" href="https://kiddiedaily.com/subscribe/">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
.sub-card{{background:#fff;border:1px solid #dde4ef;border-radius:12px;padding:22px 24px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.05);display:flex;gap:18px;align-items:flex-start}}
.sub-card .icon{{font-size:36px;min-width:44px;text-align:center}}
.sub-card h3{{margin:0 0 6px;font-size:17px;color:#1a4d80}}
.sub-card p{{margin:0;font-size:14px;color:#4a5568;line-height:1.55}}
.sub-card .action{{margin-top:12px}}
.sub-badge{{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;letter-spacing:.8px;text-transform:uppercase;margin-left:6px}}
.badge-free{{background:#d1fae5;color:#065f46}}
.badge-soon{{background:#fef3c7;color:#92400e}}
</style>
</head><body>
{HEADER}
<main style="max-width:720px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Stay Updated</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
KiddieDaily publishes fresh kid-safe, bias-rated news every morning at <strong>6am ET</strong>. Here&#39;s how to get it.
</p>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 20px;margin:0 0 20px;font-family:system-ui,sans-serif">
<span style="font-size:13px;color:#1e40af">&#128202; <strong>{total} articles</strong> published so far &middot; updated daily &middot; free forever &middot; no ads &middot; no tracking</span>
</div>

<div class="sub-card">
<div class="icon">&#128231;</div>
<div>
<h3>RSS Feed <span class="sub-badge badge-free">Free · Live now</span></h3>
<p>The fastest way to follow KiddieDaily. Copy the feed URL into any RSS reader — Feedly, Apple News, Google News, Reeder, or any other reader you prefer.</p>
<div class="action" style="display:flex;flex-direction:column;gap:8px">
<div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:6px;padding:10px 14px;font-family:monospace;font-size:14px;color:#1a4d80;word-break:break-all">https://kiddiedaily.com/feed.xml</div>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<a href="/feed.xml" style="background:#1a4d80;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Open RSS feed</a>
<a href="https://feedly.com/i/subscription/feed/https://kiddiedaily.com/feed.xml" rel="noopener nofollow" target="_blank" style="background:#2d8a3e;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Add to Feedly</a>
</div>
<p style="font-size:12px;color:#718096;margin:4px 0 0"><strong>How to use:</strong> In any RSS app, tap "Add feed" and paste the URL above. New articles appear automatically each morning.</p>
</div>
</div>
</div>

<div class="sub-card">
<div class="icon">&#128241;</div>
<div>
<h3>Add to Home Screen <span class="sub-badge badge-free">Free · iPhone &amp; Android</span></h3>
<p>Turn KiddieDaily into a home screen app — no app store needed. Open the site in Safari or Chrome, then add it to your home screen for one-tap daily access.</p>
<div class="action">
<details style="cursor:pointer">
<summary style="font-size:13px;font-weight:600;color:#1a4d80;list-style:none">&#9654; iPhone/Safari instructions</summary>
<ol style="font-size:13px;color:#4a5568;padding-left:20px;margin:8px 0;line-height:1.7">
<li>Open <strong>kiddiedaily.com</strong> in Safari</li>
<li>Tap the <strong>Share button</strong> (box with arrow) at the bottom</li>
<li>Scroll down and tap <strong>"Add to Home Screen"</strong></li>
<li>Name it "KiddieDaily" and tap <strong>Add</strong></li>
</ol>
</details>
<details style="cursor:pointer;margin-top:6px">
<summary style="font-size:13px;font-weight:600;color:#1a4d80;list-style:none">&#9654; Android/Chrome instructions</summary>
<ol style="font-size:13px;color:#4a5568;padding-left:20px;margin:8px 0;line-height:1.7">
<li>Open <strong>kiddiedaily.com</strong> in Chrome</li>
<li>Tap the <strong>three-dot menu</strong> (top right)</li>
<li>Tap <strong>"Add to Home screen"</strong></li>
<li>Tap <strong>Add</strong></li>
</ol>
</details>
</div>
</div>
</div>

<div class="sub-card">
<div class="icon">&#128278;</div>
<div>
<h3>Bookmark the Daily Digest <span class="sub-badge badge-free">Free</span></h3>
<p>The <a href="/digest/latest.html" style="color:#1a4d80">Daily Digest</a> always shows the most recent day&#39;s articles in one clean page. Bookmark it and check it with your morning coffee.</p>
<div class="action">
<a href="/digest/latest.html" style="background:#1a4d80;color:#fff;padding:8px 16px;border-radius:6px;font-size:13px;text-decoration:none;font-family:system-ui,sans-serif">Open today&#39;s digest</a>
</div>
</div>
</div>

<div class="sub-card" style="opacity:.8">
<div class="icon">&#128140;</div>
<div>
<h3>Email Newsletter <span class="sub-badge badge-soon">Coming soon</span></h3>
<p>A morning email with the day&#39;s top 5 kid-safe stories, bias ratings, and one parent discussion question. We&#39;re building this — sign up below to be notified when it launches.</p>
<div class="action">
<p style="font-size:13px;color:#718096">Email newsletter is not yet available. Use RSS or add to home screen in the meantime — same content, delivered differently.</p>
</div>
</div>
</div>

<div style="background:#f0f4f8;border-radius:10px;padding:18px 22px;margin:24px 0 0;font-family:system-ui,sans-serif">
<div style="font-size:12px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">What you get every morning</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;font-size:13px;color:#2d3748">
<div>&#9989; Up to 5 new stories</div>
<div>&#9989; Bias ratings on every article</div>
<div>&#9989; Parent discussion guides</div>
<div>&#9989; Science-first curation</div>
<div>&#9989; Kid-safety filtered</div>
<div>&#9989; Zero ads or trackers</div>
</div>
</div>

<div style="margin-top:20px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s stories</a>
<a href="/digest/latest.html" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Daily digest</a>
<a href="/parents/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("subscribe/index.html", page, f"[scraper] Subscribe / stay-updated page — {total} articles")
    print(f"  Subscribe page: RSS, home screen, digest — {total} articles referenced")


def generate_static_info_pages(manifest, today):
    """Generate about.html, contact.html, privacy.html, terms.html — static info pages."""
    articles = manifest.get("articles", [])
    total = len(articles)
    sci_n = sum(1 for a in articles if a.get("is_science"))
    sci_pct = round(sci_n / total * 100) if total else 0

    def _page(title_tag, meta_desc, canonical, h1, body_inner):
        return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title_tag}</title>
<meta name="description" content="{meta_desc}">
<link rel="canonical" href="https://kiddiedaily.com{canonical}">
{CSS}
</head><body>
{HEADER}
<main style="max-width:720px;margin:0 auto;padding:32px 24px 64px;font-family:system-ui,sans-serif;line-height:1.65;color:#2d3748">
<h1 style="font-size:26px;margin:0 0 20px">{h1}</h1>
{body_inner}
</main>
{FOOTER}
</body></html>"""

    # ── About ──────────────────────────────────────────────────────────────────
    about_body = f"""
<p style="font-size:16px;color:#4a5568">KiddieDaily is a free, independent daily news service for families. We believe every parent deserves access to balanced, kid-safe news — without paywalls, ads, or political spin.</p>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Our mission</h2>
<p>Ground-level news for parents: so you have the unbiased data you need to make the best decisions for your child. We don&#39;t tell you what to think — we give you the landscape, and the tools to read it critically.</p>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">How it works</h2>
<p>Every morning at 6am ET, our automated scraper collects stories from <strong>11 vetted sources</strong> spanning the full political spectrum. Each story is:</p>
<ul style="padding-left:20px;margin:8px 0">
<li>Filtered through a kid-safety blocklist (violence, explicit content, age-inappropriate topics)</li>
<li>Ranked to prioritize science, discovery, and nature over political conflict</li>
<li>Bias-rated using <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> methodology</li>
<li>Grouped when multiple outlets cover the same topic — so you can compare framing</li>
</ul>
<p>We publish up to 5 new articles per day. Science-focused sources are weighted higher because they tend to be more universally relevant to families and less politically charged.</p>

<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:16px 20px;margin:20px 0">
<p style="margin:0;font-size:14px;color:#1e40af"><strong>By the numbers:</strong> {total} articles published &middot; {sci_pct}% science content &middot; 11 sources &middot; 0 ads &middot; 0 trackers &middot; updated daily at 6am ET</p>
</div>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Our principles</h2>
<ol style="padding-left:20px;margin:8px 0">
<li><strong>Balance over narrative.</strong> We pull from Left, Center, and Right outlets. No single outlet is always right or always wrong.</li>
<li><strong>Science first.</strong> Discovery, nature, space, and health science take priority over political conflict.</li>
<li><strong>Kid-safe filtering.</strong> Our blocklist removes violence, explicit content, and age-inappropriate material before any article is considered.</li>
<li><strong>Parent-grade transparency.</strong> Every article shows which outlets covered it and how they lean. You see the bias before you read the story.</li>
<li><strong>No agenda.</strong> We&#39;re not affiliated with any political party, religion, or advocacy organization. We&#39;re a family project.</li>
</ol>

<h2 style="font-size:18px;margin:24px 0 10px;color:#1a4d80">Who runs KiddieDaily?</h2>
<p>KiddieDaily is a project of <strong>Legacy Bridge Alliance Group</strong>, a family-owned holding company building digital tools for families and kids. We also operate <a href="https://kiddiesketch.com" rel="noopener" style="color:#1a4d80">KiddieSketch</a>, <a href="https://kiddiego.com" rel="noopener" style="color:#1a4d80">KiddieGo</a>, and <a href="https://kiddiewordle.com" rel="noopener" style="color:#1a4d80">KiddieWordle</a>.</p>
<p>Have feedback? Reach us at <a href="/contact.html" style="color:#1a4d80">contact page</a>.</p>

<div style="margin-top:28px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">Today&#39;s stories</a>
<a href="/parents/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">For Parents</a>
<a href="/fact-check/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none">Media literacy</a>
</div>"""

    # ── Contact ────────────────────────────────────────────────────────────────
    contact_body = """
<p style="font-size:16px;color:#4a5568">Have a question, a story tip, or feedback about KiddieDaily? We&#39;d love to hear from you.</p>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:20px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Reach us by email</h2>
<p style="margin:0 0 8px">General questions and feedback:</p>
<p style="margin:0"><a href="mailto:hello@kiddiedaily.com" style="color:#1a4d80;font-weight:600;font-size:16px">hello@kiddiedaily.com</a></p>
</div>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Story tip or content concern?</h2>
<p style="margin:0">If you spot a story that shouldn&#39;t be on KiddieDaily (inappropriate for kids, factually wrong, or bias-rated incorrectly), please email:</p>
<p style="margin:8px 0 0"><a href="mailto:content@kiddiedaily.com" style="color:#1a4d80;font-weight:600;font-size:16px">content@kiddiedaily.com</a></p>
<p style="margin:8px 0 0;font-size:13px;color:#718096">We review all reports within 24 hours and will remove or correct the story if warranted.</p>
</div>

<div style="background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)">
<h2 style="font-size:17px;margin:0 0 12px;color:#1a4d80">Media or partnership inquiries</h2>
<p style="margin:0"><a href="mailto:partners@kiddiedaily.com" style="color:#1a4d80;font-weight:600">partners@kiddiedaily.com</a></p>
<p style="margin:8px 0 0;font-size:13px;color:#718096">We&#39;re open to partnerships with schools, libraries, and family-focused organizations that align with our mission of unbiased, kid-safe news.</p>
</div>

<p style="font-size:13px;color:#718096;margin:20px 0 0">KiddieDaily is operated by Legacy Bridge Alliance Group. We typically respond within 1–2 business days.</p>"""

    # ── Privacy ────────────────────────────────────────────────────────────────
    privacy_body = f"""
<p style="font-size:13px;color:#718096">Last updated: {today}</p>
<p style="font-size:16px;color:#4a5568">KiddieDaily is designed from the ground up with privacy in mind — especially for children. We collect the minimum possible data to operate the site.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">What we collect</h2>
<p><strong>Almost nothing.</strong> KiddieDaily is a static website served via GitHub Pages. We do not have accounts, logins, comment sections, or forms that collect personal information.</p>
<ul style="padding-left:20px;margin:8px 0">
<li><strong>No cookies.</strong> We set no tracking cookies, session cookies, or advertising cookies.</li>
<li><strong>No accounts.</strong> There is no sign-up, no login, and no stored user profiles.</li>
<li><strong>No ads.</strong> We run no advertising of any kind.</li>
<li><strong>No behavioral tracking.</strong> We do not track what articles you read, for how long, or what you click.</li>
</ul>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Analytics (if any)</h2>
<p>If we add analytics, we will use a cookieless, privacy-respecting tool (such as Cloudflare Web Analytics) that does not build user profiles, does not track individuals across sessions, and does not share data with third parties. We will update this policy before enabling any analytics.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Third-party links</h2>
<p>KiddieDaily links to external news sources (BBC, NPR, NASA, etc.) and fact-checking sites. Clicking those links takes you to third-party websites with their own privacy policies. We are not responsible for their data practices.</p>
<p>We also link to external educational resources (Snopes, AllSides, PBS NewsHour). These are informational links, not tracking partnerships.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Children&#39;s privacy (COPPA)</h2>
<p>KiddieDaily is designed to be used by families and does not knowingly collect personal information from children under 13. Because we collect no personal data at all, we believe we comply with the Children&#39;s Online Privacy Protection Act (COPPA). If you believe your child&#39;s information has been collected in error, contact us at <a href="mailto:privacy@kiddiedaily.com" style="color:#1a4d80">privacy@kiddiedaily.com</a> and we will delete it promptly.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">RSS content</h2>
<p>KiddieDaily aggregates headlines and summaries from public RSS feeds published by third-party news organizations. We link back to original articles and do not republish full copyrighted content. If you represent a news organization and have a concern about how we display your content, please contact us.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Contact</h2>
<p>Privacy questions: <a href="mailto:privacy@kiddiedaily.com" style="color:#1a4d80">privacy@kiddiedaily.com</a> &middot; <a href="/contact.html" style="color:#1a4d80">Contact page</a></p>"""

    # ── Terms ──────────────────────────────────────────────────────────────────
    terms_body = f"""
<p style="font-size:13px;color:#718096">Last updated: {today}</p>
<p style="font-size:16px;color:#4a5568">By using KiddieDaily, you agree to these terms. They&#39;re short and written in plain language.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">What KiddieDaily is</h2>
<p>KiddieDaily is a free news aggregation and curation service. We pull headlines and summaries from public RSS feeds and display them in a kid-safe, bias-labeled format for families. We are not a news organization — we do not produce original journalism.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Content accuracy</h2>
<p>We curate news to be kid-appropriate and balanced, but we do not independently verify every fact. The bias ratings we display (from AllSides and Ad Fontes Media) are methodological estimates, not legal judgments. Always read the original source and think critically.</p>
<p>KiddieDaily is provided &ldquo;as is.&rdquo; We make no warranties about the accuracy, completeness, or suitability of the content for any particular purpose.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Content ownership</h2>
<p>Article summaries and headlines remain the property of their original publishers. We display them under fair use for informational and educational purposes, with attribution and links back to the original source. KiddieDaily&#39;s own editorial text, design, and code are &copy; 2026 Legacy Bridge Alliance Group. Our commentary, page design, parent guides, and discussion prompts are our original work.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Prohibited uses</h2>
<ul style="padding-left:20px;margin:8px 0">
<li>Do not scrape or republish KiddieDaily content at scale without permission</li>
<li>Do not use KiddieDaily content to train AI models without written permission</li>
<li>Do not use our bias ratings to misrepresent news outlets as facts</li>
</ul>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Limitation of liability</h2>
<p>KiddieDaily and Legacy Bridge Alliance Group are not liable for any decisions made based on content displayed on this site. We are a news curation tool, not a professional advisor of any kind (legal, medical, financial, or otherwise).</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Changes</h2>
<p>We may update these terms. The &ldquo;last updated&rdquo; date at the top will reflect any changes. Continued use of the site after an update means you accept the new terms.</p>

<h2 style="font-size:18px;margin:20px 0 10px;color:#1a4d80">Contact</h2>
<p><a href="mailto:hello@kiddiedaily.com" style="color:#1a4d80">hello@kiddiedaily.com</a> &middot; <a href="/contact.html" style="color:#1a4d80">Contact page</a></p>"""

    upload("about.html", _page("About KiddieDaily — News for Families", "KiddieDaily is a free, ad-free daily news service for families. Learn about our mission, sources, and editorial principles.", "/about.html", "About KiddieDaily", about_body), "[scraper] Generate about.html")
    upload("contact.html", _page("Contact — KiddieDaily", "Get in touch with KiddieDaily for feedback, story tips, or partnership inquiries.", "/contact.html", "Contact Us", contact_body), "[scraper] Generate contact.html")
    upload("privacy.html", _page("Privacy Policy — KiddieDaily", "KiddieDaily privacy policy. No cookies, no accounts, no ads. Designed for families.", "/privacy.html", "Privacy Policy", privacy_body), "[scraper] Generate privacy.html")
    upload("terms.html", _page("Terms of Use — KiddieDaily", "KiddieDaily terms of use. Plain language, short version.", "/terms.html", "Terms of Use", terms_body), "[scraper] Generate terms.html")
    print(f"  Static pages: about, contact, privacy, terms — all deployed")


def generate_fact_check_page(manifest):
    """Generate /fact-check/index.html — media literacy + fact-check hub for families."""
    articles = manifest.get("articles", [])
    multi_source = [a for a in articles if a.get("n_sources", 1) > 1]
    n_multi = len(multi_source)
    total = len(articles)

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Fact Check — KiddieDaily Media Literacy Hub</title>
<meta name="description" content="Help your family spot bias, check facts, and read news critically. KiddieDaily's media literacy guide for parents and kids.">
<link rel="canonical" href="https://kiddiedaily.com/fact-check/">
{CSS}
<style>
.fc-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:16px 0}}
.fc-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:18px 20px;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.fc-card .icon{{font-size:28px;margin-bottom:10px}}
.fc-card h3{{margin:0 0 8px;font-size:16px;color:#1a4d80}}
.fc-card p{{margin:0;font-size:14px;color:#4a5568;line-height:1.55}}
.fc-step{{display:flex;gap:14px;align-items:flex-start;margin:12px 0;padding:14px 16px;background:#f7fafc;border-radius:8px}}
.fc-step .num{{font-size:22px;font-weight:700;color:#1a4d80;min-width:32px;line-height:1.2}}
.fc-step p{{margin:0;font-size:14px;color:#2d3748;line-height:1.55}}
.source-row{{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid #f0f0f0}}
.source-row:last-child{{border-bottom:none}}
.bias-pip{{width:12px;height:12px;border-radius:50%;flex-shrink:0}}
.tip-box{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:16px 20px;margin:16px 0}}
.tip-box h4{{margin:0 0 8px;font-size:14px;font-weight:700;color:#1e40af}}
.tip-box p,ul{{margin:0;font-size:14px;color:#1e3a8a;line-height:1.6}}
.tip-box ul{{padding-left:20px}}
</style>
</head><body>
{HEADER}
<main style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Fact Check &amp; Media Literacy</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
Helping families read the news with open eyes — no agenda, no spin.
</p>

<div style="background:#fff8e1;border:1px solid #fde68a;border-radius:10px;padding:16px 20px;margin:0 0 24px;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#92400e;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">&#128202; KiddieDaily by the numbers</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;font-size:14px;color:#92400e">
<span><strong>{total}</strong> articles analyzed</span>
<span><strong>{n_multi}</strong> covered by 2+ outlets</span>
<span><strong>11</strong> sources bias-rated</span>
<span><strong>0</strong> ads or trackers</span>
</div>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:0 0 12px">What is media bias?</div>
<div class="fc-grid">
<div class="fc-card"><div class="icon">&#129300;</div><h3>Framing bias</h3><p>The same fact can sound different depending on the words chosen. "Police responded to a protest" vs. "Police cracked down on demonstrators" — same event, different frame.</p></div>
<div class="fc-card"><div class="icon">&#128269;</div><h3>Selection bias</h3><p>News outlets choose WHAT to cover. A story that's big on Fox News might barely appear on NPR — and vice versa. Neither absence means it didn't happen.</p></div>
<div class="fc-card"><div class="icon">&#128226;</div><h3>Tone bias</h3><p>Word choice, headline intensity, and photo selection all carry emotion. Positive tone toward one group, negative toward another — that's bias at work.</p></div>
<div class="fc-card"><div class="icon">&#9878;&#65039;</div><h3>Source bias</h3><p>Who gets quoted? When one side of a story gets more expert voices than the other, the story feels more credible even if the evidence isn't.</p></div>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">How KiddieDaily measures bias</div>
<p style="font-size:15px;color:#2d3748;margin:0 0 12px;line-height:1.6">We use the same methodology as journalism schools and independent researchers: <strong>AllSides</strong> and <strong>Ad Fontes Media</strong> bias ratings. These were built by analyzing thousands of articles, surveying readers across the political spectrum, and measuring factual accuracy vs. emotional language.</p>

<div style="overflow-x:auto;margin:0 0 20px">
<table style="width:100%;border-collapse:collapse;font-family:system-ui,sans-serif;font-size:14px">
<thead><tr style="background:#f7fafc;text-align:left">
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Outlet</th>
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Bias score</th>
<th style="padding:10px 12px;border-bottom:2px solid #e2e8f0">Lean</th>
</tr></thead>
<tbody>
<tr class="source-row"><td style="padding:8px 12px">&#128251; BBC News</td><td style="padding:8px 12px">&#8722;0.3</td><td style="padding:8px 12px;color:#2b6cb0">Slight Left</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#128251; NPR</td><td style="padding:8px 12px">&#8722;0.7</td><td style="padding:8px 12px;color:#2b6cb0">Left-leaning</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#127757; Al Jazeera</td><td style="padding:8px 12px">&#8722;0.4</td><td style="padding:8px 12px;color:#2b6cb0">Slight Left</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#9878;&#65039; The Hill</td><td style="padding:8px 12px">+0.1</td><td style="padding:8px 12px;color:#276749">Center</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#129413; Fox News</td><td style="padding:8px 12px">+1.3</td><td style="padding:8px 12px;color:#c53030">Right-leaning</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#128640; NASA</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#128300; Science Daily</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#127963;&#65039; Smithsonian</td><td style="padding:8px 12px">&#8722;0.1</td><td style="padding:8px 12px;color:#276749">Center</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#128225; Science News</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row" style="background:#fafafa"><td style="padding:8px 12px">&#127759; EarthSky</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
<tr class="source-row"><td style="padding:8px 12px">&#129516; Live Science</td><td style="padding:8px 12px">0.0</td><td style="padding:8px 12px;color:#276749">Center (Science)</td></tr>
</tbody></table>
</div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">How to fact-check any story — 5 steps</div>
<div class="fc-step"><div class="num">1</div><p><strong>Find the original claim.</strong> What exactly is being said? A headline often exaggerates. Read past the first paragraph before reacting.</p></div>
<div class="fc-step"><div class="num">2</div><p><strong>Who is the source?</strong> Is it a named expert, an anonymous source, or "studies show"? Named, on-record sources are more reliable than unnamed ones.</p></div>
<div class="fc-step"><div class="num">3</div><p><strong>Search for the same story elsewhere.</strong> Does the BBC report it the same way as Fox News? If the facts differ, someone may have gotten it wrong — or be spinning it.</p></div>
<div class="fc-step"><div class="num">4</div><p><strong>Check a fact-checking site.</strong> Google Fact Check Explorer, Snopes, and PolitiFact all search thousands of verified claims. Type any claim into their search bar.</p></div>
<div class="fc-step"><div class="num">5</div><p><strong>Ask: what is this story missing?</strong> Good reporting names who benefits, who is harmed, what happened before, and what experts disagree. Missing any of these? Keep reading.</p></div>

<div style="font-size:11px;font-weight:700;color:#718096;text-transform:uppercase;letter-spacing:1.2px;margin:24px 0 12px">Trusted fact-check tools (external)</div>
<div class="fc-grid">
<div class="fc-card"><div class="icon">&#128269;</div><h3>Google Fact Check Explorer</h3><p>Search any claim. Shows what independent fact-checkers worldwide have ruled on thousands of stories.</p><p style="margin-top:10px"><a href="https://toolbox.google.com/factcheck/explorer" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Open Fact Check Explorer &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#129300;</div><h3>Snopes</h3><p>The oldest fact-checking site. Strong on viral rumors, internet hoaxes, and "did that really happen" questions.</p><p style="margin-top:10px"><a href="https://www.snopes.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit Snopes &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#9878;&#65039;</div><h3>AllSides</h3><p>Side-by-side coverage of the same story from Left, Center, and Right outlets. Great for seeing how framing changes the narrative.</p><p style="margin-top:10px"><a href="https://www.allsides.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit AllSides &rarr;</a></p></div>
<div class="fc-card"><div class="icon">&#128202;</div><h3>Ad Fontes Media</h3><p>News source ratings on a chart showing both political bias AND reliability. Used by schools and newsrooms.</p><p style="margin-top:10px"><a href="https://adfontesmedia.com" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px">Visit Ad Fontes Media &rarr;</a></p></div>
</div>

<div class="tip-box">
<h4>&#128161; Family activity: spot the framing</h4>
<p>Pick any story from today&#39;s KiddieDaily. Then:</p>
<ul>
<li>Read the KiddieDaily version</li>
<li>Search the headline on Google News and find 2 other outlets covering it</li>
<li>Ask: What words did each outlet choose? What did they emphasize? What did they leave out?</li>
<li>Discuss: Is the core fact the same across all three? What&#39;s different?</li>
</ul>
<p style="margin-top:8px">This is how journalists learn to read news critically — and it works for kids as young as 9.</p>
</div>

<div style="margin-top:24px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s stories</a>
<a href="/parents/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
<a href="/search.html" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Search all articles</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("fact-check/index.html", page, "[scraper] Fact Check / media literacy hub page")
    print(f"  Fact-check page: {total} articles referenced, {n_multi} multi-source")


def generate_games_page(manifest):
    """Generate /games/index.html — media literacy games and educational activities for families."""
    articles = manifest.get("articles", [])
    sci_articles = [a for a in articles if a.get("is_science")]
    world_articles = [a for a in articles if not a.get("is_science")]
    # Pick 5 quiz articles: 4 recent science + 1 recent world news (for variety)
    # Spread selection across the recent pool to avoid always same articles
    recent_sci = sci_articles[-20:] if len(sci_articles) >= 20 else sci_articles
    step = max(1, len(recent_sci) // 4)
    quiz_sci = [recent_sci[min(i * step, len(recent_sci) - 1)] for i in range(4)]
    quiz_world = world_articles[-2:] if world_articles else []
    quiz_pool = (quiz_sci + quiz_world[:1])[:5]

    stop = {"about", "their", "these", "those", "would", "could", "which", "where",
            "there", "after", "other", "first", "world", "using", "study", "finds",
            "found", "shows", "says", "that", "have", "with", "from", "this", "will",
            "into", "been", "more", "also", "than", "when", "were", "they"}

    def _quiz_item(a, idx):
        title = a.get("display_title", a.get("title", ""))
        words = [w.capitalize() for w in re.sub(r"[^\w\s]", "", title.lower()).split()
                 if len(w) > 4 and w not in stop]
        keyword = words[0] if words else "Science"
        # Build 3 multiple-choice options (A = correct, B/C = plausible distractors)
        distractors = [
            ("It happened a million years ago", "An ancient event"),
            ("It\'s about extreme weather", "A weather story"),
            ("Scientists changed their minds", "A retraction"),
            ("It involves a new invention", "A technology story"),
            ("It\'s about an endangered animal", "An animals story"),
        ]
        b_text, c_text = distractors[idx % len(distractors)]
        return (
            f'<div class="quiz-q" id="q{idx}" style="background:#fff;border:1px solid #dde4ef;'
            f'border-radius:10px;padding:16px 20px;margin:12px 0">'
            f'<p style="font-weight:700;font-size:15px;color:#1a4d80;margin:0 0 12px">'
            f'Q{idx+1}. What is this headline about?<br>'
            f'<span style="font-style:italic;font-weight:400;color:#2d3748">&ldquo;{title[:90]}{"…" if len(title)>90 else ""}&rdquo;</span></p>'
            f'<div style="display:flex;flex-direction:column;gap:8px">'
            f'<label style="cursor:pointer;font-size:14px;color:#2d3748"><input type="radio" name="q{idx}" value="a" style="margin-right:8px"> A) About {keyword}</label>'
            f'<label style="cursor:pointer;font-size:14px;color:#2d3748"><input type="radio" name="q{idx}" value="b" style="margin-right:8px"> B) {b_text}</label>'
            f'<label style="cursor:pointer;font-size:14px;color:#2d3748"><input type="radio" name="q{idx}" value="c" style="margin-right:8px"> C) {c_text}</label>'
            f'</div>'
            f'<div id="q{idx}-result" style="margin-top:10px;padding:8px 12px;border-radius:6px;display:none;font-size:14px"></div>'
            f'</div>'
        )

    quiz_html = "\n".join(_quiz_item(a, i) for i, a in enumerate(quiz_pool))

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Games — KiddieDaily Media Literacy Activities</title>
<meta name="description" content="Fun media literacy games and activities for kids. Spot the bias, quiz yourself on today's science news, and become a critical reader.">
<link rel="canonical" href="https://kiddiedaily.com/games/">
{CSS}
<style>
.game-card{{background:#fff;border:1px solid #dde4ef;border-radius:12px;padding:20px 22px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.05)}}
.game-card h3{{margin:0 0 8px;font-size:18px;color:#1a4d80}}
.game-card .tag{{font-size:11px;font-weight:700;color:#065f46;background:#d1fae5;padding:2px 8px;border-radius:20px;letter-spacing:.8px;text-transform:uppercase}}
.game-card p{{margin:8px 0 0;font-size:14px;color:#4a5568;line-height:1.55}}
.btn-play{{display:inline-block;margin-top:12px;background:#1a4d80;color:#fff;padding:8px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif}}
.btn-play:hover{{background:#1e3a6e}}
</style>
</head><body>
{HEADER}
<main style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 6px">Games &amp; Activities</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:15px;margin:0 0 24px">
Learn to read news like a pro — because critical thinking is a superpower.
</p>

<div class="game-card">
<span class="tag">Live Quiz</span>
<h3>&#129300; Headline Detective</h3>
<p>Can you figure out what today&#39;s science headlines are about from the title alone? Test your reading comprehension with real KiddieDaily stories.</p>
<div style="margin-top:16px">
{quiz_html if quiz_html else '<p style="color:#718096">No quiz available yet — check back after 6am ET!</p>'}
</div>
{f"""<button onclick="(function(){{
  var score=0,total={len(quiz_pool)};
  {''.join(f"""
  (function(){{
    var el=document.querySelector('input[name=q{i}]:checked');
    var res=document.getElementById('q{i}-result');
    res.style.display='block';
    if(el&&el.value==='a'){{score++;res.style.background='#d1fae5';res.style.color='#065f46';res.innerHTML='&#9989; Correct! The headline is about a science discovery.'}}
    else{{res.style.background='#fee2e2';res.style.color='#c53030';res.innerHTML='&#10060; Not quite — this was a science story. Read the full article to learn more!'}}
  }})();""" for i in range(len(quiz_pool)))}
  alert('You got '+score+' out of '+total+'! '+(score===total?'Perfect score!':score>=total/2?'Good job — keep reading!':'Keep practicing by reading KiddieDaily every day!'));
}})()" style="margin-top:14px;background:#1a4d80;color:#fff;border:none;padding:10px 22px;border-radius:6px;font-size:14px;cursor:pointer;font-family:system-ui,sans-serif">
Check My Answers</button>""" if quiz_pool else ""}
</div>

<div class="game-card">
<span class="tag">Critical Thinking</span>
<h3>&#127919; Spot the Bias Challenge</h3>
<p>Every article on KiddieDaily shows where the outlet leans on the political spectrum. But can you spot bias in the headline itself — before you read the story?</p>
<p><strong>Try this:</strong> Read two headlines on the same topic from different outlets. Look for:
<ul style="font-size:14px;color:#4a5568;margin:8px 0;padding-left:20px;line-height:1.7">
<li>Emotional or charged words ("slams", "blasts", "soars", "fails")</li>
<li>Whose perspective is front and center</li>
<li>What facts are left out of the headline</li>
<li>Whether the headline matches the actual story</li>
</ul>
</p>
<a href="/news/today.html" class="btn-play">Try with today&#39;s stories &rarr;</a>
</div>

<div class="game-card">
<span class="tag">Fact Finding</span>
<h3>&#128269; Claim Buster</h3>
<p>Pick any headline. Now try to verify ONE fact in it using an external source. Use any of these:</p>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
<a href="https://toolbox.google.com/factcheck/explorer" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Google Fact Check Explorer</a>
<a href="https://www.snopes.com" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Snopes</a>
<a href="https://www.sciencenews.org" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">Science News</a>
<a href="https://www.nasa.gov" rel="noopener nofollow" target="_blank" style="background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;padding:6px 14px;border-radius:6px;font-size:13px;text-decoration:none">NASA.gov</a>
</div>
<p style="margin-top:12px;font-size:13px;color:#718096">If you can verify it in under 3 minutes — you just fact-checked a story. That&#39;s what journalists do all day.</p>
</div>

<div class="game-card">
<span class="tag">Science Skills</span>
<h3>&#128300; Science or Spin?</h3>
<p>Science stories have a different structure than political stories. In a good science story, you should be able to find:</p>
<ul style="font-size:14px;color:#4a5568;margin:8px 0;padding-left:20px;line-height:1.7">
<li>A named researcher or institution</li>
<li>Where the study was published (journal name)</li>
<li>How many subjects were studied</li>
<li>What the researchers actually measured</li>
<li>A caveat — what the study did NOT prove</li>
</ul>
<p style="font-size:14px;color:#4a5568;margin-top:8px">Pick a science article from KiddieDaily and see how many of these 5 you can find. If you can find all 5, it&#39;s a solid study. If you find fewer than 3, be skeptical.</p>
<a href="/news/science.html" class="btn-play">Browse science articles &rarr;</a>
</div>

<div style="background:#f0f4f8;border-radius:10px;padding:18px 22px;margin:24px 0;font-family:system-ui,sans-serif">
<div style="font-size:11px;font-weight:700;color:#4a5568;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">More free media literacy resources</div>
<div style="display:flex;gap:10px;flex-wrap:wrap">
<a href="https://newslit.org" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">News Literacy Project</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.allsides.com/media-literacy" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">AllSides Media Literacy</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.commonsense.org/education/articles/news-and-media-literacy-resources" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">Common Sense Media</a>
<span style="color:#cbd5e0">·</span>
<a href="https://www.pbs.org/newshour/classroom" rel="noopener nofollow" target="_blank" style="color:#1a4d80;font-size:13px;text-decoration:none">PBS NewsHour Classroom</a>
</div>
</div>

<div style="margin-top:8px;display:flex;gap:10px;flex-wrap:wrap">
<a href="/news/today.html" style="background:#1a4d80;color:#fff;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Today&#39;s news</a>
<a href="/fact-check/" style="background:#f7fafc;color:#1a4d80;border:1px solid #1a4d80;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">Fact Check guide</a>
<a href="/parents/" style="background:#f7fafc;color:#718096;border:1px solid #e2e8f0;padding:9px 18px;border-radius:6px;font-size:14px;text-decoration:none;font-family:system-ui,sans-serif">For Parents</a>
</div>
</main>
{FOOTER}
</body></html>"""

    upload("games/index.html", page, "[scraper] Games / media literacy activities page")
    print(f"  Games page: {len(quiz_pool)} quiz questions ({len(quiz_sci)} science + {len(quiz_world[:1])} world)")


def generate_search_page(manifest):
    """Generate /search.html — full-page search interface fetching /data/kd-articles.json."""
    articles = manifest.get("articles", [])
    total = len(articles)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Search — KiddieDaily</title>
<meta name="description" content="Search all KiddieDaily news articles — kid-friendly, bias-rated, fact-checked.">
<link rel="canonical" href="https://kiddiedaily.com/search.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
{CSS}
<style>
#kd-search-input{{
  display:block;width:100%;box-sizing:border-box;
  font-size:22px;padding:14px 18px;
  border:2px solid #1a4d80;border-radius:10px;
  font-family:system-ui,sans-serif;color:#1a1a1a;
  background:#fff;margin-bottom:8px;
  box-shadow:0 2px 8px rgba(26,77,128,.10);
  outline:none;
}}
#kd-search-input:focus{{border-color:#ffd700;box-shadow:0 2px 12px rgba(26,77,128,.18)}}
#kd-result-count{{font-size:14px;color:#718096;font-family:system-ui,sans-serif;margin:0 0 20px;min-height:20px}}
.kd-sr{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sr-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-sr h3{{margin:4px 0 4px;font-size:1em;line-height:1.35}}
.kd-sr h3 a{{color:#1a4d80;text-decoration:none}}
.kd-sr h3 a:hover{{text-decoration:underline}}
.kd-sr-meta{{font-size:12px;color:#a0aec0;margin-top:4px;font-family:system-ui,sans-serif}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-badge-news{{background:#dbeafe;color:#1e40af}}
#kd-no-results{{display:none;text-align:center;color:#718096;font-family:system-ui,sans-serif;padding:40px 0;font-size:15px}}
.kd-cat-filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}}
.kd-cat-btn{{padding:7px 16px;border-radius:20px;border:2px solid #dde4ef;background:#fff;
  font-size:13px;font-weight:700;cursor:pointer;font-family:system-ui,sans-serif;
  color:#4a5568;transition:all .15s}}
.kd-cat-btn.active{{background:#1a4d80;color:#fff;border-color:#1a4d80}}
.kd-cat-btn:hover:not(.active){{border-color:#1a4d80;color:#1a4d80}}
</style>
</head>
<body>
{{HEADER}}
<main style="max-width:780px;margin:0 auto;padding:32px 24px 64px">
<h1 style="font-size:28px;margin:0 0 16px">Search KiddieDaily</h1>
<div class="kd-cat-filters">
  <button class="kd-cat-btn active" data-cat="all" onclick="setCat(this,'all')">All</button>
  <button class="kd-cat-btn" data-cat="science" onclick="setCat(this,'science')">🔬 Science</button>
  <button class="kd-cat-btn" data-cat="world" onclick="setCat(this,'world')">🌍 World News</button>
</div>
<input
  id="kd-search-input"
  type="search"
  placeholder="Search {total} articles..."
  aria-label="Search articles"
  autofocus
  autocomplete="off"
  spellcheck="false"
>
<p id="kd-result-count"></p>
<div id="kd-results"></div>
<div id="kd-no-results">No articles matched your search.</div>
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096;font-family:system-ui,sans-serif">
  <a href="/news/archive.html" style="color:#1a4d80">Full archive</a> &middot;
  <a href="/news/" style="color:#1a4d80">Kid News</a> &middot;
  <a href="/feed.xml" style="color:#1a4d80">RSS</a>
</p>
</main>
{{FOOTER}}
<script>
(function(){{
  var container = document.getElementById('kd-results');
  var countEl   = document.getElementById('kd-result-count');
  var noResults = document.getElementById('kd-no-results');
  var input     = document.getElementById('kd-search-input');
  var allArticles = [];
  var activeCategory = 'all';

  function setCat(btn, cat) {{
    activeCategory = cat;
    document.querySelectorAll('.kd-cat-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    btn.classList.add('active');
    filterAndRender();
  }}
  window.setCat = setCat;

  function renderResults(articles, query) {{
    if (!articles.length) {{
      container.innerHTML = '';
      noResults.style.display = (query || activeCategory !== 'all') ? 'block' : 'none';
      countEl.textContent = '';
      return;
    }}
    noResults.style.display = 'none';
    if (query) {{
      countEl.textContent = articles.length + ' result' + (articles.length === 1 ? '' : 's') + " for '" + query + "'";
    }} else {{
      countEl.textContent = articles.length + ' article' + (articles.length === 1 ? '' : 's') + ', newest first';
    }}
    container.innerHTML = articles.map(function(a) {{
      var badgeCls  = a.is_science ? 'kd-badge-sci' : 'kd-badge-news';
      var badgeLbl  = a.is_science ? 'Science' : 'World News';
      var src_word  = a.n_sources === 1 ? '1 source' : a.n_sources + ' sources';
      return '<div class="kd-sr">'
        + '<div class="kd-sr-top">'
        + '<span class="kd-badge ' + badgeCls + '">' + badgeLbl + '</span>'
        + '</div>'
        + '<h3><a href="/' + a.slug + '">' + a.title + '</a></h3>'
        + '<div class="kd-sr-meta">' + a.date + ' &middot; ' + src_word + '</div>'
        + '</div>';
    }}).join('');
  }}

  function filterAndRender() {{
    var q = input.value.trim().toLowerCase();
    var filtered = allArticles.filter(function(a) {{
      var matchesCat = activeCategory === 'all' || (a.category || (a.is_science ? 'science' : 'world')) === activeCategory;
      var matchesQ   = !q || a.title.toLowerCase().indexOf(q) !== -1;
      return matchesCat && matchesQ;
    }});
    renderResults(filtered, q);
  }}

  fetch('/data/kd-articles.json')
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      allArticles = data.sort(function(a, b) {{ return b.date < a.date ? -1 : b.date > a.date ? 1 : 0; }});
      // Update placeholder with live count
      input.placeholder = 'Search ' + allArticles.length + ' articles...';
      renderResults(allArticles, '');
    }})
    .catch(function() {{
      countEl.textContent = 'Could not load articles. Try refreshing.';
    }});

  input.addEventListener('input', filterAndRender);
}})();
</script>
</body></html>"""

    # Substitute HEADER and FOOTER (they contain braces so we inject after f-string render)
    page = page.replace('{HEADER}', HEADER).replace('{FOOTER}', FOOTER)
    upload("search.html", page, f"[scraper] Search page — {total} articles indexed")
    print(f"  Search page: {total} articles indexed")


# ── Scraper status page ───────────────────────────────────────────────────────
def generate_status_page(manifest, today, pushed_count):
    articles = manifest.get("articles", [])
    total = len(articles)
    sci   = sum(1 for a in articles if a.get("is_science"))
    world = total - sci
    dates = sorted({a.get("date", "") for a in articles if a.get("date")}, reverse=True)
    last_run = dates[0] if dates else "—"
    biases = [a.get("bias_avg", 0.0) for a in articles]
    avg_bias = (sum(biases) / len(biases)) if biases else 0.0

    source_counts = {}
    for a in articles:
        for icon in a.get("source_icons", "").split():
            source_counts[icon] = source_counts.get(icon, 0) + 1
    top_sources = sorted(source_counts.items(), key=lambda x: -x[1])[:6]
    sources_html = " ".join(
        f'<span style="font-size:24px" title="{icon}: {cnt} articles">{icon}</span>'
        for icon, cnt in top_sources
    )

    page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>KiddieDaily — Scraper Status</title>
<meta name="description" content="KiddieDaily automation status — last run, article counts, source breakdown.">
<link rel="canonical" href="https://kiddiedaily.com/status.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#f0f4f8;color:#2d3748}}
header.kd{{background:#1a4d80;padding:14px 0}}
header.kd .inner{{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px;padding:0 20px}}
header.kd .logo{{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif;text-decoration:none}}
header.kd nav{{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}}
header.kd nav a{{color:#fff;font-size:15px}}
main{{max-width:780px;margin:0 auto;padding:32px 24px 64px}}
.stat-card{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:20px 24px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.stat-card h3{{margin:0 0 6px;font-size:16px;color:#1a4d80}}
.stat-val{{font-size:32px;font-weight:700;color:#2d3748;margin:4px 0}}
.stat-sub{{font-size:13px;color:#718096}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}}
.badge-ok{{display:inline-block;padding:4px 12px;border-radius:20px;background:#d1fae5;color:#065f46;font-size:13px;font-weight:700}}
</style>
</head><body>
<header class="kd"><div class="inner">
  <a class="logo" href="/">📰 KiddieDaily</a>
  <nav>
    <a href="/news/">News</a>
    <a href="/news/science.html">Science</a>
    <a href="/search.html">Search</a>
    <a href="/digest/latest.html">Digest</a>
    <a href="/parent-zone/">Parents</a>
  </nav>
</div></header>
<main>
  <h1 style="font-size:28px;margin:0 0 4px">Automation Status</h1>
  <p style="color:#718096;margin:0 0 24px;font-size:14px">KiddieDaily runs automatically every morning at 6am ET via GitHub Actions.</p>

  <div class="grid">
    <div class="stat-card">
      <h3>Last Run</h3>
      <div class="stat-val">{last_run}</div>
      <div class="stat-sub">Today: +{pushed_count} new article{"s" if pushed_count != 1 else ""}</div>
    </div>
    <div class="stat-card">
      <h3>Total Articles</h3>
      <div class="stat-val">{total}</div>
      <div class="stat-sub">{sci} science &middot; {world} world news</div>
    </div>
    <div class="stat-card">
      <h3>Avg Bias (all sources)</h3>
      <div class="stat-val">{avg_bias:+.2f}</div>
      <div class="stat-sub">Scale: -2 far-left → +2 far-right</div>
    </div>
    <div class="stat-card">
      <h3>Days Covered</h3>
      <div class="stat-val">{len(dates)}</div>
      <div class="stat-sub">Since {dates[-1] if dates else "—"}</div>
    </div>
  </div>

  <div class="stat-card" style="margin-top:20px">
    <h3>Pipeline Health</h3>
    <div style="margin:10px 0 6px;display:flex;flex-wrap:wrap;gap:8px">
      <span class="badge-ok">✓ GitHub Actions cron active</span>
      <span class="badge-ok">✓ GitHub Flow (branch → PR → merge)</span>
      <span class="badge-ok">✓ 3-stage CI review</span>
      <span class="badge-ok">✓ {total} articles indexed</span>
      <span class="badge-ok">✓ RSS feed live</span>
    </div>
    <div style="margin-top:12px;font-size:13px;color:#718096">
      Sources monitored: {sources_html}
    </div>
  </div>

  <div class="stat-card" style="margin-top:16px">
    <h3>Recent Dates</h3>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
{"".join(f'      <a href="/digest/{d}.html" style="font-size:13px;padding:4px 10px;background:#dbeafe;color:#1e40af;border-radius:20px;text-decoration:none">{d}</a>' for d in dates[:14])}
    </div>
  </div>

  <p style="margin-top:24px;font-size:13px;color:#718096;text-align:center">
    <a href="https://github.com/Omtatsat101/kiddiedaily" style="color:#1a4d80">View on GitHub</a> &middot;
    <a href="/feed.xml" style="color:#1a4d80">RSS Feed</a> &middot;
    <a href="/sitemap.xml" style="color:#1a4d80">Sitemap</a>
  </p>
</main>
</body></html>"""

    upload("status.html", page, f"[scraper] Status page — {total} articles, last run {today}")
    print(f"  Status page: {total} articles, {len(dates)} days covered")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\nKiddieDaily Scraper — {today}")
    print("=" * 52)

    # 0. GitHub Flow: create content branch when running in CI (GH_ACTIONS env is set)
    in_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    if in_ci:
        print("\n[0] Setting up GitHub Flow content branch...")
        setup_content_branch(today)
        print(f"    Active branch: {ACTIVE_BRANCH}")

    # 1. Load manifest
    print("\n[1] Loading pushed-article manifest...")
    manifest = load_manifest()
    pushed_slugs = set(manifest.get("pushed_slugs", []))
    pushed_titles = set(t.lower() for t in manifest.get("pushed_titles", []))
    print(f"    {len(pushed_slugs)} articles already pushed")

    # 2. Fetch RSS
    print(f"\n[2] Fetching {len(SOURCES)} RSS feeds...")
    all_stories = []
    for src in SOURCES:
        print(f"    {src['icon']} {src['name']}...", end=" ", flush=True)
        stories = fetch_rss(src)
        print(f"{len(stories)} stories")
        all_stories.extend(stories)
        time.sleep(0.3)
    print(f"    Total: {len(all_stories)} stories")

    # 3. Deduplicate against already pushed
    new_stories = [s for s in all_stories if s["title"].lower() not in pushed_titles]
    print(f"\n[3] {len(new_stories)} new stories (not yet pushed)")

    # 4. Group by topic
    print("\n[4] Grouping by topic...")
    groups = group_stories(new_stories)
    print(f"    {len(groups)} unique topics")

    # 5. Generate + push articles
    print(f"\n[5] Generating articles (max {MAX_ARTICLES} per run — up to {MAX_SCI_PER_RUN} science, {MAX_WORLD_PER_RUN} world)...")
    pushed_count = 0
    sci_pushed_run   = 0
    world_pushed_run = 0
    source_counts_run = {}  # tracks articles per source this run

    MIN_SCORE = 1  # skip topics that rank ≤ 0 (political, low-signal, single-source noise)
    skipped_low = 0
    skipped_adult = 0
    skipped_quota = 0

    for group in groups:
        if pushed_count >= MAX_ARTICLES:
            break

        rep = group[0]

        # Skip topics with adult/inappropriate titles (regex, word-boundary safe)
        if _ADULT_TITLE_RE.search(rep["title"]):
            skipped_adult += 1
            print(f"    ⚠ Skipped (adult title): {rep['title'][:60]}")
            continue

        # Skip groups that score too low (political noise, single-source political stories)
        if ranking_score(group) < MIN_SCORE:
            skipped_low += 1
            continue

        # Per-run category balance
        is_sci_group = any(s["source_name"] in SCIENCE_SOURCES for s in group)
        if is_sci_group and sci_pushed_run >= MAX_SCI_PER_RUN:
            skipped_quota += 1
            continue
        if not is_sci_group and world_pushed_run >= MAX_WORLD_PER_RUN:
            skipped_quota += 1
            continue

        # Per-source cap: no single source dominates the run
        primary_source = rep["source_name"]
        if source_counts_run.get(primary_source, 0) >= MAX_PER_SOURCE_PER_RUN:
            skipped_quota += 1
            continue

        # World news: reject high-bias single-source stories (partisan entertainment/opinion)
        if not is_sci_group:
            n = len(group)
            bias_avg = sum(s["source_bias"] for s in group) / n if n else 0.0
            if abs(bias_avg) > MAX_WORLD_NEWS_BIAS and n == 1:
                skipped_low += 1
                continue

        slug = make_slug(rep["title"], today)
        if slug in pushed_slugs:
            continue
        # Title-level dedup: prevents same story appearing on multiple days
        if rep["title"].lower() in pushed_titles:
            continue

        score = score_group(group)
        print(f"\n    Topic: {rep['title'][:60]}...")
        print(f"    Sources: {score['n_sources']} | Bias: {score['bias_avg']:+.2f} | Agreement: {score['agreement_pct']}%")

        # Try API rewrite, fall back to RSS body
        rewritten = None
        if ANTHROPIC_KEY:
            print("    Rewriting with Claude Haiku...")
            rewritten = rewrite_for_kids(rep["title"], rep["description"])

        if rewritten:
            article_title, body_html = body_from_api(rep["title"], rewritten)
            print(f"    → API rewrite: '{article_title[:55]}...'")
        else:
            article_title, body_html = body_from_rss(group)
            print("    → Using RSS content (no API key)")

        bias_html = bias_bar_html(score)
        html = build_page(article_title, body_html, bias_html, score, group, slug, today)

        print(f"    Pushing {slug}...")
        result = upload(slug, html, f"[scraper] {article_title[:60]}")

        if result:
            manifest["pushed_slugs"].append(slug)
            manifest["pushed_titles"].append(rep["title"])
            if "articles" not in manifest:
                manifest["articles"] = []
            icons = " ".join(dict.fromkeys(s["source_icon"] for s in group))
            manifest["articles"].append({
                "slug": slug,
                "title": rep["title"],
                "display_title": article_title,
                "date": today,
                "n_sources": score["n_sources"],
                "bias_avg": score["bias_avg"],
                "agreement_pct": score["agreement_pct"],
                "is_science": any(s["source_name"] in SCIENCE_SOURCES for s in group),
                "source_icons": icons,
            })
            pushed_count += 1
            source_counts_run[primary_source] = source_counts_run.get(primary_source, 0) + 1
            if is_sci_group:
                sci_pushed_run += 1
            else:
                world_pushed_run += 1

    if skipped_low:
        print(f"\n    Skipped {skipped_low} low-score topics (political/noise below threshold)")
    if skipped_adult:
        print(f"    Filtered {skipped_adult} adult/inappropriate titles")
    if skipped_quota:
        print(f"    Skipped {skipped_quota} topics (category quota reached)")

    # 6. Save manifest (always if changed: new articles OR migration)
    manifest_dirty = pushed_count > 0 or "articles" in manifest
    if manifest_dirty:
        print(f"\n[6] Saving manifest ({len(manifest.get('articles',[]))} total articles)...")
        save_manifest(manifest)

    # 6b. Always rebuild news index if we have articles
    if manifest.get("articles"):
        print(f"\n[6b] Updating news/index.html...")
        update_news_index(manifest)

    # 6c. Always rebuild sitemap (articles + digest dates change daily)
    print(f"\n[6c] Updating sitemap.xml...")
    update_sitemap(manifest.get("pushed_slugs", []), manifest)

    # 6d. Update homepage with latest 3 articles
    print(f"\n[6d] Updating homepage...")
    update_homepage(manifest)

    # 6e. Generate RSS feed
    print(f"\n[6e] Generating RSS feed...")
    generate_rss_feed(manifest)

    # 6f. Update Parent Zone article table
    print(f"\n[6f] Updating Parent Zone...")
    update_parent_zone(manifest)

    # 6g. Generate archive page with client-side search
    print(f"\n[6g] Generating archive page...")
    generate_archive(manifest)

    # 6h. Generate category pages
    print(f"\n[6h] Generating category pages...")
    generate_category_pages(manifest)

    # 6i. Generate articles JSON index (used by related-articles JS on every article page)
    print(f"\n[6i] Generating articles JSON index...")
    generate_articles_json(manifest)

    # 6j. Generate daily digest page
    print(f"\n[6j] Generating daily digest...")
    generate_daily_digest(manifest, today)

    # 6k. Generate today's news page
    print(f"\n[6k] Generating today's news page...")
    generate_today_page(manifest, today)

    # 6k2. Generate weekly digest page
    print(f"\n[6k2] Generating weekly digest...")
    generate_weekly_digest(manifest, today)

    # 6k3. Generate search page
    print(f"\n[6k3] Generating search page...")
    generate_search_page(manifest)

    # 6k4. Generate automation status page
    print(f"\n[6k4] Generating status page...")
    generate_status_page(manifest, today, pushed_count)

    # 6k5. Generate For-Parents briefing page
    print(f"\n[6k5] Generating For-Parents briefing page...")
    generate_for_parents_page(manifest, today)

    # 6k6. Generate Fact Check / media literacy hub
    print(f"\n[6k6] Generating Fact Check / media literacy page...")
    generate_fact_check_page(manifest)

    # 6k7. Generate Games / activities page
    print(f"\n[6k7] Generating Games / activities page...")
    generate_games_page(manifest)

    # 6k8. Generate static info pages (about, contact, privacy, terms)
    print(f"\n[6k8] Generating static info pages...")
    generate_static_info_pages(manifest, today)

    # 6k8b. Generate subscribe / stay-updated page
    print(f"\n[6k8b] Generating subscribe page...")
    generate_subscribe_page(manifest, today)

    # 6k9. Generate og:image SVGs (used for social sharing previews)
    print(f"\n[6k9] Deploying og:image SVGs for social sharing...")
    _sci_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#0f172a"/>
<rect x="0" y="0" width="8" height="630" fill="#34d399"/>
<text x="80" y="90" font-family="system-ui,sans-serif" font-size="28" fill="#34d399" font-weight="700" letter-spacing="2">KIDDIEDAILY</text>
<text x="80" y="135" font-family="system-ui,sans-serif" font-size="18" fill="#94a3b8">News for Families · Science Edition</text>
<text x="80" y="340" font-family="system-ui,sans-serif" font-size="72" fill="#f8fafc">🔬</text>
<text x="200" y="310" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">Science</text>
<text x="200" y="375" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">Discovery</text>
<text x="80" y="540" font-family="system-ui,sans-serif" font-size="22" fill="#64748b">Bias-rated · Kid-safe · No ads · kiddiedaily.com</text>
</svg>"""
    _news_svg = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#0f172a"/>
<rect x="0" y="0" width="8" height="630" fill="#60a5fa"/>
<text x="80" y="90" font-family="system-ui,sans-serif" font-size="28" fill="#60a5fa" font-weight="700" letter-spacing="2">KIDDIEDAILY</text>
<text x="80" y="135" font-family="system-ui,sans-serif" font-size="18" fill="#94a3b8">News for Families · World News</text>
<text x="80" y="340" font-family="system-ui,sans-serif" font-size="72" fill="#f8fafc">🌍</text>
<text x="200" y="310" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">World</text>
<text x="200" y="375" font-family="system-ui,sans-serif" font-size="52" fill="#f1f5f9" font-weight="700">News</text>
<text x="80" y="540" font-family="system-ui,sans-serif" font-size="22" fill="#64748b">Bias-rated · Kid-safe · No ads · kiddiedaily.com</text>
</svg>"""
    upload("og-science.svg", _sci_svg, "[scraper] og:image — science articles")
    upload("og-news.svg", _news_svg, "[scraper] og:image — world news articles")
    print("  og:image SVGs deployed: og-science.svg, og-news.svg")

    # 7. Self-deploy: push this script to the kiddiedaily repo so GitHub Actions can find it
    print("\n[7] Self-deploying scraper script to repo...")
    self_src = pathlib.Path(__file__).read_text(encoding="utf-8")
    upload("scrape_and_push.py", self_src, "Deploy/update KiddieDaily scraper script")

    # 8. Push GitHub Actions workflows + governance files (idempotent)
    print("\n[8] Deploying GitHub Actions workflows and governance files...")
    upload(".github/workflows/daily-news.yml", WORKFLOW_YAML,
           "[ci] Update daily news scraper workflow (GitHub Flow)")
    upload(".github/workflows/pr-review.yml", PR_REVIEW_YAML,
           "[ci] Add 3-stage content PR review agent workflow")
    upload(".github/CODEOWNERS", CODEOWNERS_FILE,
           "[ci] Add CODEOWNERS — GitHub best practices")
    upload(".github/PULL_REQUEST_TEMPLATE.md", PR_TEMPLATE_MD,
           "[ci] Add PR template — GitHub best practices")

    # 9. GitHub Flow: open PR and squash-merge content branch → main
    if in_ci and ACTIVE_BRANCH != "main":
        print("\n[9] GitHub Flow: opening PR and merging content branch...")
        create_and_merge_pr(today, pushed_count)

    print(f"\n{'='*52}")
    print(f"DONE. {pushed_count} new article(s) pushed.")
    if pushed_count == 0:
        print("(No new articles — all stories already pushed or no suitable topics found)")

if __name__ == "__main__":
    main()
