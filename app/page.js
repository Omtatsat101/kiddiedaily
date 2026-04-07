import Link from 'next/link'

const TRUST_SPECTRUM = [
  { key: 'kids-first', label: 'Kids First', icon: '🛡️', color: 'var(--trust-kids)', desc: 'Safety & wellbeing priority' },
  { key: 'parent-friendly', label: 'Parent Friendly', icon: '👨‍👩‍👧‍👦', color: 'var(--trust-parent)', desc: 'Balanced & actionable' },
  { key: 'research-backed', label: 'Research Backed', icon: '🔬', color: 'var(--trust-research)', desc: 'Clinical evidence' },
]

const TOPICS = [
  { slug: 'vaccines', label: 'Vaccines', icon: '💉' },
  { slug: 'nutrition', label: 'Nutrition', icon: '🥦' },
  { slug: 'mental-health', label: 'Mental Health', icon: '🧠' },
  { slug: 'safety', label: 'Safety & Recalls', icon: '⚠️' },
  { slug: 'development', label: 'Development', icon: '📈' },
  { slug: 'sleep', label: 'Sleep', icon: '😴' },
  { slug: 'alternative', label: 'Ayurveda & Herbal', icon: '🌿' },
  { slug: 'screen-time', label: 'Screen Time', icon: '📱' },
]

const SAMPLE_DIGEST = {
  date: '2026-04-07',
  topStory: {
    title: 'AAP Updates Screen Time Guidelines: Interactive Apps Now Treated Differently',
    summary: 'The American Academy of Pediatrics released updated recommendations distinguishing between passive video consumption and interactive educational apps for children ages 2-8.',
    trust: 'research-backed',
    sources: ['AAP', 'Reuters Health', 'NYT'],
    insight: 'If your child uses educational apps, this is good news — the new guidelines recognize not all screen time is equal.',
  },
  safetyAlert: {
    title: 'FDA Recalls 3 Children\'s Vitamin Brands Over Lead Contamination',
    brands: 'Check your cabinet: BrightKids Gummies, TinyVites Chewables, KiddoHealth Drops',
    trust: 'kids-first',
  },
  wellnessSignal: {
    title: 'New Study Links Vitamin D Levels to Sleep Quality in Children Ages 4-8',
    summary: 'JAMA Pediatrics published findings showing moderate vitamin D supplementation improved sleep onset by an average of 12 minutes.',
    trust: 'research-backed',
    sources: ['JAMA Pediatrics', 'Healthline'],
  },
}

