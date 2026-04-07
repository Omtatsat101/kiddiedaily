/**
 * Content Safety Gate
 *
 * Every article passes through this before publishing.
 * Hard filter: PG-13 and below only.
 * Parents set per-child age restrictions.
 *
 * Ratings:
 *   G      — All ages, any child can see
 *   PG     — With parent guidance (vaccine discussions, allergy management)
 *   PG-13  — Pre-teen context (puberty, social media, teen mental health)
 *   BLOCKED — Never shown (violence, graphic medical, adult) → admin review
 */

export const RATINGS = {
  G: { label: 'G — General Audience', minAge: 0, color: '#4CAF50', description: 'Safe for all ages' },
  PG: { label: 'PG — Parental Guidance', minAge: 3, color: '#FF9800', description: 'Best with parent context' },
  'PG-13': { label: 'PG-13 — Teen Context', minAge: 10, color: '#F44336', description: 'Pre-teen and up' },
  BLOCKED: { label: 'Blocked', minAge: 99, color: '#9E9E9E', description: 'Requires admin review' }
}

// Words/topics that trigger safety review
const BLOCK_SIGNALS = [
  'murder', 'suicide method', 'graphic injury', 'sexual abuse', 'explicit',
  'gore', 'torture', 'self-harm method', 'drug use instruction', 'weapon how-to'
]

const PG13_SIGNALS = [
  'puberty', 'menstruation', 'teen depression', 'eating disorder', 'body image',
  'social media addiction', 'vaping', 'alcohol', 'dating', 'consent education',
  'self-harm awareness', 'suicide prevention', 'substance abuse prevention'
]

const PG_SIGNALS = [
  'vaccine', 'vaccination', 'immunization', 'side effect', 'allergy', 'anaphylaxis',
  'mental health', 'anxiety', 'adhd medication', 'therapy', 'diagnosis',
  'surgery', 'hospital', 'emergency', 'chronic illness', 'death of pet'
]

/**
 * Quick local classification before sending to Claude for confirmation.
 * Returns preliminary rating and confidence.
 */
export function quickClassify(article) {
  const text = `${article.title} ${article.summary}`.toLowerCase()

  // Hard blocks — never auto-approve
  if (BLOCK_SIGNALS.some(s => text.includes(s))) {
    return { rating: 'BLOCKED', confidence: 0.95, reason: 'Contains blocked content signals' }
  }

  // PG-13 signals
  if (PG13_SIGNALS.some(s => text.includes(s))) {
    return { rating: 'PG-13', confidence: 0.7, reason: 'Contains teen-context topics' }
  }

  // PG signals
  if (PG_SIGNALS.some(s => text.includes(s))) {
    return { rating: 'PG', confidence: 0.7, reason: 'Contains topics needing parent guidance' }
  }

  // Default: G-rated
  return { rating: 'G', confidence: 0.6, reason: 'No elevated content signals detected' }
}

/**
 * Full Claude-powered safety classification.
 * Used for articles where quickClassify has low confidence,
 * or for all publisher-submitted content.
 */
export async function classifyWithAI(article, apiKey) {
  if (!apiKey) return quickClassify(article)

  const prompt = `Classify this kids health article for content safety. Return JSON only.

Title: ${article.title}
Summary: ${article.summary?.slice(0, 500)}
Source: ${article.source}

Ratings:
- G: Safe for all ages (activity ideas, general nutrition, milestones)
- PG: Needs parent context (vaccines, allergies, mental health basics, medical procedures)
- PG-13: Pre-teen context ok (puberty, social media effects, teen mental health, substance awareness)
- BLOCKED: Never show to children (graphic content, violence, explicit, self-harm methods)

Return: {"rating": "G|PG|PG-13|BLOCKED", "reason": "brief explanation", "ageGroups": ["0-2","3-5","6-8","9-12"], "parentNote": "optional note to show parents about why this rating"}`

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 300,
        messages: [{ role: 'user', content: prompt }]
      })
    })
    const data = await res.json()
    const text = data.content?.[0]?.text || '{}'
    return JSON.parse(text.match(/\{[\s\S]*\}/)?.[0] || '{}')
  } catch {
    return quickClassify(article) // fallback to local
  }
}

/**
 * Filter articles for a subscriber's child profile.
 * Returns only articles that match the child's age and parent's max rating.
 */
export function filterForChild(articles, child) {
  const maxRating = child.maxRating || 'PG'
  const allowedRatings = getAllowedRatings(maxRating)
  const ageGroup = getAgeGroup(child.age)

  return articles.filter(a =>
    allowedRatings.includes(a.safetyRating) &&
    (a.ageGroups?.includes(ageGroup) || a.ageGroups?.includes('0-12'))
  )
}

function getAllowedRatings(maxRating) {
  const order = ['G', 'PG', 'PG-13']
  const idx = order.indexOf(maxRating)
  return idx >= 0 ? order.slice(0, idx + 1) : ['G']
}

function getAgeGroup(age) {
  if (age <= 2) return '0-2'
  if (age <= 5) return '3-5'
  if (age <= 8) return '6-8'
  if (age <= 12) return '9-12'
  return '13+'
}
