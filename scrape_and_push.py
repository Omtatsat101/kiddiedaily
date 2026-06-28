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
MAX_ARTICLES = 3   # max new articles per run

if not GITHUB_TOKEN:
    raise SystemExit("GITHUB_TOKEN not found: set env var or add to projects/API-KEYS.env")

# ── GitHub Contents API ────────────────────────────────────────────────────────
def gh(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"https://api.github.com{path}", data=data,
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "User-Agent": "kd-scraper",
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
        method=method)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20, context=ctx).read())
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "_body": e.read().decode()[:300]}

def upload(repo_path, content_str, message):
    existing = gh("GET", f"/repos/{REPO}/contents/{repo_path}")
    sha = existing.get("sha") if isinstance(existing, dict) and not existing.get("_err") else None
    encoded = base64.b64encode(content_str.encode("utf-8")).decode()
    payload = {"message": message, "content": encoded, "branch": "main"}
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

# ── RSS sources with AllSides / Ad Fontes Media bias ratings ──────────────────
# bias: -2=far-left  -1=left  0=center  +1=right  +2=far-right
SOURCES = [
    {"name": "BBC News",      "url": "http://feeds.bbci.co.uk/news/rss.xml",                   "bias": -0.3, "icon": "🇬🇧"},
    {"name": "NPR",           "url": "https://feeds.npr.org/1001/rss.xml",                      "bias": -0.7, "icon": "📻"},
    {"name": "Al Jazeera",    "url": "https://www.aljazeera.com/xml/rss/all.xml",              "bias": -0.4, "icon": "🌍"},
    {"name": "The Hill",      "url": "https://thehill.com/news/feed/",                          "bias":  0.1, "icon": "⚖️"},
    {"name": "Fox News",      "url": "https://moxie.foxnews.com/google-publisher/latest.xml",   "bias":  1.3, "icon": "🦅"},
    {"name": "NASA",          "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",          "bias":  0.0, "icon": "🚀"},
    {"name": "Science Daily", "url": "https://www.sciencedaily.com/rss/all.xml",               "bias":  0.0, "icon": "🔬"},
    {"name": "Smithsonian",   "url": "https://www.smithsonianmag.com/rss/latest_articles/",    "bias": -0.1, "icon": "🏛️"},
]

# ── Kid-safety filter ──────────────────────────────────────────────────────────
BLOCKLIST = [
    "murder", "killed", "shooting", "massacre", "rape", "sexual assault",
    "suicide", "overdose", "cocaine", "heroin", "fentanyl",
    "explicit", "porn", "adult content",
    "war crime", "genocide", "torture", "execution", "beheading",
]
SAFE_OVERRIDES = ["space", "science", "animal", "planet", "nature", "research",
                  "invention", "discovery", "environment", "ocean", "climate"]

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

    ATOM = "http://www.w3.org/2005/Atom"

    def get_field(item, *tags):
        for tag in tags:
            el = item.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            el = item.find(f"{{{ATOM}}}{tag}")
            if el is not None and el.text:
                return el.text.strip()
        return ""

    items = root.findall(".//item")
    if not items:
        items = root.findall(f".//{{{ATOM}}}entry")

    stories = []
    for item in items[:25]:
        title = clean(get_field(item, "title"))
        link  = clean(get_field(item, "link", "url"))
        desc  = clean(get_field(item, "description", "summary", "content"))
        pub   = get_field(item, "pubDate", "published", "updated")

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

SCIENCE_SOURCES = {"NASA", "Science Daily", "Smithsonian"}
DEPRIORITIZE_WORDS = [
    "war", "strike", "bomb", "missile", "airstrike", "military",
    "attack", "troops", "soldier", "killed", "dead", "death",
    "iran", "israel", "ukraine", "russia", "hamas", "congress",
    "senate", "republican", "democrat", "trump", "biden", "president",
    "election", "indicted", "arrested", "shooting", "crash",
]

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
            if jaccard(s["title"], other["title"]) > 0.25:
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
SKIP_PARA_WORDS = ["cookie", "subscribe", "newsletter", "javascript", "sign up",
                   "advertisement", "click here", "read more", "follow us",
                   "privacy policy", "terms of use", "all rights reserved",
                   "copyright", "©", "skip to", "share this", "email address"]

