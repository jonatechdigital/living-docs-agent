"""Projector-friendly FastAPI chat UI — Living Docs Agent."""

from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from agent import DocsAgent
from mcp_client import ROOT

agent: DocsAgent | None = None
_lock = asyncio.Lock()
UPLOADS = ROOT / "uploads"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global agent
    UPLOADS.mkdir(parents=True, exist_ok=True)
    agent = DocsAgent()
    await agent.start()
    yield
    await agent.close()
    agent = None


app = FastAPI(title="Living Docs Agent", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Living Docs Agent</title>
  <style>
    :root { --ink:#1A2D2B; --green:#00AA3E; --paper:#F7F4EF; }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "DM Sans", "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(160deg, #0d1a18 0%, #1A2D2B 55%, #0a1412 100%);
      color: var(--ink); min-height: 100vh; display: flex; flex-direction: column;
    }
    header {
      padding: 20px 28px; color: #fff; display: flex; align-items: baseline; gap: 12px;
      border-bottom: 1px solid rgba(0,170,62,.35);
    }
    header h1 { font-size: 22px; margin: 0; letter-spacing: -0.02em; }
    header span { color: var(--green); font-size: 13px; }
    #log {
      flex: 1; overflow-y: auto; padding: 24px 28px; display: flex; flex-direction: column; gap: 14px;
    }
    .bubble {
      max-width: 92%; padding: 14px 16px; border-radius: 10px; white-space: pre-wrap;
      line-height: 1.45; font-size: 15px;
    }
    .you { align-self: flex-end; background: var(--green); color: #fff; }
    .docs { align-self: flex-start; background: var(--paper); color: var(--ink); }
    .sys { align-self: center; color: rgba(255,255,255,.55); font-size: 12px; }
    .composer {
      display: flex; flex-direction: column; gap: 10px; padding: 16px 28px 24px;
      background: rgba(0,0,0,.25);
    }
    .row { display: flex; gap: 10px; align-items: center; }
    input[type=text] {
      flex: 1; padding: 14px 16px; border: none; border-radius: 8px; font-size: 16px;
      background: var(--paper); color: var(--ink);
    }
    button, label.upload {
      padding: 14px 18px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600;
      background: var(--green); color: #fff; cursor: pointer;
    }
    button:disabled { opacity: .5; cursor: wait; }
    label.upload { background: transparent; border: 1px solid rgba(0,170,62,.6); color: #c8f0d4; }
    input[type=file] { display: none; }
    .hint { color: rgba(255,255,255,.45); font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h1>Living Docs Agent</h1>
    <span>proposals · bank live · Paper canvas</span>
  </header>
  <div id="log"><div class="sys">Ready. Paste notes, a URL, upload inspo, or ask for a proposal.</div></div>
  <div class="composer">
    <form id="f" class="row">
      <input id="m" autocomplete="off" placeholder="Paste meeting notes, a URL, or ask for a proposal…" />
      <button type="submit" id="go">Send</button>
    </form>
    <div class="row">
      <label class="upload">Upload inspiration<input type="file" id="inspo" accept="image/*,.pdf" /></label>
      <span class="hint" id="uphint">Saves to uploads/ and posts inspo: uploads/&lt;name&gt;</span>
    </div>
  </div>
  <script>
    const log = document.getElementById('log');
    const form = document.getElementById('f');
    const input = document.getElementById('m');
    const btn = document.getElementById('go');
    const inspo = document.getElementById('inspo');
    function add(cls, text) {
      const d = document.createElement('div');
      d.className = 'bubble ' + cls;
      d.textContent = text;
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
    }
    async function send(text) {
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
    }
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      await send(text);
    });
    inspo.addEventListener('change', async () => {
      if (!inspo.files || !inspo.files[0]) return;
      const fd = new FormData();
      fd.append('file', inspo.files[0]);
      document.getElementById('uphint').textContent = 'Uploading…';
      try {
        const r = await fetch('/upload', { method: 'POST', body: fd });
        const j = await r.json();
        if (j.path) {
          document.getElementById('uphint').textContent = 'Saved ' + j.path;
          await send('inspo: ' + j.path);
        } else {
          add('docs', j.error || 'Upload failed');
        }
      } catch (err) {
        add('docs', 'Upload failed: ' + err);
      }
      inspo.value = '';
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


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    raw = file.filename or "inspo.bin"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw).name)[:80]
    name = f"{uuid.uuid4().hex[:8]}_{safe}"
    dest = UPLOADS / name
    data = await file.read()
    dest.write_bytes(data)
    rel = f"uploads/{name}"
    return {"path": rel, "bytes": len(data)}


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
