import { NextResponse } from 'next/server'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const MODERATION_PATH = join(process.cwd(), 'data', 'moderation.json')

async function loadModeration() {
  try {
    return JSON.parse(await readFile(MODERATION_PATH, 'utf8'))
  } catch {
    const data = { queue: [], lastUpdated: new Date().toISOString() }
    await mkdir(join(process.cwd(), 'data'), { recursive: true })
    await writeFile(MODERATION_PATH, JSON.stringify(data, null, 2))
    return data
  }
}

export async function GET() {
  const data = await loadModeration()
  return NextResponse.json(data)
}

export async function POST(request) {
  const body = await request.json()
  const { id, decision, notes } = body

  if (!id || !decision) {
    return NextResponse.json({ error: 'Article ID and decision required' }, { status: 400 })
  }

  const data = await loadModeration()
  const item = data.queue.find(q => q.id === id)
  if (!item) return NextResponse.json({ error: 'Item not found' }, { status: 404 })

  item.status = decision
  item.moderationNotes = notes || ''
  item.moderatedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(MODERATION_PATH, JSON.stringify(data, null, 2))

  return NextResponse.json({ ok: true, item })
}
