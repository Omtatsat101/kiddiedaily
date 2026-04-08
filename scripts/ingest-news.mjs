/**
 * KiddieDaily News Ingestion Pipeline
 * Pulls kids health/wellness stories from 50+ RSS feeds,
 * filters for relevance, deduplicates, and scores with Claude.
 *
 * Usage: node scripts/ingest-news.mjs
 *
 * Data directory structure:
 *   data/
 *     digests/          — daily digest JSON files
 *     subscribers.json  — subscriber list
 *     publishers.json   — publisher applications
 *     moderation.json   — content moderation queue
 *     custom-sources.json — admin-added RSS sources
 */

import { DEFAULT_SOURCES } from '../lib/sources.mjs'
import { quickClassify } from '../lib/safety-gate.mjs'

const KID_KEYWORDS = ['child', 'kid', 'baby', 'infant', 'toddler', 'teen', 'adolescent',
  'parent', 'family', 'pediatric', 'youth', 'school', 'developmental', 'nutrition',
  'vaccine', 'recall', 'safety', 'sleep', 'screen time', 'ayurveda', 'herbal', 'supplement']

async function loadAllSources() {
  // Start with default sources from lib/sources.mjs
  const sources = DEFAULT_SOURCES.map((s, i) => ({
    name: s.name,
    url: s.url,
    category: s.category,
    credibility: s.credibility,
    tier: s.tier,
  }))

  // Merge any admin-added custom sources
  try {
    const fs = await import('node:fs/promises')
    const path = await import('node:path')
    const customPath = path.join(process.cwd(), 'data', 'custom-sources.json')
    const customData = JSON.parse(await fs.readFile(customPath, 'utf8'))
    for (const src of customData.sources || []) {
      if (src.isActive) {
        sources.push({
          name: src.name,
          url: src.url,
          category: src.category || 'health',
          credibility: src.credibility || 70,
          tier: src.tier || 'consumer',
        })
      }
    }
    console.log(`[INGEST] Loaded ${customData.sources?.length || 0} custom sources`)
  } catch {
    // No custom sources file — that's fine
  }

  return sources
}

async function fetchFeed(feed) {
  try {
    const res = await fetch(feed.url, {
      headers: { 'User-Agent': 'KiddieDaily/1.0 (kids health news aggregator)' },
      signal: AbortSignal.timeout(10000)
    })
    if (!res.ok) {
      console.error(`[SKIP] ${feed.name}: HTTP ${res.status}`)
      return []
    }
    const xml = await res.text()
    return parseRSS(xml, feed)
  } catch (e) {
    console.error(`[SKIP] ${feed.name}: ${e.message}`)
    return []
  }
}

function parseRSS(xml, feed) {
  const items = []

  // Try <item> (RSS 2.0) and <entry> (Atom)
  const itemRegex = /<item>([\s\S]*?)<\/item>/gi
  const entryRegex = /<entry>([\s\S]*?)<\/entry>/gi

  let matches = [...xml.matchAll(itemRegex)]
  if (matches.length === 0) {
    matches = [...xml.matchAll(entryRegex)]
  }

  for (const m of matches) {
    const block = m[1]
    const title = tag(block, 'title')
    const link = tag(block, 'link') || extractAtomLink(block)
    const desc = tag(block, 'description') || tag(block, 'summary') || tag(block, 'content')
    const date = tag(block, 'pubDate') || tag(block, 'updated') || tag(block, 'published')

    if (!title || !link) continue

    const text = `${title} ${desc || ''}`.toLowerCase()
    const isRelevant = KID_KEYWORDS.some(kw => text.includes(kw)) || feed.category === 'safety'

    if (isRelevant) {
      items.push({
        title: clean(title),
        url: link.trim(),
        summary: clean(desc || '').slice(0, 500),
        source: feed.name,
        sourceCredibility: feed.credibility,
        category: feed.category,
        tier: feed.tier,
        publishedAt: date ? new Date(date).toISOString() : new Date().toISOString(),
      })
    }
  }

  return items
}

function extractAtomLink(block) {
  const m = block.match(/<link[^>]*href=["']([^"']+)["'][^>]*\/?>/i)
  return m ? m[1] : null
}

function tag(xml, t) {
  const m = xml.match(new RegExp(`<${t}[^>]*>(?:<!\\[CDATA\\[)?([\\s\\S]*?)(?:\\]\\]>)?</${t}>`, 'i'))
  return m ? m[1].trim() : null
}

function clean(s) {
  return (s || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim()
}

function dedup(stories) {
  const seen = new Map()
  return stories.filter(s => {
    const key = s.title.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 60)
    if (seen.has(key)) {
      const existing = seen.get(key)
      existing.relatedSources = [...(existing.relatedSources || []), { source: s.source, url: s.url }]
      return false
    }
    seen.set(key, s)
    return true
  })
}

function applySafetyGate(stories) {
  return stories.map(s => {
    const safety = quickClassify(s)
    return { ...s, safetyRating: safety.rating, safetyConfidence: safety.confidence, safetyReason: safety.reason }
  })
}

