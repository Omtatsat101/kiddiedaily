#!/usr/bin/env python3
"""
KiddieDaily Agentic Truth & Bias Verifier
Runs post-scrape as a separate GitHub Actions job.

For each article published today:
  1. Fetch HTML from the repo via GitHub Contents API
  2. Extract key claims + score truth confidence via Claude Haiku
  3. Detect loaded language / one-sided framing beyond source-level bias
  4. Inject a "Truth Check" panel into the article HTML
  5. Push updated HTML back to the repo

Secrets required (both already set on the repo):
  GITHUB_TOKEN    — built-in (contents:write)
  ANTHROPIC_API_KEY — for Claude Haiku claim analysis
"""

import os
import json
import base64
import time
import re
import sys
from datetime import date, datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO = "Omtatsat101/kiddiedaily"
MODEL = "claude-haiku-4-5-20251001"
MAX_ARTICLES_PER_RUN = 12
CLAUDE_TIMEOUT = 30
GITHUB_TIMEOUT = 20

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

ANT_HEADERS = {
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------
def gh_get(path: str) -> dict | None:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers=GH_HEADERS, timeout=GITHUB_TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def gh_put(path: str, content: str, message: str, sha: str | None = None) -> bool:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    body: dict = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "committer": {"name": "KiddieDaily Bot", "email": "bot@kiddiedaily.com"},
    }
    if sha:
        body["sha"] = sha
    r = requests.put(url, headers=GH_HEADERS, json=body, timeout=GITHUB_TIMEOUT)
    return r.status_code in (200, 201)


