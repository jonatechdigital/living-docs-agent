"""Projector-friendly FastAPI chat UI — Living Docs Agent."""

from __future__ import annotations

import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import DocsAgent
from mcp_client import ROOT

agent: DocsAgent | None = None
_agent_error: str | None = None
_agent_ready = asyncio.Event()
_lock = asyncio.Lock()
UPLOADS = ROOT / "uploads"
BRAND_ASSETS = ROOT / "brand" / "jonatech-digital" / "assets"


async def _boot_agent() -> None:
    """Start vault+Paper in background so the HTTP port binds immediately."""
    global agent, _agent_error
    try:
        print("[ui] booting agent (vault + Paper MCP)…", flush=True)
        a = DocsAgent()
        await a.start()
        agent = a
        print(
            f"[ui] agent ready model={a.model} "
            f"vault={a.hub.vault_available} paper={a.hub.paper_available}",
            flush=True,
        )
    except Exception as e:
        _agent_error = str(e)
        print(f"[ui] agent boot failed: {e}", flush=True)
    finally:
        _agent_ready.set()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global agent, _agent_error
    UPLOADS.mkdir(parents=True, exist_ok=True)
    _agent_ready.clear()
    _agent_error = None
    boot = asyncio.create_task(_boot_agent())
    yield
    boot.cancel()
    if agent is not None:
        await agent.close()
        agent = None


app = FastAPI(title="Living Docs Agent", lifespan=lifespan)
if BRAND_ASSETS.is_dir():
    app.mount("/brand", StaticFiles(directory=str(BRAND_ASSETS)), name="brand")


