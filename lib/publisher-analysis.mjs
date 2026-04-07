/**
 * Publisher Analysis Engine (Ground News Style)
 *
 * When bloggers/journalists submit their site:
 * 1. Crawl their RSS feed
 * 2. Sample 5-10 articles
 * 3. Score for bias, accuracy, credibility
 * 4. Compare against existing sources covering same topics
 * 5. Generate a "Publisher Profile" similar to Ground News source profiles
 */

export const PUBLISHER_TIERS = {
  pending: { label: 'Pending Review', color: '#9E9E9E', canAutoPublish: false },
  verified: { label: 'Verified', color: '#4CAF50', canAutoPublish: true },
  trusted: { label: 'Trusted', color: '#2196F3', canAutoPublish: true },
  expert: { label: 'Expert', color: '#9C27B0', canAutoPublish: true },
  suspended: { label: 'Suspended', color: '#F44336', canAutoPublish: false },
}

export const CREDENTIAL_TYPES = [
  { id: 'md', label: 'Medical Doctor (MD/DO)', verifyVia: 'NPI lookup' },
  { id: 'phd', label: 'PhD in relevant field', verifyVia: 'University verification' },
  { id: 'rd', label: 'Registered Dietitian', verifyVia: 'CDR verification' },
  { id: 'rn', label: 'Registered Nurse', verifyVia: 'State board lookup' },
  { id: 'lcsw', label: 'Licensed Clinical Social Worker', verifyVia: 'State board lookup' },
  { id: 'certified-educator', label: 'Certified Educator', verifyVia: 'State certification' },
  { id: 'lactation-consultant', label: 'IBCLC', verifyVia: 'IBLCE verification' },
  { id: 'journalist', label: 'Professional Journalist', verifyVia: 'Publication history' },
  { id: 'parent-blogger', label: 'Parent Blogger', verifyVia: 'Content review only' },
]

/**
 * Analyze a publisher application.
 * Returns a comprehensive profile for admin review.
 */
export async function analyzePublisher(application) {
  const { siteUrl, rssUrl, credentials, sampleArticles } = application

  // 1. Basic domain analysis
  const domainAnalysis = {
    domain: new URL(siteUrl).hostname,
    hasSSL: siteUrl.startsWith('https'),
    hasRSS: !!rssUrl,
    // In production: check domain age, DA score, backlinks via API
  }

  // 2. Content analysis (from sampled articles)
  const contentAnalysis = sampleArticles ? analyzeContent(sampleArticles) : null

  // 3. Credential check
  const credentialStatus = credentials?.map(c => ({
    type: c,
    verifiable: CREDENTIAL_TYPES.find(ct => ct.id === c)?.verifyVia || 'manual',
    verified: false // set to true after admin verification
  }))

  // 4. Generate recommended tier
  const tier = recommendTier(domainAnalysis, contentAnalysis, credentialStatus)

  return {
    domainAnalysis,
    contentAnalysis,
    credentialStatus,
    recommendedTier: tier,
    needsManualReview: tier === 'pending' || credentials?.includes('md') || credentials?.includes('phd')
  }
}

function analyzeContent(articles) {
  // Simple local analysis — Claude does the deep analysis via the publisher-reviewer agent
  const avgLength = articles.reduce((sum, a) => sum + (a.content?.length || 0), 0) / articles.length
  const hasCitations = articles.filter(a => /\b(study|research|according to|published in)\b/i.test(a.content || '')).length
  const hasDisclaimer = articles.filter(a => /\b(not medical advice|consult your doctor|disclaimer)\b/i.test(a.content || '')).length

  return {
    articleCount: articles.length,
    avgLength: Math.round(avgLength),
    citationRate: hasCitations / articles.length,
    disclaimerRate: hasDisclaimer / articles.length,
    qualitySignals: {
      hasCitations: hasCitations > articles.length * 0.5,
      hasDisclaimers: hasDisclaimer > 0,
      adequateLength: avgLength > 500,
    }
  }
}

function recommendTier(domain, content, credentials) {
  if (!domain.hasSSL || !domain.hasRSS) return 'pending'
  if (!content) return 'pending'

  const hasVerifiedCredential = credentials?.some(c =>
    ['md', 'phd', 'rd', 'rn'].includes(c.type)
  )

  if (hasVerifiedCredential && content.citationRate > 0.7) return 'expert'
  if (content.citationRate > 0.5 && content.qualitySignals.hasDisclaimers) return 'trusted'
  if (content.qualitySignals.adequateLength && content.citationRate > 0.3) return 'verified'
  return 'pending'
}

/**
 * Compare a publisher's coverage against our existing sources.
 * Ground News style: "How does this publisher cover topics vs. established sources?"
 */
export function compareToEstablished(publisherArticles, establishedArticles) {
  // Find topic overlaps
  const publisherTopics = new Set(publisherArticles.flatMap(a => a.categories || []))
  const overlapArticles = establishedArticles.filter(a =>
    (a.categories || []).some(c => publisherTopics.has(c))
  )

  return {
    topicOverlap: publisherTopics.size,
    sharedStories: overlapArticles.length,
    uniqueStories: publisherArticles.length - overlapArticles.length,
    diversityScore: publisherArticles.length > 0
      ? (publisherArticles.length - overlapArticles.length) / publisherArticles.length
      : 0
  }
}
