# KiddieDaily Platform Architecture

## Core Concept
Ground News for kids health & wellness — but open to publishers, with content safety gates and AI agents running operations.

## Platform Layers

### 1. Content Ingestion Engine
- **Built-in feeds**: 50+ RSS/API sources (medical journals, news, gov agencies)
- **Dynamic sources**: Admin adds new APIs/feeds via dashboard (no code deploy)
- **Publisher submissions**: Bloggers/journalists submit their site URL → auto-crawl RSS
- **Academic crawl**: PubMed, Google Scholar, JAMA, Lancet, Nature Pediatrics
- **Social signals**: Track trending kids health topics on Reddit, X, parent forums

### 2. AI Analysis Pipeline (Ground News Style)
Every article goes through:

```
Ingest → Safety Gate → Bias Score → Trust Classify → Multi-Source Link → Age Tag → Publish
```

**Safety Gate** (hard filter):
- PG-13 and below ONLY — anything R-rated or violent is auto-rejected
- Claude classifies: G (all ages) / PG (parental guidance) / PG-13 (teen context ok)
- Parents set age restrictions per child profile (0-2, 3-5, 6-8, 9-12, 13+)
- Content that fails safety gate goes to admin review queue, never auto-publishes

**Bias & Trust Analysis** (Ground News style):
- How many sources cover this story? (coverage score)
- Trust spectrum: Kids First / Parent Friendly / Research Backed
- Source credibility rating (0-100)
- Factual vs opinion classification
- Claim verification against medical consensus (vaccines, nutrition, supplements)
- "Blind spot" detection — stories only one type of source covers

**Publisher Analysis** (for blogger/journalist submissions):
- Domain authority score
- Historical accuracy rating (built over time)
- Bias pattern detection
- Credential verification (MD, RD, certified educator, etc.)
- Content quality score

### 3. Content Rating System

| Rating | Audience | Examples |
|--------|----------|---------|
| **G** | All ages, any child can see | Activity ideas, general nutrition, milestone guides |
| **PG** | With parent present/guidance | Vaccine discussions, allergy management, mental health basics |
| **PG-13** | Pre-teen appropriate context | Puberty, social media effects, teen mental health, substance awareness |
| **BLOCKED** | Never shown to children | Violence, graphic medical content, adult topics — admin review only |

Parents configure per-child:
- Child age → auto-restricts to appropriate rating
- Topic blockers (e.g., hide vaccine content if parent requests)
- Source preferences (only Research Backed, or include Parent Friendly too)

### 4. Admin Module

**Source Management:**
- Add/remove/pause RSS feeds, APIs, and custom scrapers
- Configure crawl frequency per source
- Set source credibility baseline
- API key vault for paid sources (PubMed, news APIs)
- Webhook endpoints for real-time feed push

**AI Agent Management:**
- Create and configure AI agents for specific tasks:
  - Content Moderator Agent — reviews flagged content
  - Digest Builder Agent — generates daily/weekly digests
  - Publisher Reviewer Agent — evaluates new publisher applications
  - Trend Spotter Agent — identifies emerging health topics
  - Fact Checker Agent — verifies medical claims against consensus
- Each agent runs on Claude Haiku (cost-efficient) with defined prompts
- Agent activity logs and performance metrics
- Override/approve agent decisions

**Publisher Management:**
- Review applications from bloggers/journalists
- Credential verification workflow
- Content quality monitoring per publisher
- Revenue share / featured placement controls
- Suspend/ban publishers who violate guidelines

**Tech Support:**
- API health dashboard (which feeds are down?)
- Ingestion pipeline metrics
- Email delivery stats (Resend dashboard)
- Subscriber growth and engagement analytics
- Error logs and alert routing

### 5. Publisher Portal (Blogger/Journalist Signup)

Publishers can:
- Submit their site URL for inclusion
- See their content's trust spectrum ratings
- View reader engagement metrics on their articles
- Get AI-powered suggestions to improve credibility
- Access a "Publisher Dashboard" showing:
  - How their articles are rated vs. similar sources
  - Which stories of theirs got multi-source coverage
  - Reader trust score over time
  - Content improvement suggestions

