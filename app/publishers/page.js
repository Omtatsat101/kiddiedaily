import Link from 'next/link'

const TIERS = [
  { name: 'Pending', color: 'bg-gray-100 text-gray-700', desc: 'Just applied — content under review' },
  { name: 'Verified', color: 'bg-green-50 text-green-700', desc: 'Approved — content auto-ingests with scoring' },
  { name: 'Trusted', color: 'bg-blue-50 text-blue-700', desc: 'High accuracy — priority placement in digests' },
  { name: 'Expert', color: 'bg-purple-50 text-purple-700', desc: 'Verified MD/PhD/RD — expert badge on articles' },
]

const CREDENTIALS = [
  'Medical Doctor (MD/DO)', 'PhD in relevant field', 'Registered Dietitian (RD)',
  'Registered Nurse (RN)', 'Licensed Clinical Social Worker', 'Certified Educator',
  'IBCLC (Lactation Consultant)', 'Professional Journalist', 'Parent Blogger'
]

export const metadata = {
  title: 'For Publishers — KiddieDaily',
  description: 'Submit your health content to KiddieDaily. Get AI-scored, reach parents, build your credibility.',
}

export default function PublishersPage() {
  return (
    <main className="min-h-screen">
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
          <Link href="/topics" className="hover:text-[var(--ink)]">Topics</Link>
          <Link href="/publishers" className="text-[var(--ink)]">For Publishers</Link>
        </div>
      </nav>

      <section className="max-w-4xl mx-auto px-6 py-12">
        <h1 className="text-3xl font-black mb-2">For Publishers</h1>
        <p className="text-[var(--muted)] mb-8 max-w-2xl">
          KiddieDaily is open to bloggers, journalists, researchers, and health professionals.
          Submit your RSS feed — our AI analyzes your content for accuracy, bias, and credibility,
          then features your best work to thousands of parents.
        </p>

        {/* TIERS */}
        <h2 className="text-xl font-black mb-4">Publisher tiers</h2>
        <div className="grid sm:grid-cols-2 gap-3 mb-12">
          {TIERS.map(t => (
            <div key={t.name} className="bg-white border border-[var(--border)] rounded-xl p-5">
              <span className={`inline-block px-3 py-1 rounded-full text-xs font-bold ${t.color} mb-2`}>{t.name}</span>
              <p className="text-sm text-[var(--muted)]">{t.desc}</p>
            </div>
          ))}
        </div>

        {/* HOW IT WORKS */}
        <h2 className="text-xl font-black mb-4">How it works</h2>
        <div className="space-y-3 mb-12">
          {[
            ['Submit your RSS feed', 'We crawl your recent articles and run them through our AI analysis pipeline.'],
            ['AI scores your content', 'Bias detection, factual accuracy, citation rate, credential verification, source comparison.'],
            ['Get your Publisher Profile', 'Like a Ground News source profile — see how your content compares to established sources.'],
            ['Articles auto-ingest', 'Once approved, your new articles are automatically scored and included in daily digests.'],
          ].map(([title, desc], i) => (
            <div key={i} className="bg-white border border-[var(--border)] rounded-xl p-5 flex gap-4">
              <div className="w-8 h-8 rounded-full bg-[var(--accent)]/10 text-[var(--accent)] flex items-center justify-center text-sm font-black flex-shrink-0">
                {i + 1}
              </div>
              <div>
                <h3 className="font-bold">{title}</h3>
                <p className="text-sm text-[var(--muted)]">{desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* APPLICATION FORM */}
        <div className="bg-white border border-[var(--border)] rounded-2xl p-8">
          <h2 className="text-xl font-black mb-4">Apply to be a publisher</h2>
          <form className="space-y-5" action="/api/publishers/apply" method="POST">
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Your name</label>
              <input type="text" name="name" required className="w-full px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Email</label>
              <input type="email" name="email" required className="w-full px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Website URL</label>
              <input type="url" name="siteUrl" required placeholder="https://" className="w-full px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">RSS feed URL (if available)</label>
              <input type="url" name="rssUrl" placeholder="https://yourblog.com/feed" className="w-full px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]" />
            </div>
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Credentials (select all that apply)</label>
              <div className="flex flex-wrap gap-2">
                {CREDENTIALS.map(c => (
                  <label key={c} className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--border)] text-sm font-semibold cursor-pointer hover:bg-gray-50">
                    <input type="checkbox" name="credentials" value={c} className="accent-[var(--accent)]" />
                    {c}
                  </label>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Tell us about your work</label>
              <textarea name="bio" rows={4} className="w-full px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)] resize-none" placeholder="What topics do you cover? Who is your audience?" />
            </div>
            <button type="submit"
              className="px-7 py-3.5 bg-gradient-to-br from-[var(--accent)] to-[var(--accent-dark)] text-white rounded-xl text-base font-extrabold hover:translate-y-[-2px] hover:shadow-lg transition-all">
              Submit Application
            </button>
          </form>
        </div>
      </section>
    </main>
  )
}
