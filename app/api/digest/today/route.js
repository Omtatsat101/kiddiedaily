import { NextResponse } from 'next/server'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

export async function GET() {
  const today = new Date().toISOString().split('T')[0]
  const digestPath = join(process.cwd(), 'data', 'digests', `${today}-digest.json`)

  try {
    const data = JSON.parse(await readFile(digestPath, 'utf8'))
    return NextResponse.json(data)
  } catch {
    return NextResponse.json(
      { error: 'No digest available for today. Run `npm run ingest && npm run digest` first.' },
      { status: 404 }
    )
  }
}
