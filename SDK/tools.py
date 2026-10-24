"""Shared domain tools wrapped as an in-process MCP server, plus memory kept in CLAUDE.md.

Lines tagged `# replaces: <part>` are what stands in for API/harness/<part>.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from shared.tools_spec import SPECS, ToolContext, compact, invoke

SERVER = "shabbat"
MEMORY_HEADER = "## Host memory"
_LINE = re.compile(r"^- \[(?P<key>[^\]]+)\] (?P<value>.*)$")

CLAUDE_MD_TEMPLATE = f"""# Shabbat Host - project memory
Loaded by Claude Code at session start (setting_sources=["project"]).
Entries below are written by the `remember` tool; the same key is overwritten, never duplicated.

{MEMORY_HEADER}
"""


def _ok(text: str) -> dict:  # replaces: tools
    return {"content": [{"type": "text", "text": text}]}  # replaces: tools


def _err(e: Exception) -> dict:  # replaces: tools
    return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "is_error": True}  # replaces: tools


def _wrap(spec, ctx: ToolContext):  # replaces: tools
    @tool(spec.name, spec.description, spec.schema)  # replaces: tools
    async def handler(args: dict) -> dict:  # replaces: tools
        try:  # replaces: tools
            return _ok(invoke(spec, ctx, args))  # replaces: tools
        except Exception as e:  # noqa: BLE001  # replaces: tools
            return _err(e)  # replaces: tools

    return handler  # replaces: tools


# ---- memory: a section of CLAUDE.md --------------------------------------
def init_memory_file(path: Path) -> None:  # replaces: memory
    if not path.exists():  # replaces: memory
        path.write_text(CLAUDE_MD_TEMPLATE, encoding="utf-8")  # replaces: memory


def read_memory(path: Path) -> dict:  # replaces: memory
    if not path.exists():  # replaces: memory
        return {}  # replaces: memory
    return {m["key"]: m["value"] for m in map(_LINE.match, path.read_text(encoding="utf-8").splitlines()) if m}  # replaces: memory


def upsert_memory(path: Path, key: str, value: str) -> dict:  # replaces: memory
    key, value = key.strip(), " ".join(str(value).split())  # replaces: memory
    if not key or not value:  # replaces: memory
        raise ValueError("key and value are required")  # replaces: memory
    init_memory_file(path)  # replaces: memory
    lines = path.read_text(encoding="utf-8").splitlines()  # replaces: memory
    old = read_memory(path).get(key)  # replaces: memory
    new_line = f"- [{key}] {value}"  # replaces: memory
    idx = next((i for i, l in enumerate(lines) if l.startswith(f"- [{key}] ")), None)  # replaces: memory
    if idx is None:  # replaces: memory
        lines.append(new_line)  # replaces: memory
    else:  # replaces: memory
        lines[idx] = new_line  # replaces: memory
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")  # replaces: memory
    return {"saved": key, **({"replaced": old} if old and old != value else {})}  # replaces: memory


def _remember_tool(memory_file: Path):  # replaces: memory
    @tool("remember", "Store or overwrite a lasting host preference/decision. Same key = overwrite.",  # replaces: memory
          {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},  # replaces: memory
           "required": ["key", "value"]})  # replaces: memory
    async def remember(args: dict) -> dict:  # replaces: memory
        try:  # replaces: memory
            return _ok(compact(upsert_memory(memory_file, args.get("key", ""), args.get("value", ""))))  # replaces: memory
        except Exception as e:  # noqa: BLE001  # replaces: memory
            return _err(e)  # replaces: memory

    return remember  # replaces: memory


def build_server(ctx: ToolContext, memory_file: Path):  # replaces: tools
    tools = [_wrap(s, ctx) for s in SPECS]  # replaces: tools
    tools.append(_remember_tool(memory_file))  # replaces: memory
    LAST_BUILT.clear()
    LAST_BUILT.update({t.name: t for t in tools})  # handle for offline tests (the fake client calls handlers)
    return create_sdk_mcp_server(SERVER, tools=tools)  # replaces: tools


LAST_BUILT: dict = {}


def allowed_tool_names() -> list[str]:  # replaces: tools
    return [f"mcp__{SERVER}__{s.name}" for s in SPECS] + [f"mcp__{SERVER}__remember"]  # replaces: tools
