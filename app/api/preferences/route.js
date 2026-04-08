import { NextResponse } from 'next/server'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const SUBSCRIBERS_PATH = join(process.cwd(), 'data', 'subscribers.json')

async function loadSubscribers() {
  try {
    return JSON.parse(await readFile(SUBSCRIBERS_PATH, 'utf8'))
  } catch {
    const data = { subscribers: [], lastUpdated: new Date().toISOString() }
    await mkdir(join(process.cwd(), 'data'), { recursive: true })
    await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))
    return data
  }
}

export async function GET(request) {
  const { searchParams } = new URL(request.url)
  const email = searchParams.get('email')
  if (!email) return NextResponse.json({ error: 'Email required' }, { status: 400 })

  const data = await loadSubscribers()
  const sub = data.subscribers.find(s => s.email === email && s.active)
  if (!sub) return NextResponse.json({ error: 'Subscriber not found' }, { status: 404 })

  return NextResponse.json({ preferences: sub.preferences, email: sub.email })
}

export async function POST(request) {
  const body = await request.json()
  const { email, preferences } = body

  if (!email) return NextResponse.json({ error: 'Email required' }, { status: 400 })

  const data = await loadSubscribers()
  const sub = data.subscribers.find(s => s.email === email)

  if (!sub) {
    return NextResponse.json({ error: 'Subscriber not found. Subscribe first.' }, { status: 404 })
  }

  sub.preferences = {
    ...sub.preferences,
    ...preferences,
  }
  sub.updatedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))

  return NextResponse.json({ ok: true, preferences: sub.preferences })
}