def fetch_article_text(url, fallback):
    """Fetch full article text from source URL; return cleaned paragraphs or fallback."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; KiddieDaily/1.0)"})
        raw = urllib.request.urlopen(req, timeout=10, context=ctx).read().decode("utf-8", errors="replace")
        # Strip scripts, styles, nav, footer, aside
        raw = re.sub(r"<(script|style|nav|footer|aside|header)[^>]*>.*?</\1>",
                     "", raw, flags=re.DOTALL | re.IGNORECASE)
        # Extract <p> content
        paras = re.findall(r"<p[^>]*>(.*?)</p>", raw, re.DOTALL | re.IGNORECASE)
        paras = [re.sub(r"<[^>]+>", "", p).strip() for p in paras]
        paras = [
            re.sub(r"\s+", " ", p)
            for p in paras
            if len(p) > 55
            and not any(w in p.lower() for w in SKIP_PARA_WORDS)
        ]
        if len(paras) >= 2:
            return " ".join(paras[:7])
    except Exception:
        pass
    return fallback


def body_from_rss(group):
    rep = group[0]
    # Try to fetch full text; fall back to RSS description
    full_text = fetch_article_text(rep["link"], rep["description"])

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", full_text) if len(s.strip()) > 25]
    lede   = " ".join(sentences[:2]) if sentences else full_text[:220]
    middle = " ".join(sentences[2:5]) if len(sentences) > 2 else ""
    extra  = " ".join(sentences[5:9]) if len(sentences) > 5 else ""

    html = [f'<p class="lede">{lede}</p>']
    if middle:
        html.append(f"<h2>What Happened</h2><p>{middle}</p>")
    if extra:
        html.append(f"<p>{extra}</p>")

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
<nav><a href="/news/">Kid News</a><a href="/parents/">For Parents</a><a href="/fact-check/">Fact Check</a>
<a href="/games/">Games</a><a href="/about.html">About</a><a href="/parent-zone/" class="pz-cta">Parent Zone</a></nav>
</div></header>"""

FOOTER = """<footer class="kd"><div class="inner">
<div style="flex:1;min-width:200px"><h4>KiddieDaily</h4>
<p style="margin:0;font-size:14px;color:#cbd5e0">Curated daily news for families with research-backed fact checks.</p></div>
<div><h4>Read</h4><a href="/news/">Kid News</a><a href="/parents/">For Parents</a>
<a href="/fact-check/">Fact Check</a><a href="/games/">Games</a></div>
<div><h4>Account</h4><a href="/parent-zone/">Parent Zone</a><a href="/about.html">About</a>
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

def build_page(title, body_html, bias_html, score, group, slug, today):
    n = score["n_sources"]
    url = f"https://kiddiedaily.com/{slug}"
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

    rt = reading_time(body_html)
    body = f"""<p class="byline">By KiddieDaily Editors &middot; {today} &middot; {rt} &middot; {n} source{"s" if n!=1 else ""}</p>
