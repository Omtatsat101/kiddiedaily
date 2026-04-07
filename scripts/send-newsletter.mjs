/**
 * KiddieDaily Newsletter Sender — renders digest to email HTML and sends via Resend
 * Usage: node scripts/send-newsletter.mjs [--date 2026-04-07] [--dry-run]
 */
async function main() {
  const fs = await import('node:fs/promises'), path = await import('node:path')
  const args = process.argv.slice(2)
  const date = args.includes('--date') ? args[args.indexOf('--date')+1] : new Date().toISOString().split('T')[0]
  const dryRun = args.includes('--dry-run')
  const digest = JSON.parse(await fs.readFile(path.join(process.cwd(), 'data', 'digests', `${date}-digest.json`), 'utf8'))
  const html = render(digest)
  if (dryRun || !process.env.RESEND_API_KEY) {
    const out = path.join(process.cwd(), 'data', 'digests', `${date}-email.html`)
    await fs.writeFile(out, html)
    console.log(`[SEND] ${dryRun ? 'Dry run' : 'No RESEND_API_KEY'} — saved to ${out}`)
    return
  }
  console.log(`[SEND] Would deliver via Resend to all subscribers`)
}

function render(d) {
  const { topStory: t, safetyAlert: s, wellnessSignal: w, bySpectrum: sp, trustSpectrum: ts } = d
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#faf7f2;font-family:'Helvetica Neue',sans-serif;color:#2a1f18">
<div style="max-width:600px;margin:0 auto;padding:20px">
<div style="text-align:center;padding:24px 0;border-bottom:1px solid #e0dcd4">
<h1 style="margin:0;font-size:28px">Kiddie<span style="color:#C4856A">Daily</span></h1>
<p style="margin:4px 0 0;font-size:13px;color:#7a6b5c">${d.date} • ${d.totalStories} stories from ${d.totalSources} sources</p></div>
<div style="display:flex;justify-content:center;gap:16px;padding:16px 0;border-bottom:1px solid #e0dcd4;font-size:12px;font-weight:700">
${Object.values(ts).map(v=>`<span style="color:${v.color}">${v.icon} ${v.label}</span>`).join(' • ')}</div>
${s?`<div style="background:#FFF3E0;border-left:4px solid #FF9800;padding:16px;margin:20px 0;border-radius:8px">
<p style="margin:0 0 4px;font-size:11px;font-weight:700;color:#E65100;text-transform:uppercase">⚠️ Safety Alert</p>
<h2 style="margin:0 0 8px;font-size:18px">${s.title}</h2>
<p style="margin:0;font-size:14px;color:#5a4a3a">${s.summary?.slice(0,200)||''}</p></div>`:''}
${t?`<div style="padding:20px 0;border-bottom:1px solid #e0dcd4">
<p style="margin:0 0 8px;font-size:11px;font-weight:700;color:#C4856A;text-transform:uppercase">${t.trustIcon} Top Story • ${t.trustLabel}</p>
<h2 style="margin:0 0 8px;font-size:22px">${t.title}</h2>
<p style="margin:0 0 12px;font-size:15px;color:#5a4a3a">${t.summary?.slice(0,300)||''}</p>
${t.actionableInsight?`<p style="margin:0;padding:12px;background:#f0f2ed;border-radius:8px;font-size:14px;font-weight:600;color:#4a7a52">💡 ${t.actionableInsight}</p>`:''}</div>`:''}
<div style="text-align:center;padding:24px 0;font-size:12px;color:#9a9a9a">
<p>KiddieDaily — AI-curated kids health & wellness</p>
<p><a href="#" style="color:#7a6b5c">Unsubscribe</a> • <a href="https://kiddiedaily.com/archive" style="color:#7a6b5c">Archive</a></p></div>
</div></body></html>`
}
main().catch(e=>{console.error(e);process.exit(1)})
