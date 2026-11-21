"""P1 smoke: wake vault → fill proposal.html → write to Paper → screenshot check.

Runs without Grok so we can prove the spine even before API keys are set.
Usage: python smoke_p1.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import date
from pathlib import Path

from jinja2 import Template

from mcp_client import MCPHub, ROOT

DEMO_FILE = "Jonatech Digital — Documents"


def fill_proposal() -> str:
    tpl_path = ROOT / "brand" / "jonatech-digital" / "templates" / "proposal.html"
    logo = ROOT / "brand" / "jonatech-digital" / "assets" / "jonatech-logo-original.png"
    if not logo.is_file():
        raise SystemExit(f"Real logo missing: {logo}")
    logo_src = "data:image/png;base64," + base64.b64encode(logo.read_bytes()).decode("ascii")
    return Template(tpl_path.read_text(encoding="utf-8")).render(
        logo_src=logo_src,
        proposal_date=date.today().isoformat(),
        title="Cursor Workshop Training",
        client_name="Ronnie",
        engagement_type="Half-day Cursor workshop facilitation",
        scope_items=[
            "Live facilitation of Cursor workflows for AI builders",
            "Hands-on agent / MCP productivity patterns",
            "Q&A and team playbook handoff",
        ],
        price="$500",
        terms=[
            "50% on acceptance; 50% on delivery.",
            "Scope locked to this proposal; changes re-quoted.",
            "Valid 14 days from proposal date.",
        ],
        next_step="Reply to accept and we lock the workshop date.",
        footer_line=(
            "Jonatech Digital · TIN 1018475623 · hello@jonatech.digital "
            "· +256 700 000 000 · Kampala"
        ),
    )


def _parse_jsonish(text: str):
    """Parse Paper tool text that may contain one or more JSON objects."""
    text = (text or "").strip()
    if not text or text.startswith("ERROR") or "Invalid arguments" in text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Paper often returns two JSON objects back-to-back — take the last valid one
    decoder = json.JSONDecoder()
    idx = 0
    last = None
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            last = obj
            idx = end
        except json.JSONDecodeError:
            idx += 1
    return last


def _find_file_id(resources_text: str, name: str) -> str | None:
    data = _parse_jsonish(resources_text)
    if not isinstance(data, dict):
        return None
    for r in data.get("resources") or []:
        if r.get("type") == "file" and r.get("name") == name:
            return r.get("id")
    return None


async def ensure_demo_file(hub: MCPHub) -> str:
    resources = await hub.call("paper_list_resources", {"limit": 100})
    print("resources head:", resources[:240])
    fid = _find_file_id(resources, DEMO_FILE)
    if fid:
        print("found existing file:", fid)
        return fid
    created = await hub.call("paper_create_file", {"name": DEMO_FILE})
    print("create_file:", created[:500])
    data = _parse_jsonish(created)
    if isinstance(data, dict):
        fid = data.get("id") or data.get("fileId") or (data.get("file") or {}).get("id")
        if fid:
            return fid
    # re-list
    resources = await hub.call("paper_list_resources", {"limit": 100})
    fid = _find_file_id(resources, DEMO_FILE)
    if fid:
        return fid
    raise SystemExit(f"Could not create/find {DEMO_FILE}\n{created}")


async def run() -> None:
    hub = MCPHub()
    await hub.start()
    assert hub.vault_available, "vault failed"
    print("wake: load_brain", flush=True)
    brain = await hub.call("load_brain", {})
    assert "STATUS" in brain, brain
    print("wake: load_knowledge", flush=True)
    knowledge = await hub.call("load_knowledge", {})
    assert "Jonatech" in knowledge
    print("wake: read_skill", flush=True)
    skill = await hub.call("read_skill", {"doc_type": "proposal"})
    assert "LESSONS" in skill
    print("wake: read_brand_style", flush=True)
    style = await hub.call("read_brand_style", {"brand": "jonatech-digital"})
    assert "#00AA3E" in style or "#1A2D2B" in style

    if not hub.paper_available:
        raise SystemExit("Paper MCP not available")
    if hub.paper_guide and "isn't running" in (hub.paper_guide or ""):
        raise SystemExit("Paper Desktop isn't running. Open it, then re-run.")

    file_id = await ensure_demo_file(hub)
    opened = await hub.call("paper_open_file", {"fileId": file_id})
    print("open:", opened[:400])
    open_data = _parse_jsonish(opened) or {}

    page = await hub.call(
        "paper_create_page",
        {
            "fileId": file_id,
            "name": f"Proposal — Ronnie {date.today().isoformat()}",
        },
    )
    print("page:", page[:500])
    page_data = _parse_jsonish(page) or {}
    page_id = page_data.get("pageId") or page_data.get("id")
    if page_id:
        await hub.call("paper_open_file", {"fileId": file_id, "pageId": page_id})

    artboard_args = {
        "fileId": file_id,
        "name": "Proposal A4",
        "styles": {
            "width": "794px",
            "height": "1123px",
            "backgroundColor": "#F7F4EF",
        },
    }
    if page_id:
        artboard_args["pageId"] = page_id
    artboard = await hub.call("paper_create_artboard", artboard_args)
    print("artboard:", artboard[:600])
    ab = _parse_jsonish(artboard) or {}
    target = ab.get("id") or ab.get("nodeId") or ab.get("artboardId")
    if not target and isinstance(ab.get("artboard"), dict):
        target = ab["artboard"].get("id")

    if not target:
        info = await hub.call(
            "paper_get_basic_info",
            {"fileId": file_id, **({"pageId": page_id} if page_id else {})},
        )
        print("basic_info:", info[:800])
        info_data = _parse_jsonish(info) or {}
        arts = info_data.get("artboards") or []
        if arts:
            target = arts[-1].get("id")
        if not target:
            raise SystemExit(f"No artboard target.\n{artboard}")

    print("targetNodeId:", target)
    html = fill_proposal()
    # Prefer body inner HTML for Paper layers; inline styles already on template
    body_m = re.search(r"<body[^>]*>([\s\S]*)</body>", html, re.I)
    fragment = body_m.group(1).strip() if body_m else html
    # Drop external font <link> leftovers if any slipped into body
    fragment = re.sub(r"<link[^>]*>", "", fragment)

    print("writing html chars:", len(fragment))
    written = await hub.call(
        "paper_write_html",
        {
            "html": fragment,
            "targetNodeId": target,
            "mode": "insert-children",
            "fileId": file_id,
        },
    )
    print("write_html:", written[:600])
    if written.startswith("ERROR") or "Invalid arguments" in written:
        raise SystemExit(f"write_html failed:\n{written}")

    shot = await hub.call(
        "paper_get_screenshot",
        {"nodeId": target, "fileId": file_id, "scale": 1},
    )
    print("screenshot:", shot[:240])
    if shot.startswith("ERROR") or "Node not found" in shot or "Invalid arguments" in shot:
        raise SystemExit(f"screenshot failed:\n{shot}")

    assert "TIN 1018475623" in html
    assert "#00AA3E" in html or "#1A2D2B" in html

    finish = await hub.call("paper_finish_working_on_nodes", {"fileId": file_id})
    print("finish:", finish[:200])

    demo_dir = ROOT / "docs" / "demo"
    preview = demo_dir / "proposal-preview.html"
    preview.write_text(html, encoding="utf-8")

    # Persist raw image from MCP if the hub left binary aside — best-effort via re-call storage
    shot_path = demo_dir / "p1-proposal-screenshot.txt"
    shot_path.write_text(shot[:500] + "\n…", encoding="utf-8")

    print("\nP1 SMOKE PASS")
    print(f"File: {DEMO_FILE} ({file_id})")
    print(f"Preview: {preview}")
    print("STOP AND SHOW JONATECH — branded proposal should be on the Paper canvas.")
    await hub.close()


if __name__ == "__main__":
    asyncio.run(run())
