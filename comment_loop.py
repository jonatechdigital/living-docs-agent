"""P2 moat: read Paper comments → edit → screenshot-verify → resolve → bank.

Used by the agent (via tools) and by `python comment_loop.py` for a deterministic pass
when open comments already exist on the demo file.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from mcp_client import MCPHub, ROOT


DEMO_FILE = "Jonatech Digital — Documents"


def _parse_all_json(text: str) -> list[Any]:
    text = (text or "").strip()
    if not text or text.startswith("ERROR"):
        return []
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    idx = 0
    out: list[Any] = []
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            out.append(obj)
            idx = end
        except json.JSONDecodeError:
            idx += 1
    return out


def _parse_jsonish(text: str) -> Any:
    objs = _parse_all_json(text)
    return objs[-1] if objs else None


def _find_file_id(resources_text: str, name: str) -> str | None:
    data = _parse_jsonish(resources_text)
    if not isinstance(data, dict):
        return None
    for r in data.get("resources") or []:
        if r.get("type") == "file" and r.get("name") == name:
            return r.get("id")
    return None


async def fix_open_comments(hub: MCPHub | None = None) -> str:
    """End-to-end comment loop. Returns a human-readable report."""
    own = hub is None
    hub = hub or MCPHub()
    if own:
        await hub.start()
    try:
        if not hub.paper_available:
            return "ERROR: Paper MCP unavailable — cannot fix comments."

        resources = await hub.call("paper_list_resources", {"limit": 100})
        file_id = _find_file_id(resources, DEMO_FILE)
        if not file_id:
            return f"ERROR: demo file '{DEMO_FILE}' not found. Render a proposal first."

        await hub.call("paper_open_file", {"fileId": file_id})
        listed = await hub.call(
            "paper_list_comment_threads",
            {"fileId": file_id, "status": "open"},
        )
        threads: list[dict] = []
        for data in _parse_all_json(listed):
            if isinstance(data, dict):
                chunk = (
                    data.get("threads")
                    or data.get("commentThreads")
                    or data.get("items")
                    or data.get("comment_threads")
                    or []
                )
                if not chunk and isinstance(data.get("result"), dict):
                    chunk = data["result"].get("threads") or data["result"].get(
                        "commentThreads"
                    ) or []
                if isinstance(chunk, list):
                    threads.extend(chunk)
            elif isinstance(data, list):
                threads.extend(data)

        # Only accept thread-shaped objects (never scrape bare file ids)
        cleaned: list[dict] = []
        for th in threads:
            if not isinstance(th, dict):
                continue
            tid = th.get("id") or th.get("commentThreadId") or th.get("threadId")
            if not tid or tid == file_id:
                continue
            cleaned.append(th)
        threads = cleaned

        if not threads:
            return (
                "No open comments on the canvas. Drop a comment in Paper "
                '(e.g. "logo too small — and add your TIN"), then say: fix my comments.'
            )

        report: list[str] = []
        for th in threads:
            tid = th.get("id") or th.get("commentThreadId") or th.get("threadId")
            if not tid:
                continue
            detail = await hub.call(
                "paper_get_comment_thread",
                {"commentThreadId": tid, "fileId": file_id},
            )
            detail_data = _parse_jsonish(detail) or {}
            # Collect comment text
            texts: list[str] = []
            raw = json.dumps(detail_data) if detail_data else detail
            for m in re.finditer(r'"(?:text|body|message|content)"\s*:\s*"([^"]+)"', raw):
                texts.append(m.group(1))
            blob = " ".join(texts).lower() or detail.lower()

            info = await hub.call("paper_get_basic_info", {"fileId": file_id})
            info_data = _parse_jsonish(info) or {}
            artboards = info_data.get("artboards") or []
            target = artboards[-1]["id"] if artboards else None

            fixed_bits: list[str] = []
            # Logo too small → enlarge logo nodes
            if "logo" in blob and ("small" in blob or "big" in blob or "size" in blob):
                if target:
                    # find logo-ish nodes via tree / children
                    children = await hub.call(
                        "paper_get_children",
                        {"nodeId": target, "fileId": file_id},
                    )
                    logo_ids = re.findall(
                        r'"id"\s*:\s*"([^"]+)".{0,120}?"(?:name|component)"\s*:\s*"(?:[^"]*[Ll]ogo[^"]*|Rectangle|Image)"',
                        children,
                        re.S,
                    )
                    if not logo_ids:
                        logo_ids = re.findall(r'"id"\s*:\s*"([^"]+)"', children)[:3]
                    if logo_ids:
                        await hub.call(
                            "paper_update_styles",
                            {
                                "fileId": file_id,
                                "updates": [
                                    {
                                        "nodeIds": logo_ids[:2],
                                        "styles": {"height": "64px", "width": "auto"},
                                    }
                                ],
                            },
                        )
                        fixed_bits.append("enlarged logo (~64px)")
                        await hub.call(
                            "append_lesson",
                            {
                                "doc_type": "proposal",
                                "lesson": "Default logo height 40px is too small for demo; prefer 56–64px on proposals.",
                            },
                        )
                        await hub.call(
                            "append_decision",
                            {"text": "Proposal logo default height = 64px (from comment feedback)."},
                        )

            # TIN missing → ensure footer text contains TIN
            if "tin" in blob:
                # Find text nodes mentioning Jonatech / footer
                tree = await hub.call(
                    "paper_get_tree_summary",
                    {"nodeId": target, "fileId": file_id} if target else {"fileId": file_id},
                )
                footer_ids = re.findall(r'"id"\s*:\s*"([^"]+)"', tree)
                # Prefer set_text on last text-ish; safer: write a footer note via update if we find content
                # Use find_nodes for "Jonatech Digital"
                found = await hub.call(
                    "paper_find_nodes",
                    {"fileId": file_id, "text": "Jonatech Digital"},
                )
                node_ids = re.findall(r'"id"\s*:\s*"([^"]+)"', found)
                if node_ids:
                    footer_line = (
                        "Jonatech Digital · TIN 1018475623 · hello@jonatech.digital "
                        "· +256 700 000 000 · Kampala"
                    )
                    await hub.call(
                        "paper_set_text_content",
                        {
                            "fileId": file_id,
                            "updates": [
                                {
                                    "nodeId": node_ids[-1],
                                    "textContent": footer_line,
                                }
                            ],
                        },
                    )
                    fixed_bits.append("footer TIN/contact enforced")
                    await hub.call(
                        "append_decision",
                        {"text": "Every proposal footer must include TIN 1018475623 + contact."},
                    )
                    await hub.call(
                        "append_lesson",
                        {
                            "doc_type": "proposal",
                            "lesson": "Before resolve, verify footer contains TIN and contact from style.md.",
                        },
                    )

            if target:
                shot = await hub.call(
                    "paper_get_screenshot",
                    {"nodeId": target, "fileId": file_id, "scale": 1},
                )
                verified = not shot.startswith("ERROR") and "Node not found" not in shot
            else:
                verified = False

            if fixed_bits and verified:
                await hub.call(
                    "paper_set_comment_thread_status",
                    {
                        "commentThreadId": tid,
                        "status": "resolved",
                        "fileId": file_id,
                    },
                )
                report.append(f"Resolved {tid}: {', '.join(fixed_bits)} (screenshot ok)")
            elif fixed_bits:
                report.append(f"Edited {tid}: {', '.join(fixed_bits)} but screenshot verify failed")
            else:
                report.append(
                    f"Thread {tid}: no auto-rule matched. Detail for model: {blob[:200]}"
                )

        await hub.call("paper_finish_working_on_nodes", {"fileId": file_id})
        return "\n".join(report) if report else "No actionable threads."
    finally:
        if own:
            await hub.close()


async def main() -> None:
    print(await fix_open_comments())


if __name__ == "__main__":
    asyncio.run(main())
