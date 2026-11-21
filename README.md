# Living Docs Agent

Hackathon project (Developer Productivity): a **branded document teammate**. Born knowing only its employer brand vault; banks clients, notes, and inspiration grammar live; renders proposals onto [Paper](https://paper.design).

v0.2: proposals only · ingest pipeline · comment moat · inspo-driven structure (brand sovereign).

> ChatGPT emits a corpse — this agent hands you a living document on a shared canvas.

## Run

```bash
cp .env.example .env   # XAI_API_KEY for chat + vision inspo
pip install -r requirements.txt

# Paper Desktop must be open
python agent.py --smoke          # render sample proposal (no API key)
python agent.py --fix-comments  # P2 moat when comments exist on canvas
python agent.py                  # interactive (needs .env)
python ui.py                     # http://127.0.0.1:8765  (upload inspo → uploads/)
```

## Demo (5 beats)

Fresh brain → paste notes → URL → upload inspo → render → fix comments → kill/relaunch.  
Script: `docs/demo/SCRIPT.md`.

## Anatomy

| Path | Role |
|------|------|
| `brain/CONTEXT.md` | STATUS + DECISIONS |
| `knowledge/` | Employer DNA + live-banked clients |
| `brand/jonatech-digital/` | Sovereign style + real logo + fallback template |
| `.agents/skills/inspirations.md` | Layout grammar (no brand theft) |
| `vault_server.py` | Memory + ingest tools |
| `comment_loop.py` | P2 comment moat |
| `uploads/` | Inspiration drops from ui.py |