export default function Home() {
  return (
    <main className="min-h-screen">
      {/* NAV */}
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
          <Link href="/topics" className="hover:text-[var(--ink)]">Topics</Link>
          <Link href="/about" className="hover:text-[var(--ink)]">About</Link>
          <Link href="/publishers" className="hover:text-[var(--ink)]">For Publishers</Link>
        </div>
      </nav>

      {/* HERO */}
      <section className="max-w-4xl mx-auto px-6 py-16 text-center">
        <p className="text-xs font-bold tracking-widest uppercase text-[var(--accent)] mb-5">
          Ground News, but for raising healthy kids
        </p>
        <h1 className="text-5xl font-black leading-tight tracking-tight mb-5">
          Kids health news.<br />
          <span className="text-[var(--accent)]">No bias. Multiple sources.</span>
        </h1>
        <p className="text-lg text-[var(--muted)] max-w-xl mx-auto mb-8 leading-relaxed">
          AI-curated health, wellness, and development news from 50+ sources — scored for trust, filtered for safety, personalized to your kids' ages. Combat misinformation with evidence.
        </p>
        <form className="flex gap-3 max-w-md mx-auto mb-4 flex-wrap justify-center" action="/api/subscribe" method="POST">
          <input type="email" name="email" placeholder="your@email.com" required
            className="flex-1 min-w-[220px] px-5 py-3.5 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
          <button type="submit"
            className="px-7 py-3.5 bg-gradient-to-br from-[var(--accent)] to-[var(--accent-dark)] text-white rounded-xl text-base font-extrabold hover:translate-y-[-2px] hover:shadow-lg transition-all">
            Subscribe Free
          </button>
        </form>
        <p className="text-xs text-[var(--muted)]">No spam. Unsubscribe anytime. Choose your kids' ages after signup.</p>
      </section>

      {/* TRUST SPECTRUM */}
      <section className="max-w-4xl mx-auto px-6 pb-12">
        <div className="flex justify-center gap-6 flex-wrap">
          {TRUST_SPECTRUM.map(t => (
            <div key={t.key} className="flex items-center gap-2 px-4 py-2 rounded-full border border-[var(--border)] bg-white text-sm font-bold">
              <span>{t.icon}</span>
              <span style={{ color: t.color }}>{t.label}</span>
            </div>
          ))}
        </div>
        <p className="text-center text-xs text-[var(--muted)] mt-3">
          Every story is scored on a trust spectrum designed for parents — not political left/right.
        </p>
      </section>

      {/* TODAY'S DIGEST PREVIEW */}
      <section className="max-w-4xl mx-auto px-6 pb-16">
        <h2 className="text-2xl font-black mb-2">Today's digest</h2>
        <p className="text-[var(--muted)] mb-6">Here's what this morning's email looks like.</p>

        <div className="space-y-4">
          {/* SAFETY ALERT */}
          <div className="bg-orange-50 border-l-4 border-orange-400 rounded-xl p-5">
            <p className="text-xs font-bold tracking-widest uppercase text-orange-700 mb-1">⚠️ Safety Alert • Kids First</p>
            <h3 className="text-lg font-extrabold mb-1">{SAMPLE_DIGEST.safetyAlert.title}</h3>
            <p className="text-sm text-orange-900/70">{SAMPLE_DIGEST.safetyAlert.brands}</p>
          </div>

          {/* TOP STORY */}
          <div className="bg-white border border-[var(--border)] rounded-xl p-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-bold tracking-widest uppercase text-[var(--trust-research)]">🔬 Top Story • Research Backed</span>
              <span className="text-xs text-[var(--muted)]">• {SAMPLE_DIGEST.topStory.sources.length} sources</span>
            </div>
            <h3 className="text-xl font-extrabold mb-2">{SAMPLE_DIGEST.topStory.title}</h3>
            <p className="text-sm text-[var(--muted)] mb-3">{SAMPLE_DIGEST.topStory.summary}</p>
            <div className="bg-green-50 rounded-lg p-3 text-sm font-semibold text-green-800">
              💡 {SAMPLE_DIGEST.topStory.insight}
            </div>
            <div className="flex gap-2 mt-3">
              {SAMPLE_DIGEST.topStory.sources.map(s => (
                <span key={s} className="text-xs font-bold px-2 py-1 rounded-full bg-blue-50 text-blue-700">{s}</span>
              ))}
            </div>
          </div>

          {/* WELLNESS SIGNAL */}
          <div className="bg-white border border-[var(--border)] rounded-xl p-5">
            <p className="text-xs font-bold tracking-widest uppercase text-[var(--trust-research)] mb-1">🔬 Wellness Signal</p>
            <h3 className="text-lg font-extrabold mb-1">{SAMPLE_DIGEST.wellnessSignal.title}</h3>
            <p className="text-sm text-[var(--muted)]">{SAMPLE_DIGEST.wellnessSignal.summary}</p>
          </div>
        </div>
      </section>

      {/* TOPICS */}
      <section className="max-w-4xl mx-auto px-6 pb-16">
        <h2 className="text-2xl font-black mb-2">Topics we cover</h2>
        <p className="text-[var(--muted)] mb-6">Filter your digest to what matters most for your family.</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {TOPICS.map(t => (
            <Link key={t.slug} href={`/topics/${t.slug}`}
              className="bg-white border border-[var(--border)] rounded-xl p-4 text-center hover:translate-y-[-2px] transition-transform">
              <div className="text-2xl mb-2">{t.icon}</div>
              <div className="text-sm font-bold">{t.label}</div>
            </Link>
          ))}
        </div>
      </section>

      {/* FOR PUBLISHERS */}
      <section className="max-w-4xl mx-auto px-6 pb-16">
        <div className="bg-white border border-[var(--border)] rounded-2xl p-8 text-center">
          <h2 className="text-2xl font-black mb-2">Are you a health writer or journalist?</h2>
          <p className="text-[var(--muted)] mb-6 max-w-lg mx-auto">
            Submit your RSS feed. Our AI analyzes your content for accuracy, bias, and credibility — then features your best work to thousands of parents who trust us.
          </p>
          <Link href="/publishers"
            className="inline-block px-7 py-3.5 border-2 border-[var(--ink)] rounded-xl text-base font-extrabold hover:bg-[var(--ink)] hover:text-white transition-colors">
            Apply as a Publisher
          </Link>
        </div>
      </section>

      {/* BOTTOM CTA */}
      <section className="max-w-4xl mx-auto px-6 pb-16 text-center">
        <h2 className="text-3xl font-black mb-3">Start tomorrow morning.</h2>
        <p className="text-[var(--muted)] mb-6">One email. Multi-source truth. Zero bias.</p>
        <form className="flex gap-3 max-w-md mx-auto flex-wrap justify-center" action="/api/subscribe" method="POST">
          <input type="email" name="email" placeholder="your@email.com" required
            className="flex-1 min-w-[220px] px-5 py-3.5 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
          <button type="submit"
            className="px-7 py-3.5 bg-gradient-to-br from-[var(--accent)] to-[var(--accent-dark)] text-white rounded-xl text-base font-extrabold">
            Subscribe Free
          </button>
        </form>
      </section>

      {/* FOOTER */}
      <footer className="max-w-4xl mx-auto px-6 py-8 text-center text-xs text-[var(--muted)] border-t border-[var(--border)]">
        <p>© 2026 KiddieDaily — A <a href="https://kiddiesketch.com" className="text-[var(--accent)]">KiddieSketch</a> brand</p>
        <p className="mt-1">AI-curated. Multi-source. Evidence-based. No bias.</p>
      </footer>
    </main>
  )
}
