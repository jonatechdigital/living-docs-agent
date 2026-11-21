"""Living Docs Agent — vault FastMCP server (brain + knowledge + skills + brand + ingest)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
BRAIN_PATH = ROOT / "brain" / "CONTEXT.md"
KNOWLEDGE_DIR = ROOT / "knowledge"
SKILLS_DIR = ROOT / ".agents" / "skills"
SKILLS_LOCK = SKILLS_DIR / "skills-lock.json"
INSPIRATIONS_PATH = SKILLS_DIR / "inspirations.md"
BRAND_ROOT = ROOT / "brand"
UPLOADS_DIR = ROOT / "uploads"

ALLOWED_DOC_TYPES = {"proposal"}
ALLOWED_BRANDS = {"jonatech-digital"}
ALLOWED_KNOWLEDGE = {
    "1_Brand_DNA.md",
    "2_Clients.md",
    "3_Services_and_Pricing.md",
    "SOUL.md",
}

mcp = FastMCP("jonatech-vault")


def _today() -> str:
    return date.today().isoformat()


def _err(msg: str) -> str:
    return f"ERROR: {msg}"


def _bump_lock(skill_key: str = "proposal") -> str:
    if SKILLS_LOCK.is_file():
        lock = json.loads(SKILLS_LOCK.read_text(encoding="utf-8"))
    else:
        lock = {"version": "0.1.0", "skills": {}}
    skill = lock.setdefault("skills", {}).setdefault(
        skill_key, {"file": f"{skill_key}.md", "version": "0.1.0"}
    )
    for bag in (skill, lock):
        parts = str(bag.get("version", "0.1.0")).split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            parts = ["0", "1", "1"]
        bag["version"] = ".".join(parts)
    SKILLS_LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return skill["version"]


@mcp.tool()
def load_brain() -> str:
    """Return brain/CONTEXT.md verbatim. Missing/corrupt → ⚠️ BRAIN NOT LOADED."""
    try:
        if not BRAIN_PATH.is_file():
            return "⚠️ BRAIN NOT LOADED"
        text = BRAIN_PATH.read_text(encoding="utf-8")
        if "## STATUS" not in text or "## DECISIONS" not in text:
            return "⚠️ BRAIN NOT LOADED"
        return text
    except Exception:
        return "⚠️ BRAIN NOT LOADED"


@mcp.tool()
def rewrite_status(section: str, new_text: str) -> str:
    """Rewrite one STATUS line in place. section matches the label before the colon."""
    try:
        if not section or not section.strip():
            return _err("section is required")
        if new_text is None:
            return _err("new_text is required")
        brain = load_brain()
        if brain.startswith("⚠️"):
            return brain
        lines = brain.splitlines()
        key = section.strip().rstrip(":")
        pattern = re.compile(rf"^(\s*-\s*{re.escape(key)}\s*:\s*).*$", re.IGNORECASE)
        found = False
        out: list[str] = []
        in_status = False
        for line in lines:
            if line.strip().startswith("## STATUS"):
                in_status = True
                out.append(line)
                continue
            if line.strip().startswith("## ") and in_status:
                in_status = False
            if in_status and pattern.match(line):
                out.append(f"- {key}: {new_text.strip()}")
                found = True
            else:
                out.append(line)
        if not found:
            inserted = False
            rebuilt: list[str] = []
            for line in out:
                if line.strip().startswith("## DECISIONS") and not inserted:
                    rebuilt.append(f"- {key}: {new_text.strip()}")
                    inserted = True
                rebuilt.append(line)
            out = rebuilt
            if not inserted:
                return _err(f"STATUS section missing; cannot set '{key}'")
        BRAIN_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
        return f"OK: STATUS '{key}' → {new_text.strip()}"
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def append_decision(text: str) -> str:
    """Prepend a dated decision under ## DECISIONS. Immutable once written."""
    try:
        if not text or not text.strip():
            return _err("text is required")
        brain = load_brain()
        if brain.startswith("⚠️"):
            return brain
        entry = f"- {_today()}: {text.strip()}"
        lines = brain.splitlines()
        out: list[str] = []
        inserted = False
        for line in lines:
            out.append(line)
            if line.strip().startswith("## DECISIONS") and not inserted:
                out.append(entry)
                inserted = True
        if not inserted:
            return _err("## DECISIONS header not found")
        BRAIN_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
        return f"OK: decision appended — {entry}"
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def load_knowledge() -> str:
    """Concatenate knowledge/ files in numeric order; SOUL.md last."""
    try:
        if not KNOWLEDGE_DIR.is_dir():
            return _err("knowledge/ directory missing")
        numbered = sorted(
            [p for p in KNOWLEDGE_DIR.glob("*.md") if re.match(r"^\d+_", p.name)],
            key=lambda p: p.name,
        )
        soul = KNOWLEDGE_DIR / "SOUL.md"
        parts: list[str] = []
        for p in numbered:
            parts.append(f"<!-- {p.name} -->\n{p.read_text(encoding='utf-8').rstrip()}\n")
        if soul.is_file():
            parts.append(f"<!-- SOUL.md -->\n{soul.read_text(encoding='utf-8').rstrip()}\n")
        if not parts:
            return _err("no knowledge files found")
        return "\n".join(parts)
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def read_skill(doc_type: str) -> str:
    """Return .agents/skills/<doc_type>.md. proposal only."""
    try:
        if doc_type not in ALLOWED_DOC_TYPES:
            return _err(f"doc_type must be one of {sorted(ALLOWED_DOC_TYPES)}")
        path = SKILLS_DIR / f"{doc_type}.md"
        if not path.is_file():
            return _err(f"skill file missing: {path.name}")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def append_lesson(doc_type: str, lesson: str) -> str:
    """Append dated lesson under ## LESSONS; bump skills-lock.json version."""
    try:
        if doc_type not in ALLOWED_DOC_TYPES:
            return _err(f"doc_type must be one of {sorted(ALLOWED_DOC_TYPES)}")
        if not lesson or not lesson.strip():
            return _err("lesson is required")
        path = SKILLS_DIR / f"{doc_type}.md"
        if not path.is_file():
            return _err(f"skill file missing: {path.name}")
        text = path.read_text(encoding="utf-8")
        entry = f"- [{_today()}] {lesson.strip()}"
        if "## LESSONS" not in text:
            text = text.rstrip() + "\n\n## LESSONS\n" + entry + "\n"
        else:
            text = text.rstrip() + "\n" + entry + "\n"
        path.write_text(text, encoding="utf-8")
        ver = _bump_lock(doc_type)
        return f"OK: lesson appended — {entry} (skill {doc_type} → {ver})"
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def read_brand_style(brand: str) -> str:
    """Return brand/<brand>/style.md. jonatech-digital only."""
    try:
        if brand not in ALLOWED_BRANDS:
            return _err(f"brand must be one of {sorted(ALLOWED_BRANDS)}")
        path = BRAND_ROOT / brand / "style.md"
        if not path.is_file():
            return _err(f"style.md missing for brand '{brand}'")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def read_template(doc_type: str) -> str:
    """Return templates/<doc_type>.html — FALLBACK when no inspirations pattern."""
    try:
        if doc_type not in ALLOWED_DOC_TYPES:
            return _err(f"doc_type must be one of {sorted(ALLOWED_DOC_TYPES)}")
        path = BRAND_ROOT / "jonatech-digital" / "templates" / f"{doc_type}.html"
        if not path.is_file():
            return _err(f"template missing: {path}")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def read_inspirations() -> str:
    """Return .agents/skills/inspirations.md (layout grammar). Empty patterns OK."""
    try:
        if not INSPIRATIONS_PATH.is_file():
            return "NO INSPIRATIONS YET — use templates/proposal.html as fallback."
        return INSPIRATIONS_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def append_knowledge(file: str, section: str, text: str) -> str:
    """Dated append into knowledge/<file> under ## <section>. LIVE BANKING."""
    try:
        name = Path(file).name
        if name not in ALLOWED_KNOWLEDGE:
            return _err(f"file must be one of {sorted(ALLOWED_KNOWLEDGE)}")
        if not section or not section.strip():
            return _err("section is required")
        if not text or not text.strip():
            return _err("text is required")
        path = KNOWLEDGE_DIR / name
        if not path.is_file():
            return _err(f"knowledge file missing: {name}")
        body = path.read_text(encoding="utf-8")
        heading = f"## {section.strip()}"
        entry = f"\n- [{_today()}] {text.strip()}\n"
        if heading in body:
            # Append after the heading block: find next ## or EOF
            idx = body.index(heading) + len(heading)
            # skip rest of heading line
            nl = body.find("\n", idx)
            insert_at = nl + 1 if nl != -1 else len(body)
            next_h = re.search(r"\n## ", body[insert_at:])
            if next_h:
                pos = insert_at + next_h.start()
                body = body[:pos] + entry + body[pos:]
            else:
                body = body.rstrip() + "\n" + entry
        else:
            body = body.rstrip() + f"\n\n{heading}\n{entry}"
        path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
        return f"OK: banked into {name} / {heading}"
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def ingest_meeting_notes(notes: str) -> str:
    """Extract client facts from notes; bank under 2_Clients.md; return MISSING fields."""
    try:
        if not notes or not notes.strip():
            return _err("notes is required")
        raw = notes.strip()

        # Heuristic extract — never invent; leave missing for the agent to ask
        client = None
        for pat in (
            r"(?:client|company)\s*[:\-]\s*([A-Za-z][\w&.'\-]*(?:\s+[A-Za-z][\w&.'\-]*){0,4})",
            r"(?:call|meeting|notes)\s+with\s+([A-Za-z][\w&.'\-]*(?:\s+[A-Za-z][\w&.'\-]*){0,4})",
            r"(?:for|with)\s+([A-Z][a-zA-Z0-9&.'\-]+(?:\s+[A-Z][a-zA-Z0-9&.'\-]+){0,3})\b",
        ):
            m = re.search(pat, raw, re.I)
            if m:
                client = m.group(1).strip().rstrip(".,;")
                # Stop at verbs that aren't part of a name
                client = re.split(
                    r"\b(?:need|wants?|asked|discussed|for|to)\b", client, maxsplit=1, flags=re.I
                )[0].strip(" .,-")
                if len(client) >= 2:
                    break
                client = None
        if not client:
            m2 = re.search(r"^#\s*(.+)$", raw, re.M)
            if m2:
                client = m2.group(1).strip()[:60]

        price = None
        pm = re.search(r"(?<![A-Za-z])(?:USD\s*)?\$\s*([\d,]+(?:\.\d+)?)", raw)
        if not pm:
            pm = re.search(r"\b([\d,]+)\s*(?:USD|dollars?)\b", raw, re.I)
        if pm:
            price = f"${pm.group(1).replace(',', '')}"

        needs = []
        for line in raw.splitlines():
            line = line.strip(" -*\t")
            if len(line) > 20 and any(
                k in line.lower()
                for k in ("need", "want", "scope", "build", "train", "workshop", "deliver")
            ):
                needs.append(line)

        dates = re.findall(
            r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)\b",
            raw,
            re.I,
        )

        missing: list[str] = []
        if not client:
            missing.append("client_name")
        if not price:
            missing.append("price")
        if not needs:
            missing.append("scope_or_needs")
        if not dates:
            missing.append("dates_or_deadline")

        section = client or "Unknown client"
        bank_bits = [
            f"Source: meeting notes ({_today()})",
            f"Raw excerpt: {raw[:400].replace(chr(10), ' ')}",
        ]
        if needs:
            bank_bits.append("Needs/scope: " + "; ".join(needs[:5]))
        if price:
            bank_bits.append(f"Pricing discussed: {price}")
        if dates:
            bank_bits.append("Dates mentioned: " + ", ".join(dates[:5]))

        banked = append_knowledge("2_Clients.md", section, " | ".join(bank_bits))
        return json.dumps(
            {
                "banked": banked,
                "client": client,
                "price": price,
                "needs": needs[:5],
                "dates": dates[:5],
                "missing": missing,
                "ask_user": (
                    f"Please confirm: {', '.join(missing)}" if missing else "All key fields present."
                ),
            },
            indent=2,
        )
    except Exception as e:
        return _err(str(e))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = False
        self.parts: list[str] = []
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip = True
        if tag == "title":
            self._skip = False

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "title"}:
            self._skip = False

    def handle_data(self, data):
        if self._skip:
            return
        t = " ".join(data.split())
        if t:
            self.parts.append(t)