<h1>{title}</h1>
{bias_html}
{body_html}
<div class="sources"><h4>Original Sources</h4><ul>{source_items}</ul></div>
<p style="margin-top:16px;padding:10px 14px;background:#f0fff4;border:1px solid #c6f6d5;border-radius:8px;font-size:13px">
&#128269; <strong>Want to verify this story?</strong>
<a href="{fact_check_url}" rel="noopener nofollow" target="_blank" style="color:#065f46">Check it on Google Fact Check Explorer &rarr;</a>
</p>
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
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{title}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E%3Ctext y=%22.9em%22 font-size=%2290%22%3E&#x1f4f0;%3C/text%3E%3C/svg%3E">
<script type="application/ld+json">{jsonld}</script>
{CSS}</head><body>{HEADER}<main>{body}</main>{FOOTER}
<script>
(function(){{
  const SLUG="{slug}";
  const TITLE_WORDS=new Set("{title}".toLowerCase().replace(/[^\w\s]/g,"").split(/\s+/).filter(w=>w.length>3&&!["that","this","with","from","have","were","they","more"].includes(w)));
  fetch("/data/kd-articles.json").then(r=>r.json()).then(articles=>{{
    const scored=articles.filter(a=>a.slug!==SLUG).map(a=>{{
      const w=new Set(a.title.toLowerCase().replace(/[^\w\s]/g,"").split(/\s+/).filter(x=>x.length>3));
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
    return f"{SCRAPED_START}\n{KD_CARD_CSS}\n<h2 class=\"kd-today-hdr\">Today&#39;s news</h2>\n{inner}\n{SCRAPED_END}"

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

# ── Sitemap ───────────────────────────────────────────────────────────────────
STATIC_URLS = [
    "/", "/news/", "/parents/", "/fact-check/", "/games/",
    "/news/galaxy-far-far-away.html",
    "/news/water-filter-invention.html",
    "/news/sea-turtles-comeback.html",
    "/parents/screen-time-balance.html",
    "/parents/back-to-school-anxiety.html",
    "/parents/read-aloud-after-8.html",
    "/fact-check/tylenol-kids-brains.html",
    "/fact-check/social-media-teen-depression.html",
    "/games/index.html",
    "/about.html", "/privacy.html", "/terms.html", "/contact.html",
    "/feed.xml", "/news/archive.html", "/news/science.html", "/news/world.html",
]

def update_sitemap(pushed_slugs):
    BASE_URL = "https://kiddiedaily.com"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Collect all URLs
    urls = list(STATIC_URLS)
    for slug in pushed_slugs:
        # slug is already a full repo path like "news/2026-06-26-title.html"
        url = f"/{slug}" if not slug.startswith("/") else slug
        if url not in urls:
            urls.append(url)

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

    trending_html = build_trending(manifest)
    new_block = (
        f'{HOMEPAGE_START}\n'
        f'<h2>Today\'s top kid news</h2>\n'
        + "\n".join(cards) +
        f'\n<p style="text-align:right;font-size:13px;margin-top:4px">'
        f'<a href="/news/">All news</a> &middot; '
        f'<a href="/news/science.html">Science</a> &middot; '
        f'<a href="/news/archive.html">Archive</a></p>\n'
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
<meta name="description" content="All KiddieDaily news articles — kid-friendly, bias-rated, fact-checked daily.">
<link rel="canonical" href="https://kiddiedaily.com/news/archive.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
<style>
body{{margin:0;font-family:Georgia,serif;background:#f0f4f8;color:#2d3748}}
header.kd{{background:#1a4d80;padding:14px 0}}
header.kd .inner{{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px;padding:0 20px}}
header.kd .logo{{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif;text-decoration:none}}
header.kd nav{{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}}
header.kd nav a{{color:#fff;font-size:15px;font-family:system-ui,sans-serif}}
main{{max-width:780px;margin:0 auto;padding:32px 24px 64px}}
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:8px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-badge-news{{background:#dbeafe;color:#1e40af}}
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
footer{{background:#1a4d80;color:#a0aec0;padding:28px 0;font-family:system-ui,sans-serif;font-size:13px;text-align:center}}
</style></head>
<body>
<header class="kd"><div class="inner">
<a href="/" class="logo">KiddieDaily<small>news for families</small></a>
<nav><a href="/news/">Kid News</a><a href="/parents/">For Parents</a><a href="/fact-check/">Fact Check</a><a href="/parent-zone/">Parent Zone</a></nav>
</div></header>
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

<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096">
  <a href="/feed.xml">Subscribe via RSS</a> &middot; <a href="/news/">Latest news</a>
</p>
</main>
<footer><p>&copy; KiddieDaily &mdash; <a href="/privacy.html" style="color:#a0aec0">Privacy</a> &middot; <a href="/feed.xml" style="color:#a0aec0">RSS</a></p></footer>

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
    cats = {
        "science": [a for a in articles if a.get("is_science")],
        "world":   [a for a in articles if not a.get("is_science")],
    }
    cat_labels = {"science": "Science", "world": "World News"}
    desc = {
        "science": "Space, animals, inventions, and discoveries — science stories for curious kids.",
        "world":   "What's happening around the world, explained for families.",
    }

    for key, arts in cats.items():
        if not arts:
            continue
        arts = sorted(arts, key=lambda x: x.get("date", ""), reverse=True)
        label = cat_labels[key]

        rows = []
        for a in arts[:20]:
            slug  = a["slug"]
            title = a.get("display_title", a.get("title", ""))
            date  = a.get("date", "")
            n     = a.get("n_sources", 1)
            bias  = a.get("bias_avg", 0.0)
            dot_pct = max(5, min(95, round((bias + 2) / 4 * 100)))
            agree = f"{n} outlet{'s' if n!=1 else ''}"
            rows.append(
                f'<div class="kd-sc">'
                f'<div class="kd-sc-top"><span class="kd-badge kd-badge-sci">{label}</span>'
                f'<span style="font-size:11px;color:#718096;margin-left:auto">{agree} &middot; {date}</span></div>'
                f'<h3 style="margin:4px 0 6px"><a href="/{slug}">{title}</a></h3>'
                f'<div class="kd-mini-bias"><span class="kd-mini-lbl">L</span>'
                f'<div class="kd-mini-track"><span class="kd-mini-dot" style="left:{dot_pct}%"></span></div>'
                f'<span class="kd-mini-lbl" style="text-align:right">R</span></div>'
                f'</div>'
            )

        page = f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{label} News — KiddieDaily</title>
<meta name="description" content="{desc[key]}">
<link rel="canonical" href="https://kiddiedaily.com/news/{key}.html">
<link rel="alternate" type="application/rss+xml" title="KiddieDaily RSS" href="/feed.xml">
<style>
body{{margin:0;font-family:Georgia,serif;background:#f0f4f8;color:#2d3748}}
header.kd{{background:#1a4d80;padding:14px 0}}
header.kd .inner{{max-width:980px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;gap:18px;padding:0 20px}}
header.kd .logo{{font-weight:700;font-size:22px;color:#fff;font-family:Georgia,serif;text-decoration:none}}
header.kd nav{{display:flex;flex-wrap:wrap;gap:18px;flex:1;justify-content:flex-end}}
header.kd nav a{{color:#fff;font-size:15px;font-family:system-ui,sans-serif}}
main{{max-width:780px;margin:0 auto;padding:32px 24px 64px}}
.kd-sc{{background:#fff;border:1px solid #dde4ef;border-radius:10px;padding:14px 18px 12px;margin:10px 0;box-shadow:0 1px 4px rgba(0,0,0,.06)}}
.kd-sc-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.kd-badge{{font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;padding:2px 8px;border-radius:20px}}
.kd-badge-sci{{background:#d1fae5;color:#065f46}}
.kd-mini-bias{{display:flex;align-items:center;gap:6px;margin-top:8px}}
.kd-mini-lbl{{font-size:10px;font-weight:700;color:#718096;width:16px}}
.kd-mini-track{{flex:1;height:6px;border-radius:3px;background:linear-gradient(to right,#3182ce 0%,#805ad5 50%,#e53e3e 100%);position:relative}}
.kd-mini-dot{{position:absolute;top:-5px;width:16px;height:16px;background:#fff;border:2px solid #4a5568;border-radius:50%;transform:translateX(-50%)}}
.kd-sc h3 a{{color:#1a4d80;text-decoration:none}}
footer{{background:#1a4d80;color:#a0aec0;padding:28px 0;font-family:system-ui,sans-serif;font-size:13px;text-align:center}}
</style></head>
<body>
<header class="kd"><div class="inner">
<a href="/" class="logo">KiddieDaily<small>news for families</small></a>
<nav><a href="/news/">All News</a><a href="/news/science.html">Science</a><a href="/news/world.html">World</a><a href="/news/archive.html">Archive</a></nav>
</div></header>
<main>
<h1 style="font-size:28px;margin-bottom:4px">{label} News</h1>
<p style="color:#718096;font-family:system-ui,sans-serif;font-size:14px;margin:0 0 24px">{desc[key]} {len(arts)} stories.</p>
{"".join(rows)}
<p style="text-align:center;margin-top:32px;font-size:13px;color:#718096">
  <a href="/news/archive.html">Full archive</a> &middot; <a href="/feed.xml">RSS feed</a> &middot; <a href="/news/">All news</a>
</p>
</main>
<footer><p>&copy; KiddieDaily &mdash; <a href="/privacy.html" style="color:#a0aec0">Privacy</a></p></footer>
</body></html>"""

        upload(f"news/{key}.html", page, f"[scraper] {label} category page — {len(arts)} articles")
    print(f"  Category pages: science={len(cats['science'])} world={len(cats['world'])}")


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
            "slug":     a["slug"],
            "title":    a.get("display_title", a.get("title", "")),
            "date":     a.get("date", ""),
            "is_science": a.get("is_science", False),
            "bias_avg": a.get("bias_avg", 0.0),
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


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\nKiddieDaily Scraper — {today}")
    print("=" * 52)

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
    print(f"\n[5] Generating articles (max {MAX_ARTICLES} per run)...")
    pushed_count = 0

    for group in groups:
        if pushed_count >= MAX_ARTICLES:
            break

        rep = group[0]
        slug = make_slug(rep["title"], today)
        if slug in pushed_slugs:
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

    # 6. Save manifest (always if changed: new articles OR migration)
    manifest_dirty = pushed_count > 0 or "articles" in manifest
    if manifest_dirty:
        print(f"\n[6] Saving manifest ({len(manifest.get('articles',[]))} total articles)...")
        save_manifest(manifest)

    # 6b. Always rebuild news index if we have articles
    if manifest.get("articles"):
        print(f"\n[6b] Updating news/index.html...")
        update_news_index(manifest)

    # 6c. Update sitemap with any new article URLs
    if pushed_count > 0:
        print(f"\n[6c] Updating sitemap.xml...")
        update_sitemap(manifest.get("pushed_slugs", []))

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

    # 7. Self-deploy: push this script to the kiddiedaily repo so GitHub Actions can find it
    print("\n[7] Self-deploying scraper script to repo...")
    self_src = pathlib.Path(__file__).read_text(encoding="utf-8")
    upload("scrape_and_push.py", self_src, "Deploy/update KiddieDaily scraper script")

    # 8. Push GitHub Actions workflow (idempotent)
    print("\n[8] Deploying GitHub Actions workflow...")
    upload(".github/workflows/daily-news.yml", WORKFLOW_YAML,
           "Add daily news scraper workflow")

    print(f"\n{'='*52}")
    print(f"DONE. {pushed_count} new article(s) pushed.")
    if pushed_count == 0:
        print("(No new articles — all stories already pushed or no suitable topics found)")

if __name__ == "__main__":
    main()
