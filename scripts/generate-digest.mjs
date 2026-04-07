/**
 * KiddieDaily Digest Generator — Trust Spectrum Classification
 * Categories: Kids First / Parent Friendly / Research Backed
 */
const TRUST = {
  KIDS_FIRST: { label: 'Kids First', color: '#4CAF50', icon: '🛡️', desc: 'Prioritizes child safety above all' },
  PARENT_FRIENDLY: { label: 'Parent Friendly', color: '#FF9800', icon: '👨‍👩‍👧‍👦', desc: 'Balanced, practical, actionable' },
  RESEARCH_BACKED: { label: 'Research Backed', color: '#2196F3', icon: '🔬', desc: 'Clinical/academic evidence' }
}

function classify(story) {
  const s = story.source.toLowerCase(), t = story.title.toLowerCase()
  if (['cpsc','fda','recall','safety'].some(k => s.includes(k)||t.includes(k))) return 'KIDS_FIRST'
  if (['jama','aap','who','cdc','nih','lancet'].some(k => s.includes(k))) return 'RESEARCH_BACKED'
  return 'PARENT_FRIENDLY'
}

async function main() {
  const fs = await import('node:fs/promises'), path = await import('node:path')
  const date = process.argv.includes('--date') ? process.argv[process.argv.indexOf('--date')+1] : new Date().toISOString().split('T')[0]
  const data = JSON.parse(await fs.readFile(path.join(process.cwd(), 'data', 'digests', `${date}.json`), 'utf8'))
  const stories = data.stories.map(s => ({ ...s, trust: classify(s), trustLabel: TRUST[classify(s)].label, trustIcon: TRUST[classify(s)].icon }))
  const top = stories.sort((a,b) => (b.relevanceScore+b.sourceCredibility)-(a.relevanceScore+a.sourceCredibility))[0]
  const safety = stories.find(s => s.category === 'safety' && s.relevanceScore > 60)
  const wellness = stories.find(s => s !== top && ['wellness','mental-health','nutrition'].includes(s.category))
  const spectrum = { KIDS_FIRST: stories.filter(s=>s.trust==='KIDS_FIRST').slice(0,3), PARENT_FRIENDLY: stories.filter(s=>s.trust==='PARENT_FRIENDLY').slice(0,3), RESEARCH_BACKED: stories.filter(s=>s.trust==='RESEARCH_BACKED').slice(0,3) }
  const digest = { date, subject: top ? `${top.title} + ${stories.length-1} more` : `KiddieDaily ${date}`, topStory: top, safetyAlert: safety, wellnessSignal: wellness, bySpectrum: spectrum, trustSpectrum: TRUST, allStories: stories.slice(0,20), totalStories: stories.length, totalSources: data.sources.length }
  await fs.writeFile(path.join(process.cwd(), 'data', 'digests', `${date}-digest.json`), JSON.stringify(digest, null, 2))
  console.log(`[DIGEST] ${date}: ${stories.length} stories, top: ${top?.title}`)
}
main().catch(e => { console.error(e); process.exit(1) })
