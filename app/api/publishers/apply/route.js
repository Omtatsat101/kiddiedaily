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

export async function POST(request) {
  const formData = await request.formData()

  const application = {
    id: `pub-${Date.now()}`,
    name: formData.get('name'),
    email: formData.get('email'),
    siteUrl: formData.get('siteUrl'),
    rssUrl: formData.get('rssUrl'),
    credentials: formData.getAll('credentials'),
    bio: formData.get('bio'),
    status: 'pending',
    appliedAt: new Date().toISOString(),
  }

  if (!application.name || !application.email || !application.siteUrl) {
    return NextResponse.json({ error: 'Name, email, and site URL required' }, { status: 400 })
  }

  const data = await loadPublishers()
  data.applications.push(application)
  data.lastUpdated = new Date().toISOString()
  await writeFile(PUBLISHERS_PATH, JSON.stringify(data, null, 2))

  console.log(`[PUBLISHER] New application: ${application.name} (${application.siteUrl})`)

  return NextResponse.redirect(new URL('/publishers?applied=true', request.url))
}

export async function GET() {
  const data = await loadPublishers()
  return NextResponse.json(data)
}
