# Jonatech Docs Agent

Branded document teammate for Jonatech Digital. v0.1 ships **proposals only** — memory (brain), company knowledge, growing skills, brand vault, render onto Paper.

> ChatGPT emits a corpse — this agent hands you a living document on a shared canvas.

## Run

```bash
cp .env.example .env   # set XAI_API_KEY for chat loop
pip install -r requirements.txt

# Paper Desktop must be open
python agent.py --smoke   # P1: render Ronnie/$500 proposal onto Paper (no API key)
python agent.py           # interactive Grok + tools (needs .env)
```

Web chat (projector): `python ui.py` → http://127.0.0.1:8765

Flip model in `config.toml`: `provider = "xai"` | `"openrouter"`.

## Demo (60s)

`python agent.py --smoke` → branded proposal on Paper file **Jonatech Digital — Documents**.  
Or chat: *Proposal for Ronnie — the Cursor workshop training gig, $500, our standard terms.*  
Full script: `docs/demo/SCRIPT.md`.

## Anatomy

| Path | Role |
|------|------|
| `brain/CONTEXT.md` | STATUS (rewrite) + DECISIONS (append) |
| `knowledge/` | Brand, clients, pricing, SOUL |
| `brand/jonatech-digital/` | style + logo + `proposal.html` |
| `vault_server.py` | FastMCP memory/knowledge/skills tools |
| `agent.py` | Grok loop + four-call wake-up |
