"""Stdio MCP client for Paper (`paper mcp`) and the Jonatech vault server."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent


def _paper_cli() -> str:
    env = os.environ.get("PAPER_CLI")
    if env and Path(env).exists():
        return env
    which = shutil.which("paper")
    if which:
        return which
    win = Path.home() / ".paper" / "bin" / "paper.exe"
    if win.exists():
        return str(win)
    unix = Path.home() / ".paper" / "bin" / "paper"
    if unix.exists():
        return str(unix)
    raise FileNotFoundError(
        "Paper CLI not found. Install Paper Desktop or set PAPER_CLI."
    )


@dataclass
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    server: str  # "vault" | "paper"


@dataclass
class MCPHub:
    """Manages vault + Paper MCP sessions."""

    tools: dict[str, ToolInfo] = field(default_factory=dict)
    paper_guide: str | None = None
    paper_available: bool = False
    vault_available: bool = False
    _stack: AsyncExitStack | None = None
    _sessions: dict[str, ClientSession] = field(default_factory=dict)

    async def start(self) -> None:
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        # --- Vault (always) ---
        vault_env = {
            **os.environ,
            "FASTMCP_SHOW_CLI_BANNER": "false",
            "NO_COLOR": "1",
        }
        vault_params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "vault_server.py")],
            cwd=str(ROOT),
            env=vault_env,
        )
        try:
            vault_transport = await self._stack.enter_async_context(
                stdio_client(vault_params)
            )
            vault_read, vault_write = vault_transport
            vault_session = await self._stack.enter_async_context(
                ClientSession(vault_read, vault_write)
            )
            await vault_session.initialize()
            self._sessions["vault"] = vault_session
            self.vault_available = True
            await self._register_tools("vault", vault_session)
        except Exception as e:
            print(f"[mcp] vault failed to start: {e}", file=sys.stderr)

        # --- Paper ---
        try:
            paper_cmd = _paper_cli()
            paper_params = StdioServerParameters(
                command=paper_cmd,
                args=["mcp"],
                env={**os.environ},
            )
            paper_transport = await self._stack.enter_async_context(
                stdio_client(paper_params)
            )
            paper_read, paper_write = paper_transport
            paper_session = await self._stack.enter_async_context(
                ClientSession(paper_read, paper_write)
            )
            await paper_session.initialize()
            self._sessions["paper"] = paper_session
            self.paper_available = True
            await self._register_tools("paper", paper_session)
            # Mandatory once per session
            try:
                guide = await paper_session.call_tool(
                    "get_guide", {"topic": "paper-mcp-instructions"}
                )
                raw = _tool_result_text(guide)
                # Keep a usable slice for the model context (full guide is huge)
                self.paper_guide = raw if len(raw) <= 14000 else (
                    raw[:14000] + "\n…[guide truncated — call paper_get_guide for more]"
                )
            except Exception as e:
                print(f"[mcp] get_guide failed: {e}", file=sys.stderr)
        except Exception as e:
            print(
                f"[mcp] Paper MCP unavailable ({e}). "
                "Will announce once and use sandbox preview fallback.",
                file=sys.stderr,
            )
            self.paper_available = False

        self._print_surface()

    async def _register_tools(self, server: str, session: ClientSession) -> None:
        listed = await session.list_tools()
        for t in listed.tools:
            # Prefix paper tools to avoid collisions; vault keeps bare names
            if server == "paper":
                key = t.name if not t.name.startswith("paper_") else t.name
                # expose as paper_<name> to model if not already
                exposed = t.name if t.name.startswith("paper_") else f"paper_{t.name}"
            else:
                exposed = t.name
            # MCP SDK uses input_schema; older code used inputSchema
            raw_schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)
            schema = raw_schema if isinstance(raw_schema, dict) else {}
            self.tools[exposed] = ToolInfo(
                name=t.name,  # actual MCP tool name
                description=t.description or "",
                input_schema=schema,
                server=server,
            )

    def _print_surface(self) -> None:
        print("\n=== MCP tool surface ===")
        by = {"vault": [], "paper": []}
        for exposed, info in sorted(self.tools.items()):
            by.setdefault(info.server, []).append(exposed)
        for server, names in by.items():
            print(f"  [{server}] ({len(names)}): {', '.join(names)}")
        print("========================\n")

    def openai_tools(self) -> list[dict[str, Any]]:
        """Convert discovered tools to OpenAI function-calling schemas."""
        out = []
        for exposed, info in self.tools.items():
            params = info.input_schema or {"type": "object", "properties": {}}
            if "type" not in params:
                params = {**params, "type": "object"}
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": exposed,
                        "description": info.description[:500]
                        or f"{info.server} tool {info.name}",
                        "parameters": params,
                    },
                }
            )
        return out

    async def call(self, exposed_name: str, arguments: dict[str, Any] | str) -> str:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return f"ERROR: invalid JSON arguments: {arguments[:200]}"
        info = self.tools.get(exposed_name)
        if not info:
            # allow calling bare paper name
            bare = exposed_name.removeprefix("paper_")
            for k, v in self.tools.items():
                if v.server == "paper" and v.name == bare:
                    info = v
                    break
        if not info:
            return f"ERROR: unknown tool '{exposed_name}'"
        session = self._sessions.get(info.server)
        if not session:
            return f"ERROR: server '{info.server}' not connected"
        try:
            result = await session.call_tool(info.name, arguments or {})
            return _tool_result_text(result)
        except Exception as e:
            return f"ERROR calling {exposed_name}: {e}"

    async def close(self) -> None:
        if self._stack:
            await self._stack.aclose()
            self._stack = None


_LAST_IMAGE_PATH: Path | None = None


def last_image_path() -> Path | None:
    return _LAST_IMAGE_PATH


def _tool_result_text(result: Any) -> str:
    """Flatten MCP CallToolResult into a string (text + image notes)."""
    global _LAST_IMAGE_PATH
    parts: list[str] = []
    content = getattr(result, "content", None) or []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text" or (
            hasattr(block, "text") and getattr(block, "text", None) is not None and btype != "image"
        ):
            parts.append(getattr(block, "text", str(block)))
        elif btype == "image" or (hasattr(block, "data") and getattr(block, "data", None)):
            mime = getattr(block, "mimeType", None) or getattr(block, "mime_type", "image/png")
            data = getattr(block, "data", "") or ""
            parts.append(f"[image:{mime} len={len(data)}]")
            # Persist latest screenshot for demo evidence
            try:
                import base64

                ext = "jpg" if "jpeg" in (mime or "") else "png"
                out = ROOT / "docs" / "demo" / f"last-screenshot.{ext}"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(base64.b64decode(data))
                _LAST_IMAGE_PATH = out
                parts.append(f"[saved:{out.as_posix()}]")
            except Exception as e:
                parts.append(f"[save-failed:{e}]")
        else:
            parts.append(str(block))
    if getattr(result, "isError", False):
        return "ERROR: " + ("\n".join(parts) if parts else "tool error")
    sc = getattr(result, "structuredContent", None)
    if sc and not parts:
        return json.dumps(sc, ensure_ascii=False)
    return "\n".join(parts) if parts else json.dumps(
        {"ok": True, "structured": sc}, default=str
    )


async def smoke_list() -> None:
    hub = MCPHub()
    await hub.start()
    print(f"vault={hub.vault_available} paper={hub.paper_available}")
    if hub.paper_guide:
        print(f"guide chars={len(hub.paper_guide)}")
    await hub.close()


if __name__ == "__main__":
    asyncio.run(smoke_list())
