# Codex Bridge Protocol

## Rules
- Claude creates requests in `queue/`
- Codex reviews and responds in `responses/`
- Completed handoffs move to `resolved/`
- All communication is via Git — no API calls

## Request Format
YAML frontmatter + markdown body in `queue/*.md`

## Response Format
YAML frontmatter + findings in `responses/*.md`
