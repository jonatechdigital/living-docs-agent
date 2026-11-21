"""Jonatech Docs Agent — vault FastMCP server (brain + knowledge + skills + brand)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
BRAIN_PATH = ROOT / "brain" / "CONTEXT.md"
KNOWLEDGE_DIR = ROOT / "knowledge"
SKILLS_DIR = ROOT / ".agents" / "skills"
SKILLS_LOCK = SKILLS_DIR / "skills-lock.json"
BRAND_ROOT = ROOT / "brand"

ALLOWED_DOC_TYPES = {"proposal"}
ALLOWED_BRANDS = {"jonatech-digital"}

mcp = FastMCP("jonatech-vault")


def _today() -> str:
    return date.today().isoformat()


def _err(msg: str) -> str:
    return f"ERROR: {msg}"


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
            # Insert before DECISIONS if STATUS has no matching line
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
        for i, line in enumerate(lines):
            out.append(line)
            if line.strip().startswith("## DECISIONS") and not inserted:
                # Insert immediately after the DECISIONS header
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
    """Return .agents/skills/<doc_type>.md. v0.1: proposal only."""
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
            # Append at end of file under LESSONS
            text = text.rstrip() + "\n" + entry + "\n"
        path.write_text(text, encoding="utf-8")

        # Bump skills-lock version
        if SKILLS_LOCK.is_file():
            lock = json.loads(SKILLS_LOCK.read_text(encoding="utf-8"))
        else:
            lock = {"version": "0.1.0", "skills": {}}
        skill = lock.setdefault("skills", {}).setdefault(doc_type, {"file": f"{doc_type}.md", "version": "0.1.0"})
        ver = skill.get("version", "0.1.0")
        parts = ver.split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except ValueError:
            parts = ["0", "1", "1"]
        skill["version"] = ".".join(parts)
        # bump top-level patch too
        top = lock.get("version", "0.1.0").split(".")
        try:
            top[-1] = str(int(top[-1]) + 1)
        except ValueError:
            top = ["0", "1", "1"]
        lock["version"] = ".".join(top)
        SKILLS_LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
        return f"OK: lesson appended — {entry} (skill {doc_type} → {skill['version']})"
    except Exception as e:
        return _err(str(e))


@mcp.tool()
def read_brand_style(brand: str) -> str:
    """Return brand/<brand>/style.md. v0.1: jonatech-digital only."""
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
    """Return templates/<doc_type>.html source. ONLY render source. proposal only."""
    try:
        if doc_type not in ALLOWED_DOC_TYPES:
            return _err(f"doc_type must be one of {sorted(ALLOWED_DOC_TYPES)}")
        # Brand is fixed in v0.1
        path = BRAND_ROOT / "jonatech-digital" / "templates" / f"{doc_type}.html"
        if not path.is_file():
            return _err(f"template missing: {path}")
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return _err(str(e))


if __name__ == "__main__":
    # Keep stdout clean for MCP stdio — silence FastMCP banner if possible
    import os

    os.environ.setdefault("FASTMCP_SHOW_CLI_BANNER", "false")
    mcp.run(transport="stdio")
