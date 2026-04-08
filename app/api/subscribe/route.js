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

export async function POST(request) {
  const contentType = request.headers.get('content-type') || ''
  let email, preferences

  if (contentType.includes('application/json')) {
    const body = await request.json()
    email = body.email
    preferences = body.preferences
  } else {
    const formData = await request.formData()
    email = formData.get('email')
  }

  if (!email || !email.includes('@')) {
    return NextResponse.json({ error: 'Valid email required' }, { status: 400 })
  }

  const data = await loadSubscribers()
  const existing = data.subscribers.find(s => s.email === email)

  if (existing) {
    if (preferences) {
      existing.preferences = { ...existing.preferences, ...preferences }
      existing.updatedAt = new Date().toISOString()
    }
  } else {
    data.subscribers.push({
      id: `sub-${Date.now()}`,
      email,
      preferences: preferences || {
        ageGroups: ['3-5', '6-8'],
        topics: ['nutrition', 'safety', 'development', 'play', 'wellness'],
        maxRating: 'PG',
      },
      subscribedAt: new Date().toISOString(),
      active: true,
    })
  }

  data.lastUpdated = new Date().toISOString()
  await writeFile(SUBSCRIBERS_PATH, JSON.stringify(data, null, 2))

  console.log(`[SUBSCRIBE] ${existing ? 'Updated' : 'New'}: ${email}`)

  // If it was a form submission, redirect. If JSON API, return JSON.
  if (contentType.includes('application/json')) {
    return NextResponse.json({ ok: true, subscriber: data.subscribers.find(s => s.email === email) })
  }

  return NextResponse.redirect(new URL('/preferences?subscribed=true&email=' + encodeURIComponent(email), request.url))
}
