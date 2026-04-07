# KiddieDaily

**AI-curated kids health & wellness news for parents.** Like Ground News, but for raising healthy kids.

## Mission

Combat misinformation around vaccines, highlight both the benefits and blind spots of Ayurveda and herbal supplements, and give parents balanced, multi-source health news they can actually trust.

## Trust Spectrum

Instead of political left/center/right, KiddieDaily uses a **parent-relevant trust spectrum**:

| Category | Icon | Color | Meaning |
|----------|------|-------|---------|
| **Kids First** | Shield | Green | Prioritizes child safety and wellbeing above all (recalls, alerts, urgent health) |
| **Parent Friendly** | Family | Orange | Balanced, practical, easy to act on (wellness tips, nutrition, screen time) |
| **Research Backed** | Microscope | Blue | Clinical/academic evidence (studies, AAP guidelines, WHO reports) |

Every story is tagged on this spectrum so parents can see *where* the information is coming from and *how* to weight it.

## What parents get

- **Daily digest email** — Top stories, safety alerts, wellness signals, plus a creative activity and product pick
- **Web archive** — Browse past digests, search by topic, filter by age group
- **Multi-source coverage** — Same story from AAP, Reuters, and Healthline? We show all three so you see the full picture
- **Age-group filtering** — Subscribe for your kids' ages (0-2, 3-5, 6-8, 9-12)
- **Topic preferences** — Nutrition, mental health, safety, development, vaccines, herbal/alternative

## Topics covered

- **Vaccines & immunization** — Latest research, schedule updates, myth-busting with citations
- **Nutrition & diet** — What kids actually need, supplement science, allergy updates
- **Ayurveda & herbal** — What works, what doesn't, what needs more research — honest and balanced
- **Mental health** — Anxiety, ADHD, screen time, social media effects, therapy access
- **Safety & recalls** — Product recalls, FDA alerts, CPSC notices
- **Development** — Milestones, speech, motor skills, learning disabilities
- **Sleep** — Research on kids' sleep, routines, screen impact
- **Physical activity** — Exercise guidelines, sports safety, outdoor play benefits

## Architecture

```
Ingest (50+ feeds) → Score with Claude → Classify trust spectrum → Build digest → Send via Resend
                                                                         ↓
                                                                   Next.js web app
                                                                   (archive + subscribe)
```

## Scripts

- `npm run ingest` — Pull news from 50+ RSS feeds, filter kids-relevant, score with Claude Haiku
- `npm run digest` — Generate daily digest with trust spectrum classification
- `npm run send` — Render email and send via Resend (or `--dry-run` to preview)

## Stack

- **Next.js 15** — Web app
- **Claude Haiku** — News scoring, bias detection, parent-friendly summaries (cost-efficient)
- **Resend** — Email delivery
- **Tailwind CSS 4** — Styling

## Part of KiddieSketch / Maya Universe

- Product picks link to **KiddieGo** store
- Activities connect to **KiddieSketch** creative tools
- Wellness content feeds **KiddyHealth** positioning
- Weekly challenges tie into **GoGoMaya** movement games
