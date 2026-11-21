"""Living Docs Agent — chat → Grok (function calling) → vault + Paper tools → reply."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import toml
from dotenv import load_dotenv
from openai import OpenAI

from mcp_client import MCPHub, ROOT

SYSTEM_PROMPT = """You are Living Docs Agent — a document team member employed by Jonatech Digital.
You are BORN knowing only your employer (Jonatech Digital brand vault + services).
Everything else (clients, meeting facts, inspiration grammar) you BANK live through conversation.

## Wake-up (before ANY render)
In order: (1) load_brain, (2) load_knowledge, (3) read_skill("proposal"),
(4) read_brand_style("jonatech-digital"), (5) read_inspirations.
If load_brain returns "⚠️ BRAIN NOT LOADED" — announce it and REFUSE to render.

## Render v2
- CONTENT = user request + banked knowledge + meeting notes.
- STRUCTURE = latest inspirations.md pattern if present; ELSE templates/proposal.html via read_template.
- BRAND = ALWAYS style.md + brand assets. Inspiration NEVER sets colors, fonts, or logo.
Logo file (light paper): brand/jonatech-digital/assets/jonatech-logo-original.png
Embed as data URI or path Paper accepts. Footer MUST include TIN + contact from style.md.

## Banking (silent bank, mention briefly in reply)
- client FACT → append_knowledge / ingest_meeting_notes / study_client_website
- durable PREFERENCE → append_decision
- document PROCEDURE → append_lesson("proposal", ...)
- inspiration layout → study_inspiration(path)  [grammar only]

When user pastes meeting notes → ingest_meeting_notes; ask ONLY for fields in "missing".
When user shares a URL → study_client_website.
When user says inspo: uploads/<name> or gives a path → study_inspiration.
Never invent missing client facts.

## Paper
Tools use paper_ prefix. ALWAYS pass fileId on mutating tools.
Target file: "Jonatech Digital — Documents" (create if missing).
One proposal = new page + A4 artboard (794x1123) → write_html → get_screenshot → finish_working_on_nodes.

## Fix my comments (THE MOAT)
1. paper_list_comment_threads (status=open) on the file
2. For EACH: paper_get_comment_thread → edit layers (update_styles / set_text_content / write_html)
3. paper_get_screenshot verify
4. If durable preference: append_decision AND/OR append_lesson BEFORE resolve
5. paper_set_comment_thread_status → resolved
6. Report what you fixed

Scope: PROPOSALS ONLY. Be concise."""

MAX_TOOL_ROUNDS = 28


def load_config() -> dict:
    cfg_path = ROOT / "config.toml"
    if cfg_path.is_file():
        return toml.load(cfg_path)
    return {"model": {"provider": "xai", "name": "grok-4-fast"}}


def make_client(cfg: dict) -> tuple[OpenAI, str]:
    model_cfg = cfg.get("model", {})
    provider = (model_cfg.get("provider") or "xai").lower()
    name = model_cfg.get("name") or "grok-4-fast"
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY missing in .env")
        base = model_cfg.get("base_url_openrouter") or "https://openrouter.ai/api/v1"
        return OpenAI(api_key=key, base_url=base), name
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        raise RuntimeError("XAI_API_KEY missing in .env")
    base = model_cfg.get("base_url_xai") or "https://api.x.ai/v1"
    return OpenAI(api_key=key, base_url=base), name


class DocsAgent:
    def __init__(self) -> None:
        load_dotenv(ROOT / ".env")
        self.cfg = load_config()
        self.client, self.model = make_client(self.cfg)
        self.hub = MCPHub()
        self.messages: list[dict] = []
        self._paper_announced = False
        self._guide_injected = False

    async def start(self) -> None:
        await self.hub.start()
        sys_content = SYSTEM_PROMPT
        logo = (
            ROOT
            / "brand"
            / "jonatech-digital"
            / "assets"
            / "jonatech-logo-original.png"
        )
        sys_content += f"\n\nAbsolute logo path: {logo.as_posix()}"
        if self.hub.paper_guide:
            guide = self.hub.paper_guide
            if len(guide) > 12000:
                guide = guide[:12000] + "\n…[guide truncated for context]"
            sys_content += (
                "\n\n--- Paper MCP instructions (loaded once this session) ---\n" + guide
            )
            self._guide_injected = True
        if not self.hub.paper_available and not self._paper_announced:
            sys_content += (
                "\n\nNOTE: Paper MCP is NOT connected. Announce this once. "
                "Do not invent Paper writes; offer sandbox preview via vault template fill."
            )
            self._paper_announced = True
        self.messages = [{"role": "system", "content": sys_content}]

    async def close(self) -> None:
        await self.hub.close()

    async def chat(self, user_text: str) -> str:
        # Fast-path for comment moat without burning model rounds when asked explicitly
        low = user_text.strip().lower()
        if low in {"fix my comments", "fix comments", "resolve comments"}:
            from comment_loop import fix_open_comments

            report = await fix_open_comments(self.hub)
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": report})
            return report

        self.messages.append({"role": "user", "content": user_text})
        tools = self.hub.openai_tools()
        for _ in range(MAX_TOOL_ROUNDS):
            kwargs: dict = {
                "model": self.model,
                "messages": self.messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                err = f"Model call failed: {e}. Retry or check API key / network."
                self.messages.append({"role": "assistant", "content": err})
                return err

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = msg.tool_calls or []

            if not tool_calls:
                text = msg.content or ""
                self.messages.append({"role": "assistant", "content": text})
                return text

            self.messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                name = tc.function.name
                args_raw = tc.function.arguments or "{}"
                print(
                    f"  → tool {name}({args_raw[:120]}{'…' if len(args_raw) > 120 else ''})"
                )
                result = await self.hub.call(name, args_raw)
                stored = result
                if len(stored) > 8000 and "[image:" in stored:
                    stored = stored[:500] + "\n…[screenshot truncated in history]"
                elif len(stored) > 16000:
                    stored = stored[:16000] + "\n…[truncated]"
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": stored,
                    }
                )

        final = "Stopped: too many tool rounds. Try again with a narrower request."
        self.messages.append({"role": "assistant", "content": final})
        return final


async def terminal_loop() -> None:
    print("Living Docs Agent — terminal chat. Ctrl+C or 'quit' to exit.\n")
    agent = DocsAgent()
    try:
        await agent.start()
        print(
            f"Model: {agent.model} | vault={agent.hub.vault_available} | "
            f"paper={agent.hub.paper_available}\n"
        )
        while True:
            try:
                line = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in {"quit", "exit", "q"}:
                break
            reply = await agent.chat(line)
            print(f"\ndocs> {reply}\n")
    finally:
        await agent.close()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"--smoke", "smoke"}:
        from smoke_p1 import run as smoke_run

        asyncio.run(smoke_run())
        return
    if len(sys.argv) > 1 and sys.argv[1] in {"--fix-comments", "fix-comments"}:
        from comment_loop import main as fix_main

        asyncio.run(fix_main())
        return
    load_dotenv(ROOT / ".env")
    if not os.environ.get("XAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "No XAI_API_KEY / OPENROUTER_API_KEY in .env.\n"
            "Copy .env.example → .env and add a key, or run:\n"
            "  python agent.py --smoke\n"
            "  python agent.py --fix-comments"
        )
        sys.exit(2)
    asyncio.run(terminal_loop())


if __name__ == "__main__":
    main()
