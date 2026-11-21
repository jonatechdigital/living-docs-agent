# Living Docs Agent

Hackathon project (Developer Productivity): a **branded document teammate** — not a chatbot. It keeps memory, loads company knowledge, grows a skill library from corrections, defends a brand vault, and renders living proposals onto [Paper](https://paper.design).

v0.1 scope: **proposals only**.

> ChatGPT emits a corpse — this agent hands you a living document on a shared canvas.

## Demo brand pack

`brand/jonatech-digital/` and the sample `knowledge/` files are **example assets** used to show how the system works in a live demo. Swap the vault for any brand — this repo is not a product claim for any company.

## Run

```bash
cp .env.example .env   # set XAI_API_KEY for chat loop
pip install -r requirements.txt

# Paper Desktop must be open
python agent.py --smoke   # P1: render sample proposal onto Paper (no API key)
python agent.py           # interactive model + tools (needs .env)
```

Web chat (projector): `python ui.py` → http://127.0.0.1:8765

Flip model in `config.toml`: `provider = "xai"` | `"openrouter"`.

## Demo (60s)

`python agent.py --smoke` → branded proposal on the Paper canvas (sample client “Ronnie”, workshop gig).  
Full script: `docs/demo/SCRIPT.md`.

## Anatomy

| Path | Role |
|------|------|
| `brain/CONTEXT.md` | STATUS (rewrite) + DECISIONS (append) |
| `knowledge/` | Sample company files (replace with yours) |
| `brand/<brand>/` | style + logo + `proposal.html` |
| `vault_server.py` | FastMCP memory/knowledge/skills tools |
| `agent.py` | Model loop + four-call wake-up |
