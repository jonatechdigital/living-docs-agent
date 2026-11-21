# Skill: Proposal

## Procedure
1. Wake-up (required): `load_brain` → `load_knowledge` → `read_skill("proposal")` → `read_brand_style("jonatech-digital")`.
2. If brain is `⚠️ BRAIN NOT LOADED` — refuse to render.
3. `read_template("proposal")` — ONLY render source. No freehand HTML.
4. Fill Jinja2 placeholders from user request + knowledge (client, service, rate, terms).
5. Place logo from `brand/jonatech-digital/assets/` (never invent a mark).
6. Write HTML layers to Paper drafts file on a **new page**. One proposal = one page.
7. `get_screenshot` → self-check: logo present, navy/teal/paper colors, footer has TIN + contact.
8. Reply with a short summary (client, price, page).

## Placeholders (proposal.html)
- `logo_src`, `proposal_date`, `title`, `client_name`, `engagement_type`
- `scope_items` (list), `price`, `terms` (list), `next_step`, `footer_line`

## Fix loop (comments)
1. List comments on the active page (Paper MCP).
2. For each: edit layer(s) → screenshot-verify → resolve.
3. Durable preference → `append_decision` (fact) AND/OR `append_lesson("proposal", …)` (procedure) **before** resolve.

## LESSONS
<!-- dated procedure corrections grow below — do not put facts here -->
- [2026-11-21] Use inline styles in proposal.html — Paper write_html drops head CSS.
