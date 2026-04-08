import { NextResponse } from 'next/server'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const CUSTOM_SOURCES_PATH = join(process.cwd(), 'data', 'custom-sources.json')

async function loadSources() {
  try {
    return JSON.parse(await readFile(CUSTOM_SOURCES_PATH, 'utf8'))
  } catch {
    const data = { sources: [], lastUpdated: new Date().toISOString() }
    await mkdir(join(process.cwd(), 'data'), { recursive: true })
    await writeFile(CUSTOM_SOURCES_PATH, JSON.stringify(data, null, 2))
    return data
  }
}

export async function GET() {
  const data = await loadSources()
  return NextResponse.json(data)
}

export async function POST(request) {
  const body = await request.json()
  const { name, url, category, credibility, tier } = body

  if (!name || !url) {
    return NextResponse.json({ error: 'Name and URL required' }, { status: 400 })
  }

  const data = await loadSources()
  const source = {
    id: `src-${Date.now()}`,
    name,
    url,
    type: 'rss',
    category: category || 'health',
    credibility: credibility || 70,
    tier: tier || 'consumer',
    isActive: true,
    addedAt: new Date().toISOString(),
  }
  data.sources.push(source)
  data.lastUpdated = new Date().toISOString()
  await writeFile(CUSTOM_SOURCES_PATH, JSON.stringify(data, null, 2))

  return NextResponse.json({ ok: true, source })
}

export async function DELETE(request) {
  const { searchParams } = new URL(request.url)
  const id = searchParams.get('id')
  if (!id) return NextResponse.json({ error: 'Source ID required' }, { status: 400 })

  const data = await loadSources()
  data.sources = data.sources.filter(s => s.id !== id)
  data.lastUpdated = new Date().toISOString()
  await writeFile(CUSTOM_SOURCES_PATH, JSON.stringify(data, null, 2))

  return NextResponse.json({ ok: true })
}
