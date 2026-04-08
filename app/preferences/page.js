'use client'

import Link from 'next/link'
import { useState, useEffect, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const AGE_GROUPS = [
  { id: '0-2', label: '0-2 years', desc: 'Infant & Toddler', icon: '👶' },
  { id: '3-5', label: '3-5 years', desc: 'Preschool', icon: '🧒' },
  { id: '6-8', label: '6-8 years', desc: 'Early Elementary', icon: '📚' },
  { id: '9-12', label: '9-12 years', desc: 'Pre-Teen', icon: '🎒' },
]

const TOPICS = [
  { id: 'nutrition', label: 'Nutrition', icon: '🥦', desc: 'Diet, vitamins, feeding tips' },
  { id: 'safety', label: 'Safety & Recalls', icon: '⚠️', desc: 'Product recalls, safety alerts' },
  { id: 'development', label: 'Development', icon: '📈', desc: 'Milestones, growth, learning' },
  { id: 'play', label: 'Play & Activities', icon: '🎨', desc: 'Games, outdoor play, creativity' },
  { id: 'wellness', label: 'Wellness', icon: '💚', desc: 'General health, prevention' },
  { id: 'mental-health', label: 'Mental Health', icon: '🧠', desc: 'Anxiety, ADHD, emotions' },
  { id: 'sleep', label: 'Sleep', icon: '😴', desc: 'Sleep training, routines, issues' },
  { id: 'vaccines', label: 'Vaccines', icon: '💉', desc: 'Immunization news & research' },
  { id: 'screen-time', label: 'Screen Time', icon: '📱', desc: 'Digital wellness, limits' },
  { id: 'alternative', label: 'Ayurveda & Herbal', icon: '🌿', desc: 'Traditional & complementary medicine' },
]

const RATING_OPTIONS = [
  { id: 'G', label: 'G Only', desc: 'Only articles safe for all ages', color: 'text-green-700 bg-green-50' },
  { id: 'PG', label: 'Up to PG', desc: 'Includes vaccine discussions, allergy management, etc.', color: 'text-orange-700 bg-orange-50' },
  { id: 'PG-13', label: 'Up to PG-13', desc: 'Includes pre-teen topics like puberty, social media', color: 'text-red-700 bg-red-50' },
]

function PreferencesContent() {
  const searchParams = useSearchParams()
  const emailParam = searchParams.get('email') || ''
  const justSubscribed = searchParams.get('subscribed') === 'true'

  const [email, setEmail] = useState(emailParam)
  const [ageGroups, setAgeGroups] = useState(['3-5', '6-8'])
  const [topics, setTopics] = useState(['nutrition', 'safety', 'development', 'play', 'wellness'])
  const [maxRating, setMaxRating] = useState('PG')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Load existing preferences if email is provided
  useEffect(() => {
    if (emailParam) {
      fetch(`/api/preferences?email=${encodeURIComponent(emailParam)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data?.preferences) {
            setAgeGroups(data.preferences.ageGroups || ['3-5', '6-8'])
            setTopics(data.preferences.topics || ['nutrition', 'safety', 'development', 'play', 'wellness'])
            setMaxRating(data.preferences.maxRating || 'PG')
          }
        })
        .catch(() => {})
    }
  }, [emailParam])

  const toggleAge = (id) => {
    setAgeGroups(prev => prev.includes(id) ? prev.filter(a => a !== id) : [...prev, id])
  }

  const toggleTopic = (id) => {
    setTopics(prev => prev.includes(id) ? prev.filter(t => t !== id) : [...prev, id])
  }

  const handleSave = async () => {
    if (!email) { setError('Enter your email to save preferences.'); return }
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/preferences', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ email, preferences: { ageGroups, topics, maxRating } }),
      })
      const data = await res.json()
      if (res.ok) {
        setSaved(true)
        setTimeout(() => setSaved(false), 3000)
      } else {
        setError(data.error || 'Failed to save. Make sure you are subscribed first.')
      }
    } catch {
      setError('Network error. Try again.')
    }
    setLoading(false)
  }

  return (
    <main className="min-h-screen">
      <nav className="max-w-4xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
          <Link href="/preferences" className="text-[var(--ink)]">Preferences</Link>
          <Link href="/about" className="hover:text-[var(--ink)]">About</Link>
        </div>
      </nav>

      <section className="max-w-3xl mx-auto px-6 py-12">
        {justSubscribed && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-5 mb-8">
            <h2 className="text-lg font-extrabold text-green-800 mb-1">Welcome to KiddieDaily!</h2>
            <p className="text-sm text-green-700">Set your preferences below to personalize your daily digest.</p>
          </div>
        )}

        <h1 className="text-3xl font-black mb-2">Your Preferences</h1>
        <p className="text-[var(--muted)] mb-8">Customize your daily digest. Choose your kids' ages, favorite topics, and content rating comfort level.</p>

        {/* EMAIL */}
        <div className="mb-10">
          <label className="block text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">
            Your email
          </label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="your@email.com"
            className="w-full max-w-md px-4 py-3 border-2 border-[var(--border)] rounded-xl text-base font-semibold bg-white outline-none focus:border-[var(--accent)]"
          />
        </div>

        {/* AGE GROUPS */}
        <div className="mb-10">
          <h2 className="text-xl font-black mb-1">Child Age Groups</h2>
          <p className="text-sm text-[var(--muted)] mb-4">Select all that apply. Content will be tailored to these age ranges.</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {AGE_GROUPS.map(ag => (
              <button
                key={ag.id}
                onClick={() => toggleAge(ag.id)}
                className={`p-4 rounded-xl border-2 text-center transition-all ${
                  ageGroups.includes(ag.id)
                    ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                    : 'border-[var(--border)] bg-white hover:border-[var(--accent)]/50'
                }`}
              >
                <div className="text-2xl mb-1">{ag.icon}</div>
                <div className="text-sm font-bold">{ag.label}</div>
                <div className="text-xs text-[var(--muted)]">{ag.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* TOPICS */}
        <div className="mb-10">
          <h2 className="text-xl font-black mb-1">Topics</h2>
          <p className="text-sm text-[var(--muted)] mb-4">Pick the categories you want in your daily digest.</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {TOPICS.map(t => (
              <button
                key={t.id}
                onClick={() => toggleTopic(t.id)}
                className={`p-4 rounded-xl border-2 text-left transition-all ${
                  topics.includes(t.id)
                    ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                    : 'border-[var(--border)] bg-white hover:border-[var(--accent)]/50'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{t.icon}</span>
                  <span className="text-sm font-bold">{t.label}</span>
                </div>
                <div className="text-xs text-[var(--muted)]">{t.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* CONTENT RATING */}
        <div className="mb-10">
          <h2 className="text-xl font-black mb-1">Content Rating Threshold</h2>
          <p className="text-sm text-[var(--muted)] mb-4">Set the maximum content rating you want to receive.</p>
          <div className="space-y-3">
            {RATING_OPTIONS.map(r => (
              <button
                key={r.id}
                onClick={() => setMaxRating(r.id)}
                className={`w-full p-4 rounded-xl border-2 text-left transition-all flex items-center gap-4 ${
                  maxRating === r.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/5'
                    : 'border-[var(--border)] bg-white hover:border-[var(--accent)]/50'
                }`}
              >
                <span className={`px-3 py-1.5 rounded-full text-xs font-bold ${r.color}`}>{r.id}</span>
                <div>
                  <div className="text-sm font-bold">{r.label}</div>
                  <div className="text-xs text-[var(--muted)]">{r.desc}</div>
                </div>
                {maxRating === r.id && (
                  <span className="ml-auto text-[var(--accent)] font-bold text-sm">Selected</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* SAVE */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4">
            <p className="text-sm text-red-700 font-semibold">{error}</p>
          </div>
        )}
        {saved && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-4 mb-4">
            <p className="text-sm text-green-700 font-semibold">Preferences saved! Your next digest will reflect these choices.</p>
          </div>
        )}
        <button
          onClick={handleSave}
          disabled={loading}
          className="px-8 py-4 bg-gradient-to-br from-[var(--accent)] to-[var(--accent-dark)] text-white rounded-xl text-base font-extrabold hover:translate-y-[-2px] hover:shadow-lg transition-all disabled:opacity-50"
        >
          {loading ? 'Saving...' : 'Save Preferences'}
        </button>

        {/* SUMMARY */}
        <div className="mt-10 bg-white border border-[var(--border)] rounded-xl p-6">
          <h3 className="text-sm font-bold tracking-widest uppercase text-[var(--muted)] mb-3">Current Settings</h3>
          <div className="space-y-2 text-sm">
            <p><strong>Age Groups:</strong> {ageGroups.length > 0 ? ageGroups.join(', ') : 'None selected'}</p>
            <p><strong>Topics:</strong> {topics.length > 0 ? topics.join(', ') : 'None selected'}</p>
            <p><strong>Max Rating:</strong> {maxRating}</p>
          </div>
        </div>
      </section>
    </main>
  )
}

export default function PreferencesPage() {
  return (
    <Suspense fallback={
      <main className="min-h-screen">
        <div className="max-w-3xl mx-auto px-6 py-16 text-center">
          <p className="text-[var(--muted)]">Loading preferences...</p>
        </div>
      </main>
    }>
      <PreferencesContent />
    </Suspense>
  )
}