Publisher tiers:
- **Pending** — just signed up, content in review queue
- **Verified** — approved, content auto-ingests with normal scoring
- **Trusted** — high historical accuracy, content gets priority placement
- **Expert** — verified credentials (MD, PhD), articles tagged with credential badge

### 6. Reader Features

- **Personalized digest** — filtered by child age, topics, trust preferences
- **"Coverage Map"** — Ground News style: see how many sources cover a story
- **"Blind Spot Alerts"** — stories only one type of source reports on
- **Bookmark & share** — save articles, share with co-parent
- **Ask a question** — AI agent answers parent questions with cited sources
- **Community notes** — parents can add context (like X Community Notes)

## Data Model

```
Source {
  id, name, url, type (rss|api|scraper|publisher),
  credibility: 0-100,
  biasPattern: string,
  crawlFrequency: string (cron),
  apiKey?: string,
  isActive: boolean,
  addedBy: userId,
  publisherId?: publisherId
}

Article {
  id, title, summary, fullText?, url, sourceId,
  publishedAt, ingestedAt, processedAt,
  safetyRating: "G" | "PG" | "PG-13" | "BLOCKED",
  trustCategory: "KIDS_FIRST" | "PARENT_FRIENDLY" | "RESEARCH_BACKED",
  biasScore: 0-100,
  credibilityScore: 0-100,
  relevanceScore: 0-100,
  categories: string[],
  ageGroups: string[],
  claims: Claim[],
  relatedArticles: articleId[],
  coverageCount: number,
  isFactual: boolean,
  aiSummary: string,
  actionableInsight: string,
  moderationStatus: "auto_approved" | "pending_review" | "approved" | "rejected"
}

Claim {
  id, articleId, claimText,
  consensusStatus: "supported" | "contested" | "debunked" | "emerging",
  evidence: { source, url, summary }[],
  verifiedBy: agentId | adminId
}

Publisher {
  id, name, email, siteUrl, rssUrl?,
  credentials: string[],
  tier: "pending" | "verified" | "trusted" | "expert",
  credentialProof: string[],
  historicalAccuracy: 0-100,
  contentQuality: 0-100,
  articleCount: number,
  appliedAt, approvedAt?,
  bio: string
}

Subscriber {
  id, email, name?,
  children: { name?, age, ageGroup }[],
  maxRating: "G" | "PG" | "PG-13",
  topics: string[],
  trustPreferences: string[],
  frequency: "daily" | "weekly",
  subscribedAt
}

Agent {
  id, name, role, model, systemPrompt,
  schedule?: string (cron),
  isActive: boolean,
  lastRunAt, runCount, errorCount
}
```

## API Routes

### Public
- `GET /api/digest/today` — today's digest
- `GET /api/digest/[date]` — specific date's digest
- `GET /api/articles?topic=&age=&trust=` — search/filter articles
- `GET /api/article/[id]` — single article with coverage map
- `POST /api/subscribe` — email signup
- `GET /api/topics` — available topic categories

### Publisher Portal
- `POST /api/publishers/apply` — submit application
- `GET /api/publishers/me` — dashboard data
- `GET /api/publishers/me/articles` — their articles + ratings
- `PUT /api/publishers/me/profile` — update profile

### Admin
- `GET /api/admin/sources` — all sources
- `POST /api/admin/sources` — add new source
- `PUT /api/admin/sources/[id]` — update source config
- `GET /api/admin/agents` — all AI agents
- `POST /api/admin/agents` — create agent
- `POST /api/admin/agents/[id]/run` — trigger agent manually
- `GET /api/admin/moderation` — content review queue
- `POST /api/admin/moderation/[id]` — approve/reject
- `GET /api/admin/publishers` — publisher applications
- `POST /api/admin/publishers/[id]/approve` — approve publisher
- `GET /api/admin/metrics` — platform health dashboard

## Tech Stack

- **Next.js 15** — Full-stack web app
- **PostgreSQL** (Neon/Supabase) — Primary database
- **Claude Haiku** — AI scoring, safety gates, analysis (cost: ~$0.001/article)
- **Claude Sonnet** — Complex analysis, claim verification (cost: ~$0.01/article)
- **Resend** — Email delivery
- **Vercel** — Hosting + cron
- **Upstash Redis** — Rate limiting, caching hot articles
