"""Jonatech Docs Agent — chat → Grok (function calling) → vault + Paper tools → reply."""

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

SYSTEM_PROMPT = """You are Jonatech Docs Agent — a document team member for Jonatech Digital.
Before ANY render you MUST, in order: (1) load_brain, (2) load_knowledge,
(3) read_skill("proposal"), (4) read_brand_style("jonatech-digital").
If load_brain returns "⚠️ BRAIN NOT LOADED" — announce it and REFUSE to render.
You never invent brand: template comes from read_template, content comes from
the user request + knowledge. Render onto the Paper drafts file, one page per
proposal, then get_screenshot and self-check before replying.

Paper tools are exposed with a paper_ prefix (e.g. paper_write_html, paper_get_screenshot,
paper_create_page, paper_create_artboard, paper_get_guide, paper_finish_working_on_nodes,
paper_list_resources, paper_open_file). Follow the paper-mcp-instructions guide already
loaded this session. After writing, always call paper_finish_working_on_nodes.
Target file name: "Jonatech Digital — Documents" (create via paper_create_file if missing).
One proposal = one new page + A4 artboard (794x1123), then write_html into the artboard.
ALWAYS pass fileId on Paper mutating tools (create_page, create_artboard, write_html,
get_screenshot, finish_working_on_nodes).

Scope lock: PROPOSALS ONLY. One template via read_template("proposal").
Logo path for embeds: use the absolute path under brand/jonatech-digital/assets/logo.svg
(or a file:// URL / paper-compatible image reference as the Paper guide specifies).
Footer must include TIN and contact from knowledge.

When the user says "fix my comments": list comment threads, for each edit layers,
screenshot-verify, then resolve. Durable preferences → append_decision (facts) and
append_lesson("proposal", ...) (procedure) BEFORE resolving.

Be concise. Report what you rendered and the self-check result."""

MAX_TOOL_ROUNDS = 24


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
        logo = ROOT / "brand" / "jonatech-digital" / "assets" / "logo.svg"
        sys_content += f"\n\nAbsolute logo path: {logo.as_posix()}"
        if self.hub.paper_guide:
            # Cap guide size so context stays usable
            guide = self.hub.paper_guide
            if len(guide) > 12000:
                guide = guide[:12000] + "\n…[guide truncated for context]"
            sys_content += (
                "\n\n--- Paper MCP instructions (loaded once this session) ---\n" + guide
            )
            self._guide_injected = True
        if not self.hub.paper_available and not self._paper_announced:
            sys_content += (
                "\n\nNOTE: Paper MCP is NOT connected. Announce this once to the user. "
                "Do not invent Paper writes. Offer a sandbox HTML preview summary instead "
                "(fill template via vault tools, describe what would render)."
            )
            self._paper_announced = True
        self.messages = [{"role": "system", "content": sys_content}]

    async def close(self) -> None:
        await self.hub.close()

    async def chat(self, user_text: str) -> str:
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

            # Persist assistant tool-call turn
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
                print(f"  → tool {name}({args_raw[:120]}{'…' if len(args_raw) > 120 else ''})")
                result = await self.hub.call(name, args_raw)
                # Truncate huge screenshot payloads for chat history
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
    print("Jonatech Docs Agent — terminal chat. Ctrl+C or 'quit' to exit.\n")
    agent = DocsAgent()
    try:
        await agent.start()
        print(f"Model: {agent.model} | vault={agent.hub.vault_available} | paper={agent.hub.paper_available}\n")
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
    load_dotenv(ROOT / ".env")
    if not os.environ.get("XAI_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        print(
            "No XAI_API_KEY / OPENROUTER_API_KEY in .env.\n"
            "Copy .env.example → .env and add a key, or run: python agent.py --smoke"
        )
        sys.exit(2)
    asyncio.run(terminal_loop())


if __name__ == "__main__":
    main()
