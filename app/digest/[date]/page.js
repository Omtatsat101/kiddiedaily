import Link from 'next/link'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { notFound } from 'next/navigation'

const TRUST_DISPLAY = {
  KIDS_FIRST: { label: 'Kids First', icon: '🛡️', color: 'text-green-700', bg: 'bg-green-50', border: 'border-green-200' },
  PARENT_FRIENDLY: { label: 'Parent Friendly', icon: '👨‍👩‍👧‍👦', color: 'text-orange-700', bg: 'bg-orange-50', border: 'border-orange-200' },
  RESEARCH_BACKED: { label: 'Research Backed', icon: '🔬', color: 'text-blue-700', bg: 'bg-blue-50', border: 'border-blue-200' },
}

async function getDigest(date) {
  try {
    const digestPath = join(process.cwd(), 'data', 'digests', `${date}-digest.json`)
    return JSON.parse(await readFile(digestPath, 'utf8'))
  } catch {
    return null
  }
}

export async function generateMetadata({ params }) {
  const { date } = await params
  const digest = await getDigest(date)
  return {
    title: digest ? `${digest.subject} — KiddieDaily` : `Digest ${date} — KiddieDaily`,
    description: digest?.topStory?.summary?.slice(0, 155) || `KiddieDaily digest for ${date}`,
  }
}

