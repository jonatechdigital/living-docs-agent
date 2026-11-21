"""Projector-friendly FastAPI chat UI for Jonatech Docs Agent."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from agent import DocsAgent

agent: DocsAgent | None = None
_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global agent
    agent = DocsAgent()
    await agent.start()
    yield
    await agent.close()
    agent = None


app = FastAPI(title="Jonatech Docs Agent", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Jonatech Docs Agent</title>
  <style>
    :root { --navy:#0B1F3A; --teal:#00C2A8; --paper:#F7F4EF; --ink:#1A1A1A; }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(160deg, #0B1F3A 0%, #132a4a 50%, #0a182c 100%);
      color: var(--ink); min-height: 100vh; display: flex; flex-direction: column;
    }
    header {
      padding: 20px 28px; color: #fff; display: flex; align-items: baseline; gap: 12px;
      border-bottom: 1px solid rgba(0,194,168,.35);
    }
    header h1 { font-size: 22px; margin: 0; letter-spacing: -0.02em; }
    header span { color: var(--teal); font-size: 13px; }
    #log {
      flex: 1; overflow-y: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 14px;
    }
    .bubble {
      max-width: 92%; padding: 14px 16px; border-radius: 10px; white-space: pre-wrap;
      line-height: 1.45; font-size: 15px;
    }
    .you { align-self: flex-end; background: var(--teal); color: var(--navy); }
    .docs { align-self: flex-start; background: var(--paper); color: var(--ink); }
    .sys { align-self: center; color: rgba(255,255,255,.55); font-size: 12px; }
    form {
      display: flex; gap: 10px; padding: 16px 28px 24px; background: rgba(0,0,0,.25);
    }
    input {
      flex: 1; padding: 14px 16px; border: none; border-radius: 8px; font-size: 16px;
      background: var(--paper); color: var(--ink);
    }
    button {
      padding: 14px 22px; border: none; border-radius: 8px; font-size: 15px; font-weight: 600;
      background: var(--teal); color: var(--navy); cursor: pointer;
    }
    button:disabled { opacity: .5; cursor: wait; }
  </style>
</head>
<body>
  <header>
    <h1>Jonatech Docs Agent</h1>
    <span>proposals · living canvas</span>
  </header>
  <div id="log"><div class="sys">Ready. Ask for a proposal.</div></div>
  <form id="f">
    <input id="m" autocomplete="off" placeholder="Proposal for Ronnie — Cursor workshop, $500…" />
    <button type="submit" id="go">Send</button>
  </form>
  <script>
    const log = document.getElementById('log');
    const form = document.getElementById('f');
    const input = document.getElementById('m');
    const btn = document.getElementById('go');
    function add(cls, text) {
      const d = document.createElement('div');
      d.className = 'bubble ' + cls;
      d.textContent = text;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      add('you', text);
      btn.disabled = true;
      try {
        const r = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: text})
        });
        const j = await r.json();
        add('docs', j.reply || j.error || '(empty)');
      } catch (err) {
        add('docs', 'Request failed: ' + err);
      } finally {
        btn.disabled = false;
        input.focus();
      }
    });
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE


@app.post("/chat")
async def chat(body: ChatIn):
    if agent is None:
        return JSONResponse({"error": "agent not started"}, status_code=503)
    async with _lock:
        try:
            reply = await agent.chat(body.message)
            return {"reply": reply}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/health")
async def health():
    return {
        "ok": agent is not None,
        "paper": bool(agent and agent.hub.paper_available),
        "vault": bool(agent and agent.hub.vault_available),
        "model": agent.model if agent else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ui:app", host="127.0.0.1", port=8765, reload=False)