@mcp.tool()
def study_client_website(url: str) -> str:
    """Fetch URL (10s). Bank business summary under client section; graceful offline."""
    try:
        if not url or not url.strip():
            return _err("url is required")
        u = url.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u

        # Guess client section from hostname
        host = re.sub(r"^https?://", "", u).split("/")[0]
        client_guess = host.split(".")[0].replace("-", " ").title()

        try:
            req = urllib.request.Request(
                u,
                headers={"User-Agent": "LivingDocsAgent/0.2 (+hackathon)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read(200_000).decode("utf-8", errors="ignore")
            parser = _TextExtractor()
            parser.feed(raw)
            blob = " ".join(parser.parts)[:1200]
            title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
            title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else host
            summary = (
                f"Website: {u} | Title: {title} | "
                f"Extract: {blob[:700]}"
            )
            banked = append_knowledge("2_Clients.md", client_guess, summary)
            return json.dumps(
                {"ok": True, "client_section": client_guess, "title": title, "banked": banked},
                indent=2,
            )
        except Exception as net_e:
            note = f"website pending ({u}) — fetch failed: {net_e}"
            banked = append_knowledge("2_Clients.md", client_guess, note)
            return json.dumps(
                {
                    "ok": False,
                    "pending": True,
                    "message": "No wifi / fetch failed — banked pending note; continue without website.",
                    "banked": banked,
                    "error": str(net_e),
                },
                indent=2,
            )
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def study_inspiration(path: str, grammar_text: str = "") -> str:
    """Study inspo image/PDF — LAYOUT GRAMMAR ONLY. Never bank colors/fonts/logo.

    If vision fails / no API key, pass grammar_text (user's 3 lines on layout).
    """
    try:
        if not path or not path.strip():
            return _err("path is required (or 'typed' with grammar_text)")
        p = Path(path.strip())
        if not p.is_file():
            for base in (UPLOADS_DIR, ROOT, ROOT / "uploads"):
                cand = base / path.strip()
                if cand.is_file():
                    p = cand
                    break
        if not p.is_file() and not (grammar_text or "").strip():
            return _err(
                f"file not found: {path}. "
                "Fallback: ask user to type 3 lines on layout; recall with grammar_text=..."
            )

        grammar = (grammar_text or "").strip() or None
        vision_error = None
        # Optional Grok vision when XAI_API_KEY present
        key = os.environ.get("XAI_API_KEY", "")
        if (
            not grammar
            and key
            and p.is_file()
            and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
        ):
            try:
                import base64

                from openai import OpenAI

                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
                client = OpenAI(api_key=key, base_url="https://api.x.ai/v1")
                resp = client.chat.completions.create(
                    model=os.environ.get("XAI_VISION_MODEL", "grok-4-fast"),
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "Analyze this proposal/design image for LAYOUT GRAMMAR ONLY. "
                                        "Return: section order, hierarchy, grid/columns, density, "
                                        "what sits above the fold. "
                                        "HARD RULE: do NOT mention colors, fonts, logos, or brand marks. "
                                        "3–8 short bullets."
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                                },
                            ],
                        }
                    ],
                )
                grammar = (resp.choices[0].message.content or "").strip()
                # Strip any accidental brand mentions
                for bad in ("#[0-9A-Fa-f]{3,8}", "font-family", "logo", "Helvetica", "Inter"):
                    grammar = re.sub(bad, "[redacted]", grammar, flags=re.I)
            except Exception as ve:
                vision_error = str(ve)

        if not grammar:
            return json.dumps(
                {
                    "ok": False,
                    "need_user": True,
                    "path": str(p) if p.is_file() else path,
                    "vision_error": vision_error,
                    "ask": (
                        "Vision unavailable. Please type 3 lines on what you like about this layout "
                        "(section order / hierarchy / density only — no colors), "
                        "then call study_inspiration again with grammar_text=..."
                    ),
                },
                indent=2,
            )

        if not INSPIRATIONS_PATH.is_file():
            INSPIRATIONS_PATH.write_text(
                "# Inspiration patterns (LAYOUT GRAMMAR ONLY)\n\n## Patterns\n",
                encoding="utf-8",
            )
        label = p.name if p.is_file() else "typed-grammar"
        src_line = p.as_posix() if p.is_file() else "typed by user"
        note = (
            f"\n### [{_today()}] {label}\n"
            f"- Source: `{src_line}`\n"
            f"{chr(10).join('- ' + ln.lstrip('- ').strip() for ln in grammar.splitlines() if ln.strip())}\n"
        )
        text = INSPIRATIONS_PATH.read_text(encoding="utf-8")
        if "## Patterns" in text:
            text = text.rstrip() + "\n" + note
        else:
            text = text.rstrip() + "\n\n## Patterns\n" + note
        INSPIRATIONS_PATH.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        if SKILLS_LOCK.is_file():
            lock = json.loads(SKILLS_LOCK.read_text(encoding="utf-8"))
        else:
            lock = {"version": "0.1.0", "skills": {}}
        lock.setdefault("skills", {}).setdefault(
            "inspirations", {"file": "inspirations.md", "version": "0.1.0"}
        )
        SKILLS_LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        _bump_lock("inspirations")

        return json.dumps(
            {
                "ok": True,
                "path": str(p),
                "banked_to": str(INSPIRATIONS_PATH),
                "grammar_preview": grammar[:800],
                "reminder": "STRUCTURE only — brand colors/fonts/logo stay Jonatech Digital vault.",
            },
            indent=2,
        )
    except Exception as e:
        return _err(str(e))


if __name__ == "__main__":
    os.environ.setdefault("FASTMCP_SHOW_CLI_BANNER", "false")
    mcp.run(transport="stdio")
