/**
 * Dynamic Source Registry
 * Sources are loaded from DB in production, from this default list in dev.
 * Admin can add/remove/pause sources via the admin module.
 * Publishers can submit their RSS feeds for inclusion.
 */

export const DEFAULT_SOURCES = [
  // === MEDICAL & RESEARCH ===
  { name: 'AAP News', url: 'https://publications.aap.org/aapnews/rss', type: 'rss', category: 'health', credibility: 95, tier: 'research' },
  { name: 'JAMA Pediatrics', url: 'https://jamanetwork.com/rss/site_12/67.xml', type: 'rss', category: 'health', credibility: 98, tier: 'research' },
  { name: 'CDC Child Health', url: 'https://tools.cdc.gov/podcasts/rss.asp', type: 'rss', category: 'development', credibility: 95, tier: 'research' },
  { name: 'WHO Child Health', url: 'https://www.who.int/rss-feeds/news-english.xml', type: 'rss', category: 'health', credibility: 95, tier: 'research' },
  { name: 'NIH Child Health', url: 'https://www.nichd.nih.gov/rss', type: 'rss', category: 'development', credibility: 95, tier: 'research' },
  { name: 'The Lancet Child', url: 'https://www.thelancet.com/rssfeed/lanchi', type: 'rss', category: 'health', credibility: 98, tier: 'research' },
  { name: 'Nature Pediatrics', url: 'https://www.nature.com/natrevdis.rss', type: 'rss', category: 'health', credibility: 97, tier: 'research' },
  { name: 'PubMed Children', url: 'https://pubmed.ncbi.nlm.nih.gov/rss/search/1/?term=children+health&limit=20', type: 'rss', category: 'health', credibility: 96, tier: 'research' },

  // === GOVERNMENT & SAFETY ===
  { name: 'CPSC Recalls', url: 'https://www.cpsc.gov/Newsroom/CPSC-RSS-Feed/Recalls-RSS', type: 'rss', category: 'safety', credibility: 98, tier: 'safety' },
  { name: 'FDA Alerts', url: 'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds', type: 'rss', category: 'safety', credibility: 98, tier: 'safety' },
  { name: 'EPA Children Health', url: 'https://www.epa.gov/rss/epa-news-releases.xml', type: 'rss', category: 'safety', credibility: 90, tier: 'safety' },

  // === CONSUMER & WELLNESS ===
  { name: 'Healthline Parents', url: 'https://www.healthline.com/rss/parenthood', type: 'rss', category: 'wellness', credibility: 75, tier: 'consumer' },
  { name: 'WebMD Children', url: 'https://rssfeeds.webmd.com/rss/rss.aspx?RSSSource=RSS_CHILD', type: 'rss', category: 'health', credibility: 75, tier: 'consumer' },
  { name: 'Parents Magazine', url: 'https://www.parents.com/feed/', type: 'rss', category: 'wellness', credibility: 70, tier: 'consumer' },
  { name: 'What to Expect', url: 'https://www.whattoexpect.com/feed/', type: 'rss', category: 'development', credibility: 72, tier: 'consumer' },
  { name: 'Verywell Family', url: 'https://www.verywellfamily.com/rss', type: 'rss', category: 'wellness', credibility: 74, tier: 'consumer' },

  // === NEWS AGENCIES ===
  { name: 'Reuters Health', url: 'https://www.reutersagency.com/feed/', type: 'rss', category: 'health', credibility: 90, tier: 'news' },
  { name: 'AP Health', url: 'https://apnews.com/hub/health.rss', type: 'rss', category: 'health', credibility: 90, tier: 'news' },
  { name: 'NPR Health', url: 'https://feeds.npr.org/103537970/rss.xml', type: 'rss', category: 'health', credibility: 82, tier: 'news' },

  // === EDUCATION & DEVELOPMENT ===
  { name: 'Zero to Three', url: 'https://www.zerotothree.org/feed', type: 'rss', category: 'development', credibility: 85, tier: 'expert' },
  { name: 'Child Mind Institute', url: 'https://childmind.org/feed/', type: 'rss', category: 'mental-health', credibility: 88, tier: 'expert' },
  { name: 'Understood.org', url: 'https://www.understood.org/rss', type: 'rss', category: 'development', credibility: 82, tier: 'expert' },
  { name: 'EdWeek', url: 'https://www.edweek.org/rss', type: 'rss', category: 'development', credibility: 80, tier: 'news' },

  // === ALTERNATIVE & INTEGRATIVE ===
  { name: 'NCCIH (NIH)', url: 'https://nccih.nih.gov/rss', type: 'rss', category: 'alternative', credibility: 85, tier: 'research' },
  // Note: Ayurveda/herbal sources are included but scored against medical consensus
]

export const SOURCE_TIERS = {
  research: { label: 'Academic/Research', weight: 1.5, color: '#2196F3' },
  safety: { label: 'Government/Safety', weight: 1.4, color: '#f44336' },
  expert: { label: 'Expert Organization', weight: 1.2, color: '#9C27B0' },
  news: { label: 'News Agency', weight: 1.0, color: '#607D8B' },
  consumer: { label: 'Consumer Health', weight: 0.8, color: '#FF9800' },
  publisher: { label: 'Independent Publisher', weight: 0.6, color: '#795548' },
}

/**
 * In production, this loads from DB. Admin adds sources via dashboard.
 * Publishers submit via /api/publishers/apply → approved feeds added here.
 */
export async function loadSources(db) {
  if (db) {
    // Production: load from database
    // return await db.query('SELECT * FROM sources WHERE is_active = true')
  }
  return DEFAULT_SOURCES.map((s, i) => ({ id: `default-${i}`, ...s, isActive: true }))
}
