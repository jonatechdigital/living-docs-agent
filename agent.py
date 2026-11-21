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
    return {"model": {"provider": "google", "name": "gemini-flash-latest"}}


def _read_key_file(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        return ""
    # Support raw key or KEY=value lines
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.startswith("AIza") and not line.startswith("AQ."):
            line = line.split("=", 1)[1].strip().strip('"').strip("'")
        return line
    return ""


def _resolve_api_key(model_cfg: dict, env_names: list[str]) -> str:
    for name in env_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    key_file = model_cfg.get("key_file") or os.environ.get("GOOGLE_API_KEY_FILE", "")
    if key_file:
        return _read_key_file(key_file)
    return ""


def make_client(cfg: dict) -> tuple[OpenAI, str]:
    model_cfg = cfg.get("model", {})
    provider = (model_cfg.get("provider") or "google").lower()
    name = model_cfg.get("name") or "gemini-flash-latest"

    if provider in {"google", "gemini", "google-ai-studio"}:
        key = _resolve_api_key(
            model_cfg, ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_AI_API_KEY"]
        )
        if not key:
            raise RuntimeError(
                "Google AI key missing. Set GOOGLE_API_KEY or key_file in config.toml"
            )
        base = (
            model_cfg.get("base_url_google")
            or "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        return OpenAI(api_key=key, base_url=base), name

    if provider == "openrouter":
        key = _resolve_api_key(model_cfg, ["OPENROUTER_API_KEY"])
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY missing in .env")
        base = model_cfg.get("base_url_openrouter") or "https://openrouter.ai/api/v1"
        return OpenAI(api_key=key, base_url=base), name

    # xai (default fallback)
    key = _resolve_api_key(model_cfg, ["XAI_API_KEY"])
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

    def _assistant_tool_message(self, msg) -> dict:
        """Preserve Gemini thought_signature / extra_content on tool_calls (required)."""
        if hasattr(msg, "model_dump"):
            dumped = msg.model_dump(exclude_none=True)
            # Drop null noise; keep tool_calls exactly as returned
            out = {"role": "assistant", "content": dumped.get("content") or ""}
            if dumped.get("tool_calls"):
                out["tool_calls"] = dumped["tool_calls"]
            return out
        # Fallback (non-pydantic)
        return {
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
                for tc in (msg.tool_calls or [])
            ],
        }

    async def chat(self, user_text: str) -> str:
        # Fast-path for comment moat without burning model rounds when asked explicitly
        low = user_text.strip().lower()
        if low in {"fix my comments", "fix comments", "resolve comments"}:
            from comment_loop import fix_open_comments

            report = await fix_open_comments(self.hub)
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": report})
            return report

        # Fast-path: inspo upload — bank grammar without a full tool loop
        if low.startswith("inspo:"):
            path = user_text.split(":", 1)[1].strip()
            if path.lower().endswith((".md", ".txt")):
                reply = (
                    f"That looks like notes ({path}), not a layout image. "
                    "Paste the meeting notes as chat text instead of Upload inspiration."
                )
                self.messages.append({"role": "user", "content": user_text})
                self.messages.append({"role": "assistant", "content": reply})
                return reply
            result = await self.hub.call("study_inspiration", {"path": path})
            # If vision needs grammar, bank a brochure-safe default for demo
            if '"need_user"' in result or '"ok": false' in result.lower():
                result = await self.hub.call(
                    "study_inspiration",
                    {
                        "path": path,
                        "grammar_text": (
                            "Brochure structure: sectioned spreads, airy whitespace, "
                            "title + dominant visual above fold, services as tile grid, "
                            "pricing as card row near end, footer/contact close. "
                            "Use this STRUCTURE only — Jonatech brand colors/logo."
                        ),
                    },
                )
            reply = f"Inspiration banked (layout grammar only).\n{result[:1200]}"
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": reply})
            return reply

        # Fast-path: bare URL → study website
        if user_text.strip().startswith("http://") or user_text.strip().startswith(
            "https://"
        ):
            result = await self.hub.call(
                "study_client_website", {"url": user_text.strip()}
            )
            reply = f"Website studied / banked.\n{result[:1200]}"
            self.messages.append({"role": "user", "content": user_text})
            self.messages.append({"role": "assistant", "content": reply})
            return reply

        self.messages.append({"role": "user", "content": user_text})
        tools = self.hub.openai_tools()
        # Gemini OpenAI compat: strip unsupported JSON-schema keys that can 400
        for t in tools:
            params = t.get("function", {}).get("parameters") or {}
            params.pop("$schema", None)
            t["function"]["parameters"] = params

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
                # Drop the failed user turn's broken history tail if prior tool sig missing
                self.messages.append({"role": "assistant", "content": err})
                return err

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = msg.tool_calls or []

            if not tool_calls:
                text = msg.content or ""
                self.messages.append({"role": "assistant", "content": text})
                return text

            self.messages.append(self._assistant_tool_message(msg))

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
    cfg = load_config()
    try:
        make_client(cfg)
    except RuntimeError as e:
        print(
            f"{e}\n"
            "Or run without a model:\n"
            "  python agent.py --smoke\n"
            "  python agent.py --fix-comments"
        )
        sys.exit(2)
    asyncio.run(terminal_loop())


if __name__ == "__main__":
    main()
