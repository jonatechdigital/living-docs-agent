# Skill: Proposal

## Procedure
1. Wake-up: `load_brain` → `load_knowledge` → `read_skill("proposal")` → `read_brand_style("jonatech-digital")` → `read_inspirations`.
2. If brain is `⚠️ BRAIN NOT LOADED` — refuse to render.
3. **STRUCTURE:** latest inspirations.md pattern if present; ELSE `read_template("proposal")` (fallback).
4. **BRAND:** always style.md + `jonatech-logo-original.png`. Never take colors/fonts/logo from inspo.
5. **CONTENT:** request + banked knowledge. Ask only for missing fields (never invent).
6. Write to Paper — new page, A4 artboard, screenshot self-check (logo, green/slate, TIN footer).
7. Reply with short summary.

## Placeholders (fallback template)
- `logo_src`, `proposal_date`, `title`, `client_name`, `engagement_type`
- `scope_items` (list), `price`, `terms` (list), `next_step`, `footer_line`

## Fix loop (comments) — THE MOAT
1. `paper_list_comment_threads` status=open.
2. For each: read → edit layers → `paper_get_screenshot` verify → bank decision/lesson if durable → resolve.
3. Fast-path: user says "fix my comments" (`python agent.py --fix-comments`).

## Banking
- Fact → `append_knowledge` / ingest tools
- Preference → `append_decision`
- Procedure → `append_lesson`

## LESSONS
- [2026-11-21] Use inline styles in proposal.html — Paper write_html drops head CSS.
