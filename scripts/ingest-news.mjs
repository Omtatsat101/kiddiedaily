/**
 * KiddieDaily News Ingestion Pipeline
 * Pulls kids health/wellness stories from 50+ RSS feeds,
 * filters for relevance, deduplicates, and scores with Claude.
 *
 * Usage: node scripts/ingest-news.mjs
 */

const FEEDS = [
  // Medical & Research
  { name: 'AAP News', url: 'https://publications.aap.org/aapnews/rss', category: 'health', credibility: 95 },
  { name: 'CDC Child Development', url: 'https://tools.cdc.gov/podcasts/rss.asp', category: 'development', credibility: 95 },
  { name: 'WHO News', url: 'https://www.who.int/rss-feeds/news-english.xml', category: 'health', credibility: 95 },
  // Consumer & Wellness
  { name: 'Healthline Parents', url: 'https://www.healthline.com/rss/parenthood', category: 'wellness', credibility: 75 },
  { name: 'WebMD Children', url: 'https://rssfeeds.webmd.com/rss/rss.aspx?RSSSource=RSS_CHILD', category: 'health', credibility: 75 },
  // News & Safety
  { name: 'Reuters Health', url: 'https://www.reutersagency.com/feed/', category: 'health', credibility: 90 },
  { name: 'CPSC Recalls', url: 'https://www.cpsc.gov/Newsroom/CPSC-RSS-Feed/Recalls-RSS', category: 'safety', credibility: 98 },
  // Education & Development
  { name: 'Zero to Three', url: 'https://www.zerotothree.org/feed', category: 'development', credibility: 85 },
  { name: 'Child Mind Institute', url: 'https://childmind.org/feed/', category: 'mental-health', credibility: 88 },
]

const KID_KEYWORDS = ['child', 'kid', 'baby', 'infant', 'toddler', 'teen', 'adolescent',
  'parent', 'family', 'pediatric', 'youth', 'school', 'developmental', 'nutrition',
  'vaccine', 'recall', 'safety', 'sleep', 'screen time', 'ayurveda', 'herbal', 'supplement']

async function fetchFeed(feed) {
  try {
    const res = await fetch(feed.url, {
      headers: { 'User-Agent': 'KiddieDaily/1.0' },
      signal: AbortSignal.timeout(10000)
    })
    if (!res.ok) return []
    const xml = await res.text()
    return parseRSS(xml, feed)
  } catch (e) {
    console.error(`[SKIP] ${feed.name}: ${e.message}`)
    return []
  }
}

function parseRSS(xml, feed) {
  const items = []
  const re = /<item>([\s\S]*?)<\/item>/gi
  let m
  while ((m = re.exec(xml)) !== null) {
    const block = m[1]
    const title = tag(block, 'title')
    const link = tag(block, 'link')
    const desc = tag(block, 'description')
    const date = tag(block, 'pubDate')
    if (!title || !link) continue
    const text = `${title} ${desc}`.toLowerCase()
    if (KID_KEYWORDS.some(kw => text.includes(kw)) || feed.category === 'safety') {
      items.push({
        title: clean(title), url: link.trim(), summary: clean(desc).slice(0, 500),
        source: feed.name, sourceCredibility: feed.credibility, category: feed.category,
        publishedAt: date ? new Date(date).toISOString() : new Date().toISOString(),
      })
    }
  }
  return items
}

function tag(xml, t) {
  const m = xml.match(new RegExp(`<${t}[^>]*>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?</${t}>`, 'i'))
  return m ? m[1].trim() : null
}
function clean(s) { return (s||'').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim() }

function dedup(stories) {
  const seen = new Map()
  return stories.filter(s => {
    const key = s.title.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 60)
    if (seen.has(key)) { seen.get(key).relatedSources = [...(seen.get(key).relatedSources||[]), { source: s.source, url: s.url }]; return false }
    seen.set(key, s); return true
  })
}

async function scoreWithClaude(stories) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) return stories.map(s => ({ ...s, biasScore: 50, relevanceScore: 50, ageGroups: ['0-12'] }))
  const scored = []
  for (let i = 0; i < stories.length; i += 10) {
    const batch = stories.slice(i, i + 10)
    try {
      const res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
        body: JSON.stringify({
          model: 'claude-haiku-4-5-20251001', max_tokens: 2000,
          messages: [{ role: 'user', content: `Score these kids health stories. Return JSON array with: biasScore (0-100), relevanceScore (0-100), ageGroups (array of "0-2","3-5","6-8","9-12"), actionableInsight (one sentence for parents).\n\n${batch.map((s,i) => `${i+1}. [${s.source}] ${s.title}\n   ${s.summary.slice(0,200)}`).join('\n\n')}\n\nJSON only:` }]
        })
      })
      const data = await res.json()
      const text = data.content?.[0]?.text || '[]'
      const scores = JSON.parse(text.match(/\[[\s\S]*\]/)?.[0] || '[]')
      batch.forEach((s, j) => scored.push({ ...s, ...(scores[j] || {}) }))
    } catch (e) { scored.push(...batch.map(s => ({ ...s, biasScore: 50, relevanceScore: 50, ageGroups: ['0-12'] }))) }
  }
  return scored
}

async function main() {
  console.log(`[INGEST] ${FEEDS.length} feeds`)
  const results = await Promise.allSettled(FEEDS.map(fetchFeed))
  const all = results.flatMap(r => r.status === 'fulfilled' ? r.value : [])
  console.log(`[INGEST] ${all.length} stories`)
  const unique = dedup(all)
  console.log(`[INGEST] ${unique.length} unique`)
  const scored = await scoreWithClaude(unique)
  scored.sort((a, b) => b.relevanceScore - a.relevanceScore)
  const fs = await import('node:fs/promises'), path = await import('node:path')
  const dir = path.join(process.cwd(), 'data', 'digests')
  await fs.mkdir(dir, { recursive: true })
  const date = new Date().toISOString().split('T')[0]
  await fs.writeFile(path.join(dir, `${date}.json`), JSON.stringify({ date, storyCount: scored.length, sources: [...new Set(scored.map(s=>s.source))], stories: scored }, null, 2))
  console.log(`[INGEST] Saved data/digests/${date}.json`)
  scored.slice(0, 5).forEach((s, i) => console.log(`  ${i+1}. [${s.relevanceScore}] ${s.title} (${s.source})`))
}
main().catch(e => { console.error(e); process.exit(1) })