class ChatIn(BaseModel):
    message: str


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Living Docs Agent</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap" rel="stylesheet" />
  <style>
    :root {
      --ink: #1A2D2B;
      --green: #00AA3E;
      --green-deep: #008C34;
      --paper: #F3EEE4;
      --paper-2: #EBE4D6;
      --muted: #5C6570;
      --line: #D4CFC6;
      --white: #FFFCFA;
      --shadow: 0 18px 50px rgba(26, 45, 43, 0.12);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: "Outfit", system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(0,170,62,0.14), transparent 55%),
        radial-gradient(900px 500px at 100% 0%, rgba(26,45,43,0.08), transparent 50%),
        linear-gradient(165deg, #F7F4EF 0%, var(--paper) 45%, var(--paper-2) 100%);
      min-height: 100vh;
      display: grid;
      place-items: stretch;
    }
    .shell {
      width: min(920px, 100%);
      margin: 0 auto;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      padding: 28px 24px 20px;
      gap: 18px;
    }
    header.top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      animation: rise 0.5s ease both;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
      min-width: 0;
    }
    .brand img {
      height: 52px;
      width: auto;
      border-radius: 8px;
      background: #0a0a0a;
      padding: 6px 10px;
      box-shadow: var(--shadow);
    }
    .brand-copy { min-width: 0; }
    .brand-copy h1 {
      margin: 0;
      font-size: clamp(1.35rem, 2.4vw, 1.75rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.1;
    }
    .brand-copy p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }
    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,252,250,0.7);
      border: 1px solid var(--line);
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--muted);
      white-space: nowrap;
    }
    .status .dot {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--green);
      box-shadow: 0 0 0 0 rgba(0,170,62,0.55);
      animation: pulse 1.8s ease infinite;
    }
    .status.busy .dot { background: #C9A227; animation-duration: 0.9s; }
    .status.down .dot { background: #B42318; animation: none; }

    .stage {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: var(--white);
      border: 1px solid rgba(212,207,198,0.9);
      border-radius: 22px;
      box-shadow: var(--shadow);
      overflow: hidden;
      animation: rise 0.55s ease 0.05s both;
    }
    .chat-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 20px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #FFFCFA, #F7F4EF);
    }
    .chat-head strong {
      font-size: 0.92rem;
      letter-spacing: -0.01em;
    }
    .chat-head span {
      color: var(--muted);
      font-size: 0.78rem;
    }
    #log {
      flex: 1;
      overflow-y: auto;
      padding: 22px 22px 28px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      scroll-behavior: smooth;
      background:
        linear-gradient(180deg, rgba(247,244,239,0.35), transparent 120px),
        repeating-linear-gradient(
          -12deg,
          transparent,
          transparent 11px,
          rgba(26,45,43,0.015) 11px,
          rgba(26,45,43,0.015) 12px
        );
    }
    .empty {
      margin: auto;
      text-align: left;
      max-width: 460px;
      width: 100%;
      padding: 8px;
      animation: rise 0.6s ease 0.12s both;
    }
    .empty h2 {
      font-family: "Source Serif 4", Georgia, serif;
      font-weight: 600;
      font-size: 1.45rem;
      margin: 0 0 8px;
      letter-spacing: -0.02em;
    }
    .empty p {
      margin: 0 0 16px;
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.95rem;
    }
    .chips {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .chip {
      text-align: left;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 14px;
      padding: 12px 14px;
      font: 500 0.9rem/1.35 Outfit, system-ui, sans-serif;
      cursor: pointer;
      transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
    }
    .chip small {
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-weight: 400;
      font-size: 0.78rem;
    }
    .chip:hover {
      border-color: var(--green);
      box-shadow: 0 8px 20px rgba(26,45,43,0.06);
      transform: translateY(-1px);
    }

    .msg {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-width: min(86%, 680px);
      animation: pop 0.28s ease both;
    }
    .msg.you { align-self: flex-end; align-items: flex-end; }
    .msg.docs { align-self: flex-start; align-items: flex-start; }
    .msg .who {
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 0 4px;
    }
    .msg.you .who { color: var(--green-deep); }
    .bubble {
      padding: 14px 16px;
      border-radius: 18px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.55;
      font-size: 1.02rem;
    }
    .msg.you .bubble {
      background: var(--ink);
      color: #F7F4EF;
      border-bottom-right-radius: 5px;
    }
    .msg.docs .bubble {
      background: #fff;
      color: var(--ink);
      border: 1px solid var(--line);
      border-bottom-left-radius: 5px;
      box-shadow: 0 6px 18px rgba(26,45,43,0.04);
    }
    .msg.typing .bubble {
      display: inline-flex;
      gap: 5px;
      align-items: center;
      min-width: 52px;
      padding: 14px 18px;
    }
    .msg.typing .bubble i {
      width: 7px; height: 7px; border-radius: 50%;
      background: var(--muted);
      opacity: 0.45;
      animation: blink 1.1s infinite ease-in-out;
    }
    .msg.typing .bubble i:nth-child(2) { animation-delay: 0.15s; }
    .msg.typing .bubble i:nth-child(3) { animation-delay: 0.3s; }

    .composer {
      padding: 14px 16px 16px;
      border-top: 1px solid var(--line);
      background: linear-gradient(180deg, #FFFCFA 0%, #F7F4EF 100%);
    }
    form.row {
      display: flex;
      gap: 10px;
      align-items: flex-end;
    }
    #m {
      flex: 1;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 16px;
      padding: 14px 16px;
      font: 400 1.02rem/1.4 Outfit, system-ui, sans-serif;
      color: var(--ink);
      outline: none;
      resize: none;
      min-height: 52px;
      max-height: 160px;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    #m:focus {
      border-color: var(--green);
      box-shadow: 0 0 0 3px rgba(0,170,62,0.15);
    }
    #go {
      border: none;
      border-radius: 14px;
      padding: 0 22px;
      height: 52px;
      background: var(--green);
      color: #fff;
      font: 600 0.95rem Outfit, system-ui, sans-serif;
      cursor: pointer;
      transition: background 0.15s, transform 0.12s;
      flex-shrink: 0;
    }
    #go:hover { background: var(--green-deep); }
    #go:active { transform: scale(0.98); }
    #go:disabled { opacity: 0.55; cursor: wait; }

    .tools {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 10px;
    }
    label.upload {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px dashed var(--muted);
      color: var(--ink);
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      background: transparent;
      transition: border-color 0.15s, color 0.15s;
    }
    label.upload:hover { border-color: var(--green); color: var(--green-deep); }
    input[type=file] { display: none; }
    #uphint { color: var(--muted); font-size: 0.78rem; }

    @keyframes rise {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: none; }
    }
    @keyframes pop {
      from { opacity: 0; transform: translateY(6px) scale(0.98); }
      to { opacity: 1; transform: none; }
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(0,170,62,0.45); }
      70% { box-shadow: 0 0 0 8px rgba(0,170,62,0); }
      100% { box-shadow: 0 0 0 0 rgba(0,170,62,0); }
    }
    @keyframes blink {
      0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    @media (max-width: 640px) {
      .shell { padding: 16px 12px 12px; }
      .brand img { height: 42px; }
      .status span.label { display: none; }
      .msg { max-width: 94%; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="top">
      <div class="brand">
        <img src="/brand/jonatech-logo-original.png" alt="Jonatech Digital" />
        <div class="brand-copy">
          <h1>Living Docs Agent</h1>
          <p>Bank live · render on Paper · remember corrections</p>
        </div>
      </div>
      <div class="status" id="pill"><span class="dot"></span><span class="label">Connecting…</span></div>
    </header>

    <main class="stage">
      <div class="chat-head">
        <strong>Chat</strong>
        <span id="threadMeta">Demo session · proposals only</span>
      </div>
      <div id="log">
        <div class="empty" id="empty">
          <h2>Start the conversation</h2>
          <p>Tap a starter, or paste notes / a URL below. Replies show here; Paper updates on the right.</p>
          <div class="chips">
            <button type="button" class="chip" data-send="Call with Ronnie. Need Cursor workshop training for builders. Discussed $500. Standard terms.">
              Bank meeting notes
              <small>Call with Ronnie · workshop · $500</small>
            </button>
            <button type="button" class="chip" data-send="Proposal for Ronnie — Cursor workshop, $500, our standard terms.">
              Render proposal
              <small>Write branded page onto Paper</small>
            </button>
            <button type="button" class="chip" data-send="fix my comments">
              Fix my comments
              <small>Read canvas comments → edit → resolve</small>
            </button>
          </div>
        </div>
      </div>
      <div class="composer">
        <form id="f" class="row">
          <textarea id="m" rows="1" autocomplete="off" placeholder="Paste notes, a URL, or ask for a proposal…"></textarea>
          <button type="submit" id="go">Send</button>
        </form>
        <div class="tools">
          <label class="upload">Upload inspiration<input type="file" id="inspo" accept="image/*,.pdf" /></label>
          <span id="uphint">Layout only — brand stays Jonatech</span>
        </div>
      </div>
    </main>
  </div>
  <script>
    const log = document.getElementById('log');
    const empty = document.getElementById('empty');
    const form = document.getElementById('f');
    const input = document.getElementById('m');
    const btn = document.getElementById('go');
    const inspo = document.getElementById('inspo');
    const pill = document.getElementById('pill');
    const pillLabel = pill.querySelector('.label');
    let typingEl = null;

    function clearEmpty() {
      if (empty && empty.parentNode) empty.remove();
    }
    function autosize() {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    }
    function add(role, text) {
      clearEmpty();
      const wrap = document.createElement('div');
      wrap.className = 'msg ' + role;
      const who = document.createElement('div');
      who.className = 'who';
      who.textContent = role === 'you' ? 'You' : 'Docs';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = text;
      wrap.appendChild(who);
      wrap.appendChild(bubble);
      log.appendChild(wrap);
      log.scrollTop = log.scrollHeight;
      return wrap;
    }
    function showTyping() {
      clearEmpty();
      typingEl = document.createElement('div');
      typingEl.className = 'msg docs typing';
      typingEl.innerHTML = '<div class="who">Docs</div><div class="bubble"><i></i><i></i><i></i></div>';
      log.appendChild(typingEl);
      log.scrollTop = log.scrollHeight;
    }
    function hideTyping() {
      if (typingEl) { typingEl.remove(); typingEl = null; }
    }
    function setStatus(kind, label) {
      pill.classList.remove('busy', 'down');
      if (kind) pill.classList.add(kind);
      pillLabel.textContent = label;
    }
    async function refreshHealth() {
      try {
        const r = await fetch('/health');
        const j = await r.json();
        if (!j.ready) setStatus('busy', 'Starting…');
        else if (!j.ok) setStatus('down', 'Agent down');
        else setStatus('', j.paper ? 'Paper live' : 'Ready (no Paper)');
      } catch {
        setStatus('down', 'Offline');
      }
    }
    async function send(text) {
      add('you', text);
      btn.disabled = true;
      setStatus('busy', 'Working…');
      showTyping();
      try {
        const r = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: text})
        });
        const j = await r.json();
        hideTyping();
        add('docs', j.reply || j.error || '(empty)');
      } catch (err) {
        hideTyping();
        add('docs', 'Request failed: ' + err);
      } finally {
        btn.disabled = false;
        input.focus();
        refreshHealth();
      }
    }
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      autosize();
      await send(text);
    });
    input.addEventListener('input', autosize);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form.requestSubmit();
      }
    });
    document.querySelectorAll('.chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const text = chip.getAttribute('data-send') || '';
        if (text) send(text);
      });
    });
    inspo.addEventListener('change', async () => {
      if (!inspo.files || !inspo.files[0]) return;
      const file = inspo.files[0];
      const name = (file.name || '').toLowerCase();
      if (name.endsWith('.md') || name.endsWith('.txt')) {
        document.getElementById('uphint').textContent = 'Notes file — paste into chat instead';
        add('docs', 'Meeting notes should be pasted as text, not uploaded as inspiration. Open KELH_MEETING_NOTES.md and paste the “Paste-ready” block.');
        inspo.value = '';
        return;
      }
      const fd = new FormData();
      fd.append('file', file);
      document.getElementById('uphint').textContent = 'Uploading…';
      try {
        const r = await fetch('/upload', { method: 'POST', body: fd });
        const j = await r.json();
        if (j.path) {
          document.getElementById('uphint').textContent = 'Inspiration attached';
          await send('inspo: ' + j.path);
        } else {
          add('docs', j.error || 'Upload failed');
        }
      } catch (err) {
        add('docs', 'Upload failed: ' + err);
      }
      inspo.value = '';
    });
    refreshHealth();
    setInterval(refreshHealth, 8000);
    input.focus();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE


@app.post("/chat")
async def chat(body: ChatIn):
    if not _agent_ready.is_set():
        return JSONResponse(
            {"error": "Agent still starting (Paper/vault). Wait a few seconds and retry."},
            status_code=503,
        )
    if agent is None:
        return JSONResponse(
            {"error": f"Agent failed to start: {_agent_error or 'unknown'}"},
            status_code=503,
        )
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
        "ready": _agent_ready.is_set(),
        "error": _agent_error,
        "paper": bool(agent and agent.hub.paper_available),
        "vault": bool(agent and agent.hub.vault_available),
        "model": agent.model if agent else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("ui:app", host="127.0.0.1", port=8765, reload=False)
