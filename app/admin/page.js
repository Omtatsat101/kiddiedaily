'use client'

import Link from 'next/link'
import { useState, useEffect } from 'react'

const TABS = ['sources', 'moderation', 'publishers', 'digest']

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState('sources')
  const [sources, setSources] = useState([])
  const [moderation, setModeration] = useState([])
  const [publishers, setPublishers] = useState([])
  const [digests, setDigests] = useState([])
  const [digestPreview, setDigestPreview] = useState(null)
  const [loading, setLoading] = useState(false)

  // New source form
  const [newSource, setNewSource] = useState({ name: '', url: '', category: 'health', credibility: 70, tier: 'consumer' })

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    const [srcRes, modRes, pubRes, digRes] = await Promise.allSettled([
      fetch('/api/admin/sources').then(r => r.json()),
      fetch('/api/admin/moderation').then(r => r.json()),
      fetch('/api/admin/publishers').then(r => r.json()),
      fetch('/api/admin/digest').then(r => r.json()),
    ])
    if (srcRes.status === 'fulfilled') setSources(srcRes.value.sources || [])
    if (modRes.status === 'fulfilled') setModeration(modRes.value.queue || [])
    if (pubRes.status === 'fulfilled') setPublishers(pubRes.value.applications || [])
    if (digRes.status === 'fulfilled') setDigests(digRes.value.digests || [])
    setLoading(false)
  }

  const addSource = async () => {
    if (!newSource.name || !newSource.url) return
    await fetch('/api/admin/sources', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(newSource),
    })
    setNewSource({ name: '', url: '', category: 'health', credibility: 70, tier: 'consumer' })
    loadData()
  }

  const removeSource = async (id) => {
    await fetch(`/api/admin/sources?id=${id}`, { method: 'DELETE' })
    loadData()
  }

  const moderateItem = async (id, decision) => {
    await fetch('/api/admin/moderation', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ id, decision }),
    })
    loadData()
  }

  const reviewPublisher = async (id, status) => {
    await fetch('/api/admin/publishers', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ id, status }),
    })
    loadData()
  }

  const previewDigest = async (date) => {
    const res = await fetch(`/api/admin/digest?date=${date}`)
    if (res.ok) {
      const data = await res.json()
      setDigestPreview(data)
    }
  }

  return (
    <main className="min-h-screen">
      <nav className="max-w-6xl mx-auto px-6 py-5 flex items-center justify-between">
        <Link href="/" className="text-2xl font-black tracking-tight">
          Kiddie<span className="text-[var(--accent)]">Daily</span>
          <span className="text-xs font-bold text-[var(--muted)] ml-2">Admin</span>
        </Link>
        <div className="flex gap-4 items-center text-sm font-semibold text-[var(--muted)]">
          <Link href="/" className="hover:text-[var(--ink)]">Site</Link>
          <Link href="/archive" className="hover:text-[var(--ink)]">Archive</Link>
        </div>
      </nav>

      <section className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="text-3xl font-black mb-6">Admin Dashboard</h1>

        {/* TABS */}
        <div className="flex gap-2 mb-8 flex-wrap">
          {TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-2.5 rounded-xl text-sm font-bold capitalize transition-all ${
                activeTab === tab
                  ? 'bg-[var(--ink)] text-white'
                  : 'bg-white border border-[var(--border)] text-[var(--muted)] hover:text-[var(--ink)]'
              }`}
            >
              {tab}
              {tab === 'moderation' && moderation.filter(m => m.status === 'pending').length > 0 && (
                <span className="ml-2 px-1.5 py-0.5 bg-red-500 text-white rounded-full text-xs">
                  {moderation.filter(m => m.status === 'pending').length}
                </span>
              )}
              {tab === 'publishers' && publishers.filter(p => p.status === 'pending').length > 0 && (
                <span className="ml-2 px-1.5 py-0.5 bg-orange-500 text-white rounded-full text-xs">
                  {publishers.filter(p => p.status === 'pending').length}
                </span>
              )}
            </button>
          ))}
        </div>

        {loading && <p className="text-[var(--muted)] text-sm mb-4">Loading...</p>}

        {/* SOURCES TAB */}
        {activeTab === 'sources' && (
          <div>
            <h2 className="text-xl font-black mb-4">Source Management</h2>
            <p className="text-sm text-[var(--muted)] mb-6">Add or remove custom RSS sources. Default sources from lib/sources.mjs are always included.</p>

            {/* Add source form */}
            <div className="bg-white border border-[var(--border)] rounded-xl p-6 mb-6">
              <h3 className="text-sm font-bold tracking-widest uppercase text-[var(--muted)] mb-4">Add New Source</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-xs font-bold text-[var(--muted)] mb-1">Source Name</label>
                  <input
                    type="text"
                    value={newSource.name}
                    onChange={e => setNewSource({ ...newSource, name: e.target.value })}
                    placeholder="e.g. Pediatric News Weekly"
                    className="w-full px-4 py-2.5 border-2 border-[var(--border)] rounded-lg text-sm font-semibold bg-white outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-[var(--muted)] mb-1">RSS Feed URL</label>
                  <input
                    type="url"
                    value={newSource.url}
                    onChange={e => setNewSource({ ...newSource, url: e.target.value })}
                    placeholder="https://example.com/feed.xml"
                    className="w-full px-4 py-2.5 border-2 border-[var(--border)] rounded-lg text-sm font-semibold bg-white outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-[var(--muted)] mb-1">Category</label>
                  <select
                    value={newSource.category}
                    onChange={e => setNewSource({ ...newSource, category: e.target.value })}
                    className="w-full px-4 py-2.5 border-2 border-[var(--border)] rounded-lg text-sm font-semibold bg-white outline-none focus:border-[var(--accent)]"
                  >
                    <option value="health">Health</option>
                    <option value="wellness">Wellness</option>
                    <option value="safety">Safety</option>
                    <option value="development">Development</option>
                    <option value="nutrition">Nutrition</option>
                    <option value="mental-health">Mental Health</option>
                    <option value="alternative">Alternative</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-[var(--muted)] mb-1">Tier</label>
                  <select
                    value={newSource.tier}
                    onChange={e => setNewSource({ ...newSource, tier: e.target.value })}
                    className="w-full px-4 py-2.5 border-2 border-[var(--border)] rounded-lg text-sm font-semibold bg-white outline-none focus:border-[var(--accent)]"
                  >
                    <option value="research">Research</option>
                    <option value="safety">Safety</option>
                    <option value="expert">Expert</option>
                    <option value="news">News</option>
                    <option value="consumer">Consumer</option>
                    <option value="publisher">Publisher</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-[var(--muted)] mb-1">Credibility (0-100)</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={newSource.credibility}
                    onChange={e => setNewSource({ ...newSource, credibility: parseInt(e.target.value) || 70 })}
                    className="w-full px-4 py-2.5 border-2 border-[var(--border)] rounded-lg text-sm font-semibold bg-white outline-none focus:border-[var(--accent)]"
                  />
                </div>
              </div>
              <button
                onClick={addSource}
                className="px-6 py-2.5 bg-[var(--ink)] text-white rounded-lg text-sm font-bold hover:opacity-90 transition-opacity"
              >
                Add Source
              </button>
            </div>

            {/* Custom sources list */}
            {sources.length > 0 ? (
              <div className="space-y-2">
                <h3 className="text-sm font-bold tracking-widest uppercase text-[var(--muted)] mb-2">Custom Sources ({sources.length})</h3>
                {sources.map(s => (
                  <div key={s.id} className="bg-white border border-[var(--border)] rounded-xl p-4 flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm">{s.name}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-bold">{s.tier}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-bold">{s.category}</span>
                      </div>
                      <p className="text-xs text-[var(--muted)] mt-0.5">{s.url}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-xs font-bold text-[var(--muted)]">Cred: {s.credibility}</span>
                      <button
                        onClick={() => removeSource(s.id)}
                        className="text-xs px-3 py-1.5 bg-red-50 text-red-700 rounded-lg font-bold hover:bg-red-100"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--muted)]">No custom sources added yet. Default sources from lib/sources.mjs are always active.</p>
            )}
          </div>
        )}

        {/* MODERATION TAB */}
        {activeTab === 'moderation' && (
          <div>
            <h2 className="text-xl font-black mb-4">Content Moderation Queue</h2>
            <p className="text-sm text-[var(--muted)] mb-6">Articles flagged by the safety gate for manual review.</p>

            {moderation.filter(m => m.status === 'pending').length > 0 ? (
              <div className="space-y-3">
                {moderation.filter(m => m.status === 'pending').map(item => (
                  <div key={item.id} className="bg-white border border-[var(--border)] rounded-xl p-5">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-orange-50 text-orange-700">
                        {item.safetyRating || 'UNRATED'}
                      </span>
                      <span className="text-xs text-[var(--muted)]">{item.source}</span>
                      <span className="text-xs text-[var(--muted)]">{item.addedAt?.split('T')[0]}</span>
                    </div>
                    <h3 className="font-bold mb-1">{item.title}</h3>
                    <p className="text-sm text-[var(--muted)] mb-3">{item.summary?.slice(0, 200)}</p>
                    {item.flagReason && (
                      <p className="text-xs text-red-600 mb-3">Flag reason: {item.flagReason}</p>
                    )}
                    <div className="flex gap-2">
                      <button
                        onClick={() => moderateItem(item.id, 'approved')}
                        className="px-4 py-2 bg-green-50 text-green-700 rounded-lg text-xs font-bold hover:bg-green-100"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => moderateItem(item.id, 'rejected')}
                        className="px-4 py-2 bg-red-50 text-red-700 rounded-lg text-xs font-bold hover:bg-red-100"
                      >
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
                <p className="text-green-700 font-bold">Queue is clear. No articles pending review.</p>
              </div>
            )}

            {moderation.filter(m => m.status !== 'pending').length > 0 && (
              <div className="mt-8">
                <h3 className="text-sm font-bold tracking-widest uppercase text-[var(--muted)] mb-3">Previously Reviewed</h3>
                <div className="space-y-2">
                  {moderation.filter(m => m.status !== 'pending').slice(0, 10).map(item => (
                    <div key={item.id} className="bg-white border border-[var(--border)] rounded-lg p-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                          item.status === 'approved' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                        }`}>{item.status}</span>
                        <span className="text-sm font-semibold">{item.title?.slice(0, 60)}</span>
                      </div>
                      <span className="text-xs text-[var(--muted)]">{item.moderatedAt?.split('T')[0]}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* PUBLISHERS TAB */}
        {activeTab === 'publishers' && (
          <div>
            <h2 className="text-xl font-black mb-4">Publisher Applications</h2>
            <p className="text-sm text-[var(--muted)] mb-6">Review and approve publisher submissions.</p>

            {publishers.length > 0 ? (
              <div className="space-y-3">
                {publishers.map(app => (
                  <div key={app.id} className="bg-white border border-[var(--border)] rounded-xl p-5">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold">{app.name}</span>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                          app.status === 'pending' ? 'bg-gray-100 text-gray-600' :
                          app.status === 'approved' || app.status === 'verified' ? 'bg-green-50 text-green-700' :
                          app.status === 'rejected' ? 'bg-red-50 text-red-700' :
                          'bg-blue-50 text-blue-700'
                        }`}>
                          {app.status}
                        </span>
                      </div>
                      <span className="text-xs text-[var(--muted)]">{app.appliedAt?.split('T')[0]}</span>
                    </div>
                    <p className="text-sm text-[var(--muted)] mb-1">{app.email}</p>
                    <a href={app.siteUrl} target="_blank" rel="noopener" className="text-sm text-[var(--accent)] font-semibold">{app.siteUrl}</a>
                    {app.rssUrl && <p className="text-xs text-[var(--muted)] mt-0.5">RSS: {app.rssUrl}</p>}
                    {app.credentials?.length > 0 && (
                      <div className="flex gap-1 mt-2 flex-wrap">
                        {app.credentials.map(c => (
                          <span key={c} className="text-xs px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 font-bold">{c}</span>
                        ))}
                      </div>
                    )}
                    {app.bio && <p className="text-sm text-[var(--muted)] mt-2 italic">"{app.bio}"</p>}

                    {app.status === 'pending' && (
                      <div className="flex gap-2 mt-3">
                        <button
                          onClick={() => reviewPublisher(app.id, 'verified')}
                          className="px-4 py-2 bg-green-50 text-green-700 rounded-lg text-xs font-bold hover:bg-green-100"
                        >
                          Approve (Verified)
                        </button>
                        <button
                          onClick={() => reviewPublisher(app.id, 'trusted')}
                          className="px-4 py-2 bg-blue-50 text-blue-700 rounded-lg text-xs font-bold hover:bg-blue-100"
                        >
                          Approve (Trusted)
                        </button>
                        <button
                          onClick={() => reviewPublisher(app.id, 'rejected')}
                          className="px-4 py-2 bg-red-50 text-red-700 rounded-lg text-xs font-bold hover:bg-red-100"
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-[var(--muted)]">No publisher applications yet.</p>
            )}
          </div>
        )}

        {/* DIGEST TAB */}
        {activeTab === 'digest' && (
          <div>
            <h2 className="text-xl font-black mb-4">Digest Preview</h2>
            <p className="text-sm text-[var(--muted)] mb-6">Preview digests before sending. Run <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">npm run ingest && npm run digest</code> to generate.</p>

            {digests.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
                {digests.map(date => (
                  <button
                    key={date}
                    onClick={() => previewDigest(date)}
                    className="bg-white border border-[var(--border)] rounded-xl p-4 text-left hover:border-[var(--accent)] transition-colors"
                  >
                    <p className="text-xs font-bold tracking-widest uppercase text-[var(--muted)]">Digest</p>
                    <p className="text-lg font-black">{date}</p>
                    <p className="text-xs text-[var(--accent)] font-semibold mt-1">Click to preview</p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="bg-orange-50 border border-orange-200 rounded-xl p-6 mb-8">
                <p className="text-sm text-orange-700 font-semibold">No digests found. Run the pipeline:</p>
                <code className="block mt-2 text-xs bg-white p-3 rounded-lg">npm run ingest && npm run digest</code>
              </div>
            )}

            {digestPreview && (
              <div className="bg-white border border-[var(--border)] rounded-2xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-black">Preview: {digestPreview.date}</h3>
                  <div className="text-xs text-[var(--muted)] font-bold">
                    {digestPreview.totalStories} stories / {digestPreview.totalSources} sources
                  </div>
                </div>

                <p className="text-sm font-bold text-[var(--accent)] mb-4">Subject: {digestPreview.subject}</p>

                {/* Safety alert */}
                {digestPreview.safetyAlert && (
                  <div className="bg-orange-50 border-l-4 border-orange-400 rounded-xl p-4 mb-4">
                    <p className="text-xs font-bold tracking-widest uppercase text-orange-700 mb-1">Safety Alert</p>
                    <h4 className="font-bold text-sm">{digestPreview.safetyAlert.title}</h4>
                    <p className="text-xs text-orange-900/70 mt-1">{digestPreview.safetyAlert.summary?.slice(0, 200)}</p>
                  </div>
                )}

                {/* Top story */}
                {digestPreview.topStory && (
                  <div className="border border-[var(--border)] rounded-xl p-4 mb-4">
                    <p className="text-xs font-bold tracking-widest uppercase text-[var(--trust-research)] mb-1">Top Story</p>
                    <h4 className="font-bold">{digestPreview.topStory.title}</h4>
                    <p className="text-sm text-[var(--muted)] mt-1">{digestPreview.topStory.summary?.slice(0, 200)}</p>
                    <p className="text-xs text-[var(--muted)] mt-2">Source: {digestPreview.topStory.source} | Relevance: {digestPreview.topStory.relevanceScore}</p>
                  </div>
                )}

                {/* All stories preview */}
                {digestPreview.allStories && (
                  <div className="mt-4">
                    <p className="text-xs font-bold tracking-widest uppercase text-[var(--muted)] mb-2">All Stories ({digestPreview.allStories.length})</p>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {digestPreview.allStories.map((s, i) => (
                        <div key={i} className="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-50 text-sm">
                          <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{s.trust?.replace('_', ' ')}</span>
                          <span className="font-semibold flex-1">{s.title?.slice(0, 80)}</span>
                          <span className="text-xs text-[var(--muted)]">{s.source}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="mt-6 flex gap-3">
                  <Link
                    href={`/digest/${digestPreview.date}`}
                    className="px-5 py-2.5 bg-[var(--accent)] text-white rounded-lg text-sm font-bold hover:opacity-90"
                  >
                    View Full Digest Page
                  </Link>
                  <button
                    onClick={() => setDigestPreview(null)}
                    className="px-5 py-2.5 border border-[var(--border)] rounded-lg text-sm font-bold text-[var(--muted)] hover:text-[var(--ink)]"
                  >
                    Close Preview
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  )
}