export default async function DigestPage({ params }) {
  const { date } = await params
  const digest = await getDigest(date)

  if (!digest) {
    return (
      <main className="min-h-screen">
        <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
          <Link href="/" className="text-2xl font-black tracking-tight">
            Kiddie<span className="text-[var(--accent)]">Daily</span>
          </Link>
          <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
            <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
            <Link href="/" className="hover:text-[var(--ink)]">Home</Link>
          </div>
        </nav>
        <section className="max-w-4xl mx-auto px-6 py-16 text-center">
          <h1 className="text-3xl font-black mb-4">No digest for {date}</h1>
          <p className="text-[var(--muted)] mb-6">This digest hasn't been generated yet. Run the pipeline:</p>
          <code className="block bg-white border border-[var(--border)] rounded-xl p-4 text-sm max-w-md mx-auto mb-6">
            npm run ingest && npm run digest -- --date {date}
          </code>
          <Link href="/archive" className="text-[var(--accent)] font-bold text-sm">Browse available digests</Link>
        </section>
      </main>
    )
  }

  const { topStory, safetyAlert, wellnessSignal, bySpectrum, allStories, trustSpectrum } = digest

  return (
    <main className="min-h-screen">
      {/* NAV */}
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
          <Link href="/preferences" className="hover:text-[var(--ink)]">Preferences</Link>
          <Link href="/about" className="hover:text-[var(--ink)]">About</Link>
        </div>
      </nav>

      <section className="max-w-4xl mx-auto px-6 py-8">
        {/* HEADER */}
        <div className="text-center mb-8">
          <p className="text-xs font-bold tracking-widest uppercase text-[var(--accent)] mb-2">
            Daily Digest
          </p>
          <h1 className="text-3xl font-black mb-2">{date}</h1>
          <p className="text-[var(--muted)] text-sm">
            {digest.totalStories} stories from {digest.totalSources} sources
          </p>
        </div>

        {/* TRUST SPECTRUM BAR */}
        <div className="flex justify-center gap-4 flex-wrap mb-8">
          {Object.entries(TRUST_DISPLAY).map(([key, t]) => {
            const count = bySpectrum?.[key]?.length || 0
            return (
              <div key={key} className={`flex items-center gap-2 px-4 py-2 rounded-full border ${t.border} ${t.bg} text-sm font-bold`}>
                <span>{t.icon}</span>
                <span className={t.color}>{t.label}</span>
                <span className="text-xs text-gray-500">({count})</span>
              </div>
            )
          })}
        </div>

        {/* SAFETY ALERT */}
        {safetyAlert && (
          <div className="bg-orange-50 border-l-4 border-orange-400 rounded-xl p-6 mb-6">
            <p className="text-xs font-bold tracking-widest uppercase text-orange-700 mb-2">
              ⚠️ Safety Alert
            </p>
            <h2 className="text-xl font-extrabold mb-2">{safetyAlert.title}</h2>
            <p className="text-sm text-orange-900/70 mb-3">{safetyAlert.summary}</p>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold px-2 py-1 rounded-full bg-orange-100 text-orange-800">
                {safetyAlert.source}
              </span>
              {safetyAlert.relatedSources?.map(rs => (
                <span key={rs.source} className="text-xs font-bold px-2 py-1 rounded-full bg-orange-100/50 text-orange-700">
                  {rs.source}
                </span>
              ))}
              <span className="text-xs text-orange-600">Credibility: {safetyAlert.sourceCredibility}/100</span>
            </div>
            {safetyAlert.actionableInsight && (
              <div className="mt-3 bg-white/50 rounded-lg p-3 text-sm font-semibold text-orange-800">
                💡 {safetyAlert.actionableInsight}
              </div>
            )}
          </div>
        )}

        {/* TOP STORY */}
        {topStory && (
          <div className="bg-white border border-[var(--border)] rounded-xl p-6 mb-6">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold tracking-widest uppercase text-[var(--trust-research)]">
                {topStory.trustIcon || '📰'} Top Story
                {topStory.trustLabel && ` \u2022 ${topStory.trustLabel}`}
              </span>
              {topStory.relatedSources && (
                <span className="text-xs text-[var(--muted)]">
                  \u2022 {1 + topStory.relatedSources.length} sources
                </span>
              )}
            </div>
            <h2 className="text-2xl font-extrabold mb-3">{topStory.title}</h2>
            <p className="text-[var(--muted)] mb-4 leading-relaxed">{topStory.summary}</p>
            {topStory.actionableInsight && (
              <div className="bg-green-50 rounded-lg p-4 text-sm font-semibold text-green-800 mb-4">
                💡 {topStory.actionableInsight}
              </div>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700">
                {topStory.source}
              </span>
              {topStory.relatedSources?.map(rs => (
                <span key={rs.source} className="text-xs font-bold px-2.5 py-1 rounded-full bg-gray-100 text-gray-600">
                  {rs.source}
                </span>
              ))}
              {topStory.ageGroups && (
                <span className="text-xs text-[var(--muted)] ml-2">Ages: {
                  Array.isArray(topStory.ageGroups) ? topStory.ageGroups.join(', ') : topStory.ageGroups
                }</span>
              )}
            </div>
          </div>
        )}

        {/* WELLNESS SIGNAL */}
        {wellnessSignal && (
          <div className="bg-white border border-[var(--border)] rounded-xl p-6 mb-8">
            <p className="text-xs font-bold tracking-widest uppercase text-[var(--trust-parent)] mb-2">
              {wellnessSignal.trustIcon || '💚'} Wellness Signal
            </p>
            <h3 className="text-lg font-extrabold mb-2">{wellnessSignal.title}</h3>
            <p className="text-sm text-[var(--muted)] mb-3">{wellnessSignal.summary}</p>
            {wellnessSignal.actionableInsight && (
              <div className="bg-blue-50 rounded-lg p-3 text-sm font-semibold text-blue-800">
                💡 {wellnessSignal.actionableInsight}
              </div>
            )}
            <div className="flex items-center gap-2 mt-3">
              <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700">
                {wellnessSignal.source}
              </span>
            </div>
          </div>
        )}

        {/* TRUST SPECTRUM SECTIONS */}
        {bySpectrum && Object.entries(bySpectrum).map(([trustKey, stories]) => {
          if (!stories || stories.length === 0) return null
          const display = TRUST_DISPLAY[trustKey] || { label: trustKey, icon: '📰', color: 'text-gray-700', bg: 'bg-gray-50', border: 'border-gray-200' }

          return (
            <div key={trustKey} className="mb-8">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-lg">{display.icon}</span>
                <h2 className="text-xl font-black">{display.label}</h2>
                <span className="text-xs text-[var(--muted)]">({stories.length} stories)</span>
              </div>
              <div className="space-y-3">
                {stories.map((story, idx) => (
                  <div key={idx} className={`bg-white border border-[var(--border)] rounded-xl p-5`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${display.bg} ${display.color}`}>
                        {story.category}
                      </span>
                      <span className="text-xs text-[var(--muted)]">{story.source}</span>
                      {story.sourceCredibility && (
                        <span className="text-xs text-[var(--muted)]">Cred: {story.sourceCredibility}</span>
                      )}
                    </div>
                    <h3 className="font-bold mb-1">{story.title}</h3>
                    <p className="text-sm text-[var(--muted)] mb-2">{story.summary?.slice(0, 250)}</p>
                    {story.actionableInsight && (
                      <p className="text-xs font-semibold text-green-700 bg-green-50 rounded-lg px-3 py-2 mb-2">
                        💡 {story.actionableInsight}
                      </p>
                    )}
                    <div className="flex items-center gap-2 flex-wrap">
                      {story.url && (
                        <a href={story.url} target="_blank" rel="noopener noreferrer"
                          className="text-xs text-[var(--accent)] font-bold hover:underline">
                          Read original
                        </a>
                      )}
                      {story.relatedSources?.length > 0 && (
                        <span className="text-xs text-[var(--muted)]">
                          + {story.relatedSources.length} more source{story.relatedSources.length > 1 ? 's' : ''}
                        </span>
                      )}
                      {story.ageGroups && (
                        <span className="text-xs text-[var(--muted)]">
                          Ages: {Array.isArray(story.ageGroups) ? story.ageGroups.join(', ') : story.ageGroups}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )
        })}

        {/* ALL REMAINING STORIES */}
        {allStories && allStories.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl font-black mb-4">All Stories</h2>
            <div className="space-y-2">
              {allStories.map((story, idx) => (
                <div key={idx} className="bg-white border border-[var(--border)] rounded-lg p-4 flex items-start gap-3">
                  <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 flex-shrink-0 mt-0.5">
                    {story.trust?.replace('_', ' ') || 'unscored'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-bold">{story.title}</h4>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-[var(--muted)]">{story.source}</span>
                      <span className="text-xs text-[var(--muted)]">{story.category}</span>
                      {story.url && (
                        <a href={story.url} target="_blank" rel="noopener noreferrer"
                          className="text-xs text-[var(--accent)] font-semibold hover:underline">
                          Link
                        </a>
                      )}
                    </div>
                  </div>
                  {story.relevanceScore && (
                    <span className="text-xs font-bold text-[var(--muted)] flex-shrink-0">{story.relevanceScore}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* CTA */}
        <div className="text-center py-8 border-t border-[var(--border)]">
          <p className="text-[var(--muted)] text-sm mb-4">Get this digest in your inbox every morning.</p>
          <Link href="/"
            className="inline-block px-7 py-3.5 bg-gradient-to-br from-[var(--accent)] to-[var(--accent-dark)] text-white rounded-xl text-base font-extrabold hover:translate-y-[-2px] hover:shadow-lg transition-all">
            Subscribe Free
          </Link>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="max-w-4xl mx-auto px-6 py-8 text-center text-xs text-[var(--muted)] border-t border-[var(--border)]">
        <p>KiddieDaily -- A <a href="https://kiddiesketch.com" className="text-[var(--accent)]">KiddieSketch</a> brand</p>
        <p className="mt-1">AI-curated. Multi-source. Evidence-based. No bias.</p>
      </footer>
    </main>
  )
}
