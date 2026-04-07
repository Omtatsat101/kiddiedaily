import Link from 'next/link'

const SAMPLE_DIGESTS = [
  { date: '2026-04-07', title: 'AAP Screen Time Update + FDA Vitamin Recall', stories: 12, sources: 8, topTrust: 'research-backed' },
  { date: '2026-04-06', title: 'Outdoor Play Reduces ADHD Symptoms by 30%', stories: 9, sources: 6, topTrust: 'research-backed' },
  { date: '2026-04-05', title: 'WHO Updates Child Nutrition Guidelines', stories: 14, sources: 11, topTrust: 'kids-first' },
  { date: '2026-04-04', title: 'New Autism Screening Recommendations for Age 2', stories: 8, sources: 5, topTrust: 'research-backed' },
  { date: '2026-04-03', title: 'CPSC Recalls Popular Highchair Brand', stories: 6, sources: 4, topTrust: 'kids-first' },
  { date: '2026-04-02', title: 'Ashwagandha for Kids: What the Evidence Says', stories: 11, sources: 7, topTrust: 'parent-friendly' },
  { date: '2026-04-01', title: 'Spring Allergy Season: Updated Treatment Guidelines', stories: 10, sources: 8, topTrust: 'parent-friendly' },
]

const TRUST_COLORS = {
  'kids-first': { bg: 'bg-green-50', text: 'text-green-700', label: '🛡️ Kids First' },
  'parent-friendly': { bg: 'bg-orange-50', text: 'text-orange-700', label: '👨‍👩‍👧‍👦 Parent Friendly' },
  'research-backed': { bg: 'bg-blue-50', text: 'text-blue-700', label: '🔬 Research Backed' },
}

export const metadata = {
  title: 'Archive — KiddieDaily',
  description: 'Browse past daily digests of AI-curated kids health and wellness news.',
}

export default function ArchivePage() {
  return (
    <main className="min-h-screen">
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="text-[var(--ink)]">Archive</Link>
          <Link href="/topics" className="hover:text-[var(--ink)]">Topics</Link>
          <Link href="/about" className="hover:text-[var(--ink)]">About</Link>
        </div>
      </nav>

      <section className="max-w-4xl mx-auto px-6 py-12">
        <h1 className="text-3xl font-black mb-2">Digest Archive</h1>
        <p className="text-[var(--muted)] mb-8">Every issue stays free. Browse, search, and share.</p>

        <div className="space-y-3">
          {SAMPLE_DIGESTS.map(d => {
            const trust = TRUST_COLORS[d.topTrust]
            return (
              <Link key={d.date} href={`/archive/${d.date}`}
                className="block bg-white border border-[var(--border)] rounded-xl p-5 hover:translate-y-[-1px] transition-transform">
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div>
                    <p className="text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-1">{d.date}</p>
                    <h2 className="text-lg font-extrabold">{d.title}</h2>
                  </div>
                  <div className="flex items-center gap-3 text-xs font-bold">
                    <span className={`px-2.5 py-1 rounded-full ${trust.bg} ${trust.text}`}>{trust.label}</span>
                    <span className="text-[var(--muted)]">{d.stories} stories</span>
                    <span className="text-[var(--muted)]">{d.sources} sources</span>
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      </section>
    </main>
  )
}
