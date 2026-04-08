import { NextResponse } from 'next/server'
import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

const DIGESTS_DIR = join(process.cwd(), 'data', 'digests')

export async function GET(request) {
  const { searchParams } = new URL(request.url)
  const date = searchParams.get('date')

  try {
    if (date) {
      // Return specific digest
      const digestPath = join(DIGESTS_DIR, `${date}-digest.json`)
      const data = JSON.parse(await readFile(digestPath, 'utf8'))
      return NextResponse.json(data)
    }

    // List available digests
    const files = await readdir(DIGESTS_DIR).catch(() => [])
    const digests = files
      .filter(f => f.endsWith('-digest.json'))
      .map(f => f.replace('-digest.json', ''))
      .sort()
      .reverse()

    return NextResponse.json({ digests })
  } catch {
    return NextResponse.json({ error: 'No digests found. Run `npm run ingest && npm run digest` first.' }, { status: 404 })
  }
}
