"""Shabbat Host on the Claude Agent SDK: Claude Code runs the harness, we only configure it.

A new SDKShabbatAgent = a new session. Continuity comes from Claude Code's own session
store (resume=session_id) and from CLAUDE.md, which Claude Code loads by itself.
Lines tagged `# replaces: <part>` stand in for API/harness/<part>.py.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, ToolUseBlock,
)

from shared import config, domain  # noqa: E402
from shared.prompt import BASE_SYSTEM_PROMPT, SDK_MEMORY_NOTE  # noqa: E402
from shared.store import Store  # noqa: E402
from shared.tools_spec import ToolContext  # noqa: E402

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("sdk_tools", Path(__file__).resolve().parent / "tools.py")
sdk_tools = sys.modules.setdefault("sdk_tools", importlib.util.module_from_spec(_spec))
if not hasattr(sdk_tools, "build_server"):
    _spec.loader.exec_module(sdk_tools)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def log(msg: str) -> None:
    print(f"[SDK/agent.py] {msg}", file=sys.stderr, flush=True)


@dataclass
class TurnResult:
    answer: str
    usage: dict
    cost: float
    reported_cost: float | None
    model_calls: int
    tools: list
    seconds: float
    session_id: str | None
    model_usage: dict | None


def usage_from_result(u: dict | None) -> dict:
    u = u or {}  # replaces: tokens
    return {"input": u.get("input_tokens", 0) or 0, "cache_read": u.get("cache_read_input_tokens", 0) or 0,  # replaces: tokens
            "cache_write": u.get("cache_creation_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}  # replaces: tokens


def cost_from_usage(u: dict, model: str) -> float:
    p = config.price_for(model)  # same price table as the API version, for a fair comparison
    return (u["input"] * p["input"] + u["cache_read"] * p["cache_read"] + u["cache_write"] * p["cache_write"]
            + u["output"] * p["output"]) / 1_000_000


class SDKShabbatAgent:
    def __init__(self, state_dir: str | Path, *, session: int = 1, today: dt.date | None = None,
                 model: str = config.MODEL, effort: str = config.EFFORT, client_cls=ClaudeSDKClient, fetch=None):
        self.dir = Path(state_dir)
        self.model, self.effort, self.client_cls = model, effort, client_cls
        self.today = today or dt.date.today()
        self.store = Store(self.dir / "domain", session=session)
        self.workdir = self.dir / "sdk" / "workdir"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.workdir / "CLAUDE.md"
        sdk_tools.init_memory_file(self.memory_file)  # replaces: memory
        self.session_file = self.dir / "sdk" / "session.json"
        ctx = ToolContext(self.store, self.today, **({"fetch": fetch} if fetch else {}))
        self.server = sdk_tools.build_server(ctx, self.memory_file)  # replaces: tools
        self.session_id = self._load_session_id()  # replaces: history
        self.client = None

    def _load_session_id(self) -> str | None:
        if self.session_file.exists():  # replaces: history
            return json.loads(self.session_file.read_text(encoding="utf-8"))["session_id"]  # replaces: history
        return None  # replaces: history

    def options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            model=self.model,
            effort=self.effort,
            thinking={"type": "adaptive"},
            system_prompt=BASE_SYSTEM_PROMPT + "\n" + SDK_MEMORY_NOTE,  # replaces: context
            setting_sources=["project"],  # replaces: memory, context
            cwd=str(self.workdir),  # replaces: memory
            mcp_servers={sdk_tools.SERVER: self.server},  # replaces: tools
            strict_mcp_config=True,  # replaces: tools
            tools=[],  # replaces: tools
            allowed_tools=sdk_tools.allowed_tool_names(),  # replaces: tools
            permission_mode="dontAsk",  # replaces: tools
            resume=self.session_id,  # replaces: history
            max_turns=12,  # replaces: loop
        )

    async def __aenter__(self):
        log(f"connect (resume={self.session_id})")
        self.client = self.client_cls(options=self.options())  # replaces: loop
        await self.client.connect()  # replaces: loop
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()
        log("disconnected")

    def _prompt(self, text: str) -> str:
        friday = domain.next_friday(self.today)  # replaces: context
        return f"[today {self.today} ({DAYS[self.today.weekday()]}); next friday {friday}]\n{text}"  # replaces: context

    async def ask(self, text: str) -> TurnResult:
        t0 = time.time()
        await self.client.query(self._prompt(text))  # replaces: loop
        call_ids, tools_used, result = set(), [], None
        async for msg in self.client.receive_response():  # replaces: loop
            if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
                call_ids.add(msg.message_id or id(msg))  # one API response may arrive as several messages
                for b in msg.content:
                    if isinstance(b, ToolUseBlock):
                        tools_used.append(b.name.split("__")[-1])
                        log(f"tool_use {b.name}")
            elif isinstance(msg, ResultMessage):
                result = msg
        if result is None:
            raise RuntimeError("no ResultMessage received")
        usage = usage_from_result(result.usage)  # replaces: tokens
        self.session_id = result.session_id  # replaces: history
        self.session_file.write_text(json.dumps({"session_id": self.session_id}), encoding="utf-8")  # replaces: history
        cost = cost_from_usage(usage, self.model)
        log(f"result: calls={len(call_ids)} in={usage['input']} cache_r={usage['cache_read']} "
            f"cache_w={usage['cache_write']} out={usage['output']} ${cost:.4f} "
            f"(reported total_cost_usd={result.total_cost_usd})")
        return TurnResult(result.result or "", usage, cost, result.total_cost_usd,  # replaces: tokens
                          len(call_ids), tools_used, time.time() - t0, result.session_id,
                          getattr(result, "model_usage", None))

    def memory(self) -> dict:
        return sdk_tools.read_memory(self.memory_file)
