"""
KiddieDaily Agentic News Scraper v1.0
Fetches RSS from curated bias-rated sources → scores bias + source agreement → generates kid-friendly
HTML articles → pushes to Omtatsat101/kiddiedaily GitHub Pages.

Local run:  python scrape_and_push.py
GitHub Actions: triggered daily at 10am UTC via .github/workflows/daily-news.yml (self-deployed)

Requires:  GITHUB_TOKEN  (env var or projects/API-KEYS.env)
Optional:  ANTHROPIC_API_KEY  (for Claude Haiku kid-friendly rewrites)
"""
import urllib.request, urllib.error, ssl, json, base64, time, os, pathlib, re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

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
            if jaccard(s["title"], other["title"]) > 0.28:
                group.append(other)
                used.add(j)
        groups.append(group)
    # Prefer groups with more sources, then science/tech topics
    groups.sort(key=lambda g: (
        -len(g),
        abs(sum(s["source_bias"] for s in g) / len(g))  # prefer center bias
    ))
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
    prompt = f"""Rewrite this news story for KiddieDaily — a fact-checked news site for kids ages 8–14.

Original headline: {title}
Original summary: {description}

Write (return ONLY the article, no commentary):
Line 1: Kid-friendly headline (exciting, accurate, under 12 words)
Line 2: (blank)
Lede paragraph: 2–3 sentences, engaging hook explaining what happened and why it's interesting.
Then 2–3 short sections (each starts with ## Header):
- What Happened (the facts, simply explained)
- Why It Matters (impact on kids/families/world)
- Think About This (one reflective question for family discussion)

Rules: factual, age-appropriate, no violence/politics/adult content, warm + curious tone."""

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
def body_from_rss(group):
    rep = group[0]
    desc = rep["description"]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", desc) if len(s.strip()) > 20]
    lede = " ".join(sentences[:2]) if sentences else desc[:200]
    rest = " ".join(sentences[2:]) if len(sentences) > 2 else ""

    html = [f'<p class="lede">{lede}</p>']
    if rest:
        html.append(f"<h2>What Happened</h2><p>{rest}</p>")

    others = [s for s in group[1:3] if s["description"] and s["description"][:100] != desc[:100]]
    if others:
        html.append(f"<h2>How {others[0]['source_name']} Covers It</h2><p>{others[0]['description'][:500]}</p>")

    html.append("""<h2>Think About This</h2>
<p>What questions does this story raise for you? Talk with your family: Why does this news matter?
Who is affected? What might happen next? Is there anything you can do?</p>""")
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
        f'<li><a href="{s["link"]}" rel="noopener nofollow" target="_blank">'
        f'{s["source_name"]}: {s["title"][:75]}{"..." if len(s["title"])>75 else ""}</a></li>'
        for s in group
    )
    body = f"""<p class="byline">By KiddieDaily Editors &middot; {today} &middot; Aggregated from {n} source{"s" if n!=1 else ""}</p>
<h1>{title}</h1>
{bias_html}
{body_html}
<div class="sources"><h4>Original Sources</h4><ul>{source_items}</ul></div>
<p><em>More stories: <a href="/news/">Kid News</a> &middot; <a href="/fact-check/">Fact Check</a></em></p>"""

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
{CSS}</head><body>{HEADER}<main>{body}</main>{FOOTER}</body></html>"""

# ── Manifest: tracks pushed slugs to avoid duplicates ─────────────────────────
def load_manifest():
    r = gh("GET", f"/repos/{REPO}/contents/data/kd-scraped-manifest.json")
    if r.get("_err") or not r.get("content"):
        return {"pushed_slugs": [], "pushed_titles": []}
    try:
        return json.loads(base64.b64decode(r["content"]).decode("utf-8"))
    except Exception:
        return {"pushed_slugs": [], "pushed_titles": []}

def save_manifest(manifest):
    upload("data/kd-scraped-manifest.json",
           json.dumps(manifest, indent=2, ensure_ascii=False),
           "Update scraped articles manifest")

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
            pushed_count += 1

    # 6. Save manifest
    if pushed_count > 0:
        print(f"\n[6] Saving manifest...")
        save_manifest(manifest)

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