# ---------------------------------------------------------------------------
# Claude analysis
# ---------------------------------------------------------------------------
def claude_analyze(title: str, snippet: str, n_sources: int, bias_avg: float) -> dict:
    """
    Extract claims + score truth confidence + detect bias signals.
    Returns a dict with keys: claims, truth_confidence, bias_signals,
    missing_context, kid_safe_rating.
    Falls back to safe defaults on any error.
    """
    default = {
        "claims": [],
        "truth_confidence": 65,
        "bias_signals": [],
        "missing_context": None,
        "kid_safe_rating": "G",
    }

    if not ANTHROPIC_API_KEY:
        return default

    prompt = f"""You are a fact-checking assistant for KiddieDaily, a children's news site for ages 5-12.

ARTICLE TITLE: {title}

CONTENT SNIPPET (first 900 chars of article text):
{snippet[:900]}

SCRAPER METADATA: {n_sources} independent source(s) covered this story. Bias average: {bias_avg:.2f} (-2=far left, 0=center, +2=far right).

Return ONLY a JSON object (no explanation, no markdown fences) with these exact keys:

{{
  "claims": ["short claim 1", "short claim 2"],
  "truth_confidence": 75,
  "bias_signals": ["example loaded phrase"],
  "missing_context": "brief note or null",
  "kid_safe_rating": "G"
}}

Rules:
- claims: 2-3 key factual claims from the article, each under 12 words
- truth_confidence: integer 0-100
  * Start at 65 for single-source opinion/editorial
  * +10 per additional independent source (max +30)
  * +15 if source is NASA, NIH, academic institution, or peer-reviewed science
  * -15 if the article is primarily opinion/editorial/analysis
  * -10 if bias_avg is < -1.0 or > +1.0 (extreme lean)
  * Maximum 95, minimum 25
- bias_signals: list of 0-3 specific loaded words or one-sided framing examples found in the text; empty list if none
- missing_context: a single phrase (<20 words) describing the most important missing perspective, or null if balanced
- kid_safe_rating: "G" (any age), "PG" (parental guidance suggested), or "PG-13" (older kids, discuss with parent)
  * PG-13 only for: death/war with graphic details, health crises with scary stats, significant political controversy
  * PG for: mild conflict, minor scary elements, complex geopolitics
  * G for: science, nature, animals, sports, arts, achievements"""

    payload = {
        "model": MODEL,
        "max_tokens": 350,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=ANT_HEADERS,
            json=payload,
            timeout=CLAUDE_TIMEOUT,
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        # Strip markdown fences if model added them
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return default
        parsed = json.loads(m.group())
        # Sanitise
        parsed["truth_confidence"] = max(25, min(95, int(parsed.get("truth_confidence", 65))))
        parsed["kid_safe_rating"] = parsed.get("kid_safe_rating", "G")
        if parsed["kid_safe_rating"] not in ("G", "PG", "PG-13"):
            parsed["kid_safe_rating"] = "G"
        parsed["claims"] = [str(c) for c in parsed.get("claims", [])[:3]]
        parsed["bias_signals"] = [str(s) for s in parsed.get("bias_signals", [])[:3]]
        return parsed
    except Exception as exc:
        print(f"    Claude error: {exc}")
        return default


# ---------------------------------------------------------------------------
# HTML injection
# ---------------------------------------------------------------------------
_TRUTH_RE = re.compile(
    r"<!-- TRUTH_CHECK_START -->.*?<!-- TRUTH_CHECK_END -->",
    re.DOTALL,
)

def build_truth_html(result: dict) -> str:
    tc = result["truth_confidence"]
    rating = result["kid_safe_rating"]

    if tc >= 80:
        badge_emoji, badge_label, badge_color = "✅", "High Confidence", "#38a169"
    elif tc >= 60:
        badge_emoji, badge_label, badge_color = "🔍", "Moderate Confidence", "#d69e2e"
    else:
        badge_emoji, badge_label, badge_color = "⚠️", "Use Caution", "#e53e3e"

    rating_color = {"G": "#38a169", "PG": "#d69e2e", "PG-13": "#c05621"}.get(rating, "#38a169")

    claims_li = "".join(
        f'<li style="margin-bottom:4px">{c}</li>' for c in result["claims"]
    )
    claims_block = (
        f'<ul style="margin:8px 0 0;padding-left:18px;font-size:.83rem;color:#4a5568">'
        f"{claims_li}</ul>"
        if claims_li
        else ""
    )

    signals_spans = " ".join(
        f'<span style="display:inline-block;background:#fff5f5;color:#c53030;'
        f'border-radius:4px;padding:1px 6px;font-size:.75rem;margin:2px 2px 0 0">'
        f"&ldquo;{s}&rdquo;</span>"
        for s in result["bias_signals"]
    )
    signals_block = (
        f'<div style="margin-top:8px;font-size:.8rem;color:#718096">'
        f"Bias signals: {signals_spans}</div>"
        if signals_spans
        else ""
    )

    mc = result.get("missing_context") or ""
    missing_block = (
        f'<p style="margin:8px 0 0;font-size:.8rem;color:#718096">'
        f"<strong>Missing context:</strong> {mc}</p>"
        if mc
        else ""
    )

    return (
        "<!-- TRUTH_CHECK_START -->\n"
        '<div class="kd-truth-box" style="margin:24px 0;padding:16px 20px;'
        "border-radius:12px;background:#f7fafc;border:1px solid #e2e8f0;"
        'font-family:system-ui,sans-serif;font-size:.9rem">\n'
        '  <div style="display:flex;align-items:center;gap:10px">\n'
        f'    <span style="font-size:1.3rem">{badge_emoji}</span>\n'
        "    <div>\n"
        f'      <div style="font-weight:700;color:#2d3748">Truth Check</div>\n'
        f'      <div style="color:{badge_color};font-weight:600;font-size:.8rem">'
        f"{badge_label} &middot; {tc}%</div>\n"
        "    </div>\n"
        f'    <span style="margin-left:auto;background:{rating_color};color:#fff;'
        f"font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:99px;"
        f'letter-spacing:.03em">{rating}</span>\n'
        "  </div>\n"
        f"  {claims_block}\n"
        f"  {signals_block}\n"
        f"  {missing_block}\n"
        '  <div style="margin-top:10px;font-size:.72rem;color:#a0aec0">'
        'Verified by KiddieDaily AI &middot; '
        '<a href="/fact-check/" style="color:#667eea;text-decoration:none">'
        "Learn about our fact-checking</a></div>\n"
        "</div>\n"
        "<!-- TRUTH_CHECK_END -->"
    )


def inject_truth_check(html: str, truth_html: str) -> str:
    """Inject or replace the truth-check block in article HTML."""
    # Replace existing block
    if "<!-- TRUTH_CHECK_START -->" in html:
        return _TRUTH_RE.sub(truth_html, html)

    # Try to insert after the bias box (before sources div)
    for marker in (
        '<div class="sources"',
        '<div class="kd-sources"',
        "<h4>Original Sources</h4>",
        '<div class="source-links"',
    ):
        if marker in html:
            return html.replace(marker, truth_html + "\n" + marker, 1)

    # Fallback: before the first </section> or before <footer
    if "</section>" in html:
        return html.replace("</section>", truth_html + "\n</section>", 1)
    if "<footer" in html:
        idx = html.find("<footer")
        return html[:idx] + truth_html + "\n" + html[idx:]

    # Last resort: before </body>
    return html.replace("</body>", truth_html + "\n</body>")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def strip_tags(html: str) -> str:
    """Very fast tag stripper — good enough for snippet extraction."""
    return re.sub(r"<[^>]+>", " ", html)


def run() -> int:
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN not set — cannot access GitHub API.")
        return 1

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{ts}] KiddieDaily Truth Verifier — starting")

    # Read manifest
    manifest_data = gh_get("data/kd-scraped-manifest.json")
    if not manifest_data:
        print("Manifest not found at data/kd-scraped-manifest.json — nothing to do.")
        return 0

    manifest = json.loads(base64.b64decode(manifest_data["content"]).decode())
    articles = manifest.get("articles", [])

    # Prefer today; fall back to yesterday for UTC timezone edge cases
    today_articles = [a for a in articles if a.get("date") in (TODAY, YESTERDAY)]
    today_articles = today_articles[:MAX_ARTICLES_PER_RUN]

    if not today_articles:
        print(f"No articles found for {TODAY} or {YESTERDAY} — nothing to verify.")
        return 0

    print(f"Found {len(today_articles)} article(s) to verify (today={TODAY}).")
    updated = 0

    for article in today_articles:
        slug = article.get("slug", "")
        if not slug.endswith(".html"):
            slug += ".html"

        print(f"  → {slug}")

        file_data = gh_get(slug)
        if not file_data:
            print("    ✗ Not found in repo — skipped.")
            continue

        html = base64.b64decode(file_data["content"]).decode("utf-8", errors="replace")
        sha = file_data["sha"]

        if "<!-- TRUTH_CHECK_START -->" in html:
            print("    ✓ Already verified — skipped.")
            continue

        # Extract readable text for Claude (strip HTML tags)
        snippet = strip_tags(html)
        snippet = re.sub(r"\s+", " ", snippet).strip()

        result = claude_analyze(
            title=article.get("display_title") or article.get("title", ""),
            snippet=snippet,
            n_sources=article.get("n_sources", 1),
            bias_avg=float(article.get("bias_avg", 0.0)),
        )
        time.sleep(0.4)  # Claude courtesy rate limit

        truth_html = build_truth_html(result)
        updated_html = inject_truth_check(html, truth_html)

        if updated_html == html:
            print("    ✗ Could not find injection point — skipped.")
            continue

        slug_short = slug.split("/")[-1]
        ok = gh_put(
            path=slug,
            content=updated_html,
            message=f"feat(truth): truth-check badge — {slug_short} [bot]",
            sha=sha,
        )

        if ok:
            rating = result["kid_safe_rating"]
            tc = result["truth_confidence"]
            print(f"    ✅ Updated  tc={tc}%  rating={rating}")
            updated += 1
        else:
            print("    ❌ GitHub push failed.")

        time.sleep(1.2)  # GitHub secondary rate limit guard

    print(f"\nDone. Updated {updated}/{len(today_articles)} article(s).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