async function scoreWithClaude(stories) {
  const apiKey = process.env.ANTHROPIC_API_KEY
  if (!apiKey) {
    console.log('[INGEST] No ANTHROPIC_API_KEY — using default scores')
    return stories.map(s => ({ ...s, biasScore: 50, relevanceScore: s.sourceCredibility || 50, ageGroups: ['0-12'] }))
  }

  const scored = []
  for (let i = 0; i < stories.length; i += 10) {
    const batch = stories.slice(i, i + 10)
    console.log(`[INGEST] Scoring batch ${Math.floor(i / 10) + 1}/${Math.ceil(stories.length / 10)}`)
    try {
      const res = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
        body: JSON.stringify({
          model: 'claude-haiku-4-5-20251001',
          max_tokens: 2000,
          messages: [{
            role: 'user',
            content: `Score these kids health stories. Return a JSON array with objects containing: biasScore (0-100, 50=neutral), relevanceScore (0-100, higher=more relevant to parents), ageGroups (array of applicable age ranges from "0-2","3-5","6-8","9-12"), actionableInsight (one sentence for parents).

${batch.map((s, j) => `${j + 1}. [${s.source}] ${s.title}\n   ${s.summary.slice(0, 200)}`).join('\n\n')}

Return JSON array only, no other text:`
          }]
        })
      })
      const data = await res.json()
      const text = data.content?.[0]?.text || '[]'
      const scores = JSON.parse(text.match(/\[[\s\S]*\]/)?.[0] || '[]')
      batch.forEach((s, j) => scored.push({ ...s, ...(scores[j] || {}) }))
    } catch (e) {
      console.error(`[INGEST] Scoring error: ${e.message}`)
      scored.push(...batch.map(s => ({ ...s, biasScore: 50, relevanceScore: s.sourceCredibility || 50, ageGroups: ['0-12'] })))
    }
  }
  return scored
}

async function flagForModeration(stories) {
  const flagged = stories.filter(s =>
    s.safetyRating === 'BLOCKED' || (s.safetyRating === 'PG-13' && s.safetyConfidence < 0.8)
  )

  if (flagged.length === 0) return

  try {
    const fs = await import('node:fs/promises')
    const path = await import('node:path')
    const modPath = path.join(process.cwd(), 'data', 'moderation.json')
    let modData
    try {
      modData = JSON.parse(await fs.readFile(modPath, 'utf8'))
    } catch {
      modData = { queue: [], lastUpdated: new Date().toISOString() }
    }

    for (const story of flagged) {
      modData.queue.push({
        id: `mod-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        title: story.title,
        summary: story.summary,
        source: story.source,
        url: story.url,
        safetyRating: story.safetyRating,
        flagReason: story.safetyReason,
        status: 'pending',
        addedAt: new Date().toISOString(),
      })
    }

    modData.lastUpdated = new Date().toISOString()
    await fs.writeFile(modPath, JSON.stringify(modData, null, 2))
    console.log(`[INGEST] Flagged ${flagged.length} articles for moderation`)
  } catch (e) {
    console.error(`[INGEST] Could not write moderation queue: ${e.message}`)
  }
}

async function main() {
  const fs = await import('node:fs/promises')
  const path = await import('node:path')

  // Ensure data directories exist
  const dataDir = path.join(process.cwd(), 'data')
  const digestDir = path.join(dataDir, 'digests')
  await fs.mkdir(digestDir, { recursive: true })

  // Load all sources (default + custom)
  const sources = await loadAllSources()
  console.log(`[INGEST] Fetching from ${sources.length} sources...`)

  // Fetch all feeds concurrently
  const results = await Promise.allSettled(sources.map(fetchFeed))
  const all = results.flatMap(r => r.status === 'fulfilled' ? r.value : [])
  console.log(`[INGEST] Fetched ${all.length} raw stories`)

  // Dedup
  const unique = dedup(all)
  console.log(`[INGEST] ${unique.length} unique stories after dedup`)

  // Safety gate
  const safeStories = applySafetyGate(unique)
  const blocked = safeStories.filter(s => s.safetyRating === 'BLOCKED')
  const publishable = safeStories.filter(s => s.safetyRating !== 'BLOCKED')
  console.log(`[INGEST] ${publishable.length} publishable, ${blocked.length} blocked`)

  // Flag questionable content for moderation
  await flagForModeration(safeStories)

  // Score with Claude AI
  const scored = await scoreWithClaude(publishable)
  scored.sort((a, b) => (b.relevanceScore || 0) - (a.relevanceScore || 0))

  // Save daily data file
  const date = new Date().toISOString().split('T')[0]
  const output = {
    date,
    storyCount: scored.length,
    sources: [...new Set(scored.map(s => s.source))],
    stories: scored,
    blockedCount: blocked.length,
    ingestedAt: new Date().toISOString(),
  }

  const outputPath = path.join(digestDir, `${date}.json`)
  await fs.writeFile(outputPath, JSON.stringify(output, null, 2))
  console.log(`[INGEST] Saved data/digests/${date}.json (${scored.length} stories)`)

  // Print top 5
  console.log('\nTop stories:')
  scored.slice(0, 5).forEach((s, i) => {
    console.log(`  ${i + 1}. [${s.relevanceScore || '?'}] ${s.title} (${s.source}) [${s.safetyRating}]`)
  })
}

main().catch(e => { console.error(e); process.exit(1) })
