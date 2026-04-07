import { NextResponse } from 'next/server'

export async function POST(request) {
  const formData = await request.formData()
  const email = formData.get('email')

  if (!email || !email.includes('@')) {
    return NextResponse.json({ error: 'Valid email required' }, { status: 400 })
  }

  // In production: save to PostgreSQL subscribers table
  // For now: log and redirect
  console.log(`[SUBSCRIBE] New subscriber: ${email}`)

  // TODO: Send welcome email via Resend
  // TODO: Redirect to preferences page (age group, topics, frequency)

  return NextResponse.redirect(new URL('/?subscribed=true', request.url))
}
