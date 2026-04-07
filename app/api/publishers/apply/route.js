import { NextResponse } from 'next/server'

export async function POST(request) {
  const formData = await request.formData()

  const application = {
    name: formData.get('name'),
    email: formData.get('email'),
    siteUrl: formData.get('siteUrl'),
    rssUrl: formData.get('rssUrl'),
    credentials: formData.getAll('credentials'),
    bio: formData.get('bio'),
    appliedAt: new Date().toISOString(),
    status: 'pending',
  }

  if (!application.name || !application.email || !application.siteUrl) {
    return NextResponse.json({ error: 'Name, email, and site URL required' }, { status: 400 })
  }

  // In production:
  // 1. Save to PostgreSQL publishers table
  // 2. Trigger publisher-reviewer AI agent to analyze the site
  // 3. Send confirmation email via Resend
  // 4. Add to admin review queue in Notion

  console.log(`[PUBLISHER] New application: ${application.name} (${application.siteUrl})`)

  return NextResponse.redirect(new URL('/publishers?applied=true', request.url))
}
