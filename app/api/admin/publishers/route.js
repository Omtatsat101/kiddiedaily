import { NextResponse } from 'next/server'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { join } from 'node:path'

const PUBLISHERS_PATH = join(process.cwd(), 'data', 'publishers.json')

async function loadPublishers() {
  try {
    return JSON.parse(await readFile(PUBLISHERS_PATH, 'utf8'))
  } catch {
    const data = { applications: [], lastUpdated: new Date().toISOString() }
    await mkdir(join(process.cwd(), 'data'), { recursive: true })
    await writeFile(PUBLISHERS_PATH, JSON.stringify(data, null, 2))
    return data
  }
}

export async function GET() {
  const data = await loadPublishers()
  return NextResponse.json(data)
}

export async function POST(request) {
  const body = await request.json()
  const { id, status, notes } = body

  if (!id || !status) {
    return NextResponse.json({ error: 'Application ID and status required' }, { status: 400 })
  }

  const data = await loadPublishers()
  const app = data.applications.find(a => a.id === id)
  if (!app) return NextResponse.json({ error: 'Application not found' }, { status: 404 })

  app.status = status
  app.reviewNotes = notes || ''
  app.reviewedAt = new Date().toISOString()
  data.lastUpdated = new Date().toISOString()
  await writeFile(PUBLISHERS_PATH, JSON.stringify(data, null, 2))

  return NextResponse.json({ ok: true, application: app })
}
