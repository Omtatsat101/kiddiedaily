import Link from 'next/link'

export const metadata = {
  title: 'About — KiddieDaily',
  description: 'Our mission: combat misinformation, balance traditional medicine with evidence, and give parents the truth about kids health.',
}

export default function AboutPage() {
  return (
    <main className="min-h-screen">
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
          <Link href="/about" className="text-[var(--ink)]">About</Link>
        </div>
      </nav>

      <article className="max-w-3xl mx-auto px-6 py-12 prose prose-lg">
        <h1 className="text-3xl font-black mb-6">Why KiddieDaily exists</h1>

        <div className="space-y-6 text-[var(--muted)] leading-relaxed">
          <p className="text-lg">
            Parents are drowning in health misinformation. Anti-vaccine fear campaigns share the same feed as legitimate medical research. Ayurvedic supplement claims go unchallenged next to peer-reviewed studies. And when you Google "is [thing] safe for kids?" — you get 10 contradictory answers from 10 sources with 10 different agendas.
          </p>

          <p>
            <strong className="text-[var(--ink)]">KiddieDaily exists to fix this.</strong>
          </p>

          <p>
            We built KiddieDaily because we believe parents deserve the same tools that informed citizens get from platforms like Ground News — multi-source coverage, bias scoring, and transparency about where information comes from.
          </p>

          <h2 className="text-xl font-black text-[var(--ink)] mt-8">Our approach</h2>

          <p>
            Every day, our AI ingests kids health news from 50+ sources — medical journals (JAMA, AAP, Lancet), government agencies (CDC, FDA, WHO), consumer health sites (Healthline, WebMD), news agencies (Reuters, AP), and independent publishers.
          </p>

          <p>
            Each article is scored on our <strong className="text-[var(--ink)]">Trust Spectrum</strong> — not political left/right (because kids health isn't politics), but:
          </p>

          <ul className="space-y-2">
            <li><strong style={{color: 'var(--trust-kids)'}}>🛡️ Kids First</strong> — Safety alerts, recalls, urgent health. When in doubt, protect the child.</li>
            <li><strong style={{color: 'var(--trust-parent)'}}>👨‍👩‍👧‍👦 Parent Friendly</strong> — Balanced, practical, actionable. What you can actually do today.</li>
            <li><strong style={{color: 'var(--trust-research)'}}>🔬 Research Backed</strong> — Clinical evidence, peer-reviewed studies. The science behind the headlines.</li>
          </ul>

          <h2 className="text-xl font-black text-[var(--ink)] mt-8">On vaccines</h2>
          <p>
            We follow the evidence. The overwhelming scientific consensus — supported by the AAP, WHO, CDC, and decades of research — is that childhood vaccines are safe and effective. We present this evidence clearly. We also explain <em>why</em> vaccine hesitancy exists, because understanding the fear is the first step to addressing it. We never platform anti-vaccine misinformation as equivalent to peer-reviewed evidence.
          </p>

          <h2 className="text-xl font-black text-[var(--ink)] mt-8">On Ayurveda and herbal medicine</h2>
          <p>
            We're honest. Some traditional remedies have real evidence behind them — turmeric for inflammation, ashwagandha for stress, honey for coughs. Many others don't. And some carry real risks, especially for children (heavy metals in unregulated supplements, herb-drug interactions, dosing unknowns for small bodies).
          </p>
          <p>
            KiddieDaily covers Ayurvedic and herbal medicine with the same rigor we apply to pharmaceutical news: what does the evidence say? What are the blind spots? What does your pediatrician need to know? We consult the NIH's National Center for Complementary and Integrative Health (NCCIH) as our baseline reference.
          </p>

          <h2 className="text-xl font-black text-[var(--ink)] mt-8">Content safety</h2>
          <p>
            Every article is rated G, PG, or PG-13 before it reaches your inbox. Parents set age restrictions per child. Anything beyond PG-13 is blocked entirely — it never reaches subscribers. Our AI safety gate plus human moderators ensure nothing inappropriate slips through.
          </p>

          <h2 className="text-xl font-black text-[var(--ink)] mt-8">Open to publishers</h2>
          <p>
            KiddieDaily isn't a walled garden. Bloggers, journalists, researchers, and health professionals can <Link href="/publishers" className="text-[var(--accent)] font-bold">submit their content</Link> for inclusion. Our AI analyzes every submission for bias, accuracy, and credibility — and assigns a publisher tier. The best content gets featured. The worst gets rejected. Transparency for everyone.
          </p>
        </div>
      </article>
    </main>
  )
}
