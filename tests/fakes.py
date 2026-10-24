"""Offline fakes: a scripted Messages API client, a scripted Agent SDK client, and a fake HTTP fetch.

No API key, no network, no Claude Code process.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "API"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ------------------------------------------------------------ Messages API --
class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none: bool = True) -> dict:
        return {k: v for k, v in self.__dict__.items() if not (exclude_none and v is None)}


class Usage:
    def __init__(self, input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0):
        self.input_tokens, self.output_tokens = input_tokens, output_tokens
        self.cache_read_input_tokens, self.cache_creation_input_tokens = cache_read_input_tokens, cache_creation_input_tokens


class Resp:
    def __init__(self, content, stop_reason, usage=None):
        self.content, self.stop_reason, self.usage = content, stop_reason, usage


_ids = iter(range(1, 10_000))


def text(t: str) -> Block:
    return Block(type="text", text=t)


def tool_use(name: str, inp: dict) -> Block:
    return Block(type="tool_use", id=f"toolu_{next(_ids):04d}", name=name, input=inp)


def resp(*blocks) -> Resp:
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return Resp(list(blocks), stop)


def _has_cache_control(obj) -> bool:
    return '"cache_control"' in json.dumps(obj, ensure_ascii=False)


class ScriptedClient:
    """Pops one scripted response per messages.create call; records every request.

    Usage numbers are simulated from request size so caching/compaction logic has
    realistic-looking input: a request whose prefix was sent before is billed as
    cache_read for that prefix. Compaction requests are answered automatically.
    """

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.messages = self
        self._prev_size = 0

    def create(self, **kw):
        self.requests.append(copy.deepcopy(kw))
        size = len(json.dumps([kw.get("tools"), kw.get("system"), kw.get("messages")], ensure_ascii=False)) // 3
        if "tools" not in kw:  # compaction.py summary call
            return Resp([text("סיכום: נועה, יוסי ודני; תפריט נשמר; מגבלת זמן ופרווה בזיכרון.")], "end_turn",
                        Usage(input_tokens=size, output_tokens=40))
        cached = min(self._prev_size, size) if _has_cache_control(kw) else 0
        self._prev_size = size
        r = self.script.pop(0)
        r = r(kw) if callable(r) else r
        out = 20 * len(r.content)
        r.usage = Usage(input_tokens=30, output_tokens=out, cache_read_input_tokens=cached,
                        cache_creation_input_tokens=max(0, size - cached - 30))
        return r


# ----------------------------------------------------------------- network --
def fake_fetch(url: str) -> dict:
    if "hebcal" in url:
        return {"items": [
            {"category": "candles", "title": "הדלקת נרות: 17:03", "date": "2026-10-30T17:03:00+02:00"},
            {"category": "parashat", "title": "Parashat Lech-Lecha", "hebrew": "פרשת לך־לך"},
            {"category": "havdalah", "title": "הבדלה: 17:58", "date": "2026-10-31T17:58:00+02:00"}]}
    if "open-meteo" in url:
        hours = [f"2026-10-30T{h:02d}:00" for h in range(24)]
        return {"hourly": {"time": hours, "temperature_2m": [20.0] * 24,
                           "precipitation_probability": [70 if 18 <= h <= 22 else 5 for h in range(24)]}}
    raise AssertionError(url)


def broken_fetch(url: str) -> dict:
    from shared.external import ExternalError
    raise ExternalError("URLError: offline")


# --------------------------------------------------------------- Agent SDK --
class FakeSDKClient:
    """Stands in for ClaudeSDKClient. Each query() consumes one scripted turn:
    a list of ("tool", name, args) steps and a final ("text", answer).
    Tool steps really call the in-process MCP handlers, so state on disk changes."""

    instances: list["FakeSDKClient"] = []

    def __init__(self, options=None, *, script=None, session_id="sess-fake-1"):
        self.options, self.script, self.session_id = options, list(script or []), session_id
        self.prompts, self.connected = [], False
        FakeSDKClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def query(self, prompt):
        self.prompts.append(prompt)
        self._turn = self.script.pop(0)

    async def receive_response(self):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, UserMessage, ToolResultBlock
        import sdk_tools

        n = 0
        final = ""
        for step in self._turn:
            n += 1
            if step[0] == "tool":
                _, name, args = step
                tid = f"tu{n}"
                yield AssistantMessage(content=[ToolUseBlock(id=tid, name=f"mcp__shabbat__{name}", input=args)],
                                       model="claude-opus-5-5", message_id=f"m{n}")
                res = await sdk_tools.LAST_BUILT[name].handler(args)
                yield UserMessage(content=[ToolResultBlock(tool_use_id=tid, content=res["content"],
                                                           is_error=res.get("is_error", False))])
            else:
                final = step[1]
                yield AssistantMessage(content=[TextBlock(text=final)], model="claude-opus-5-5", message_id=f"m{n}")
        yield ResultMessage(subtype="success", duration_ms=1000, duration_api_ms=900, is_error=False,
                            num_turns=n, session_id=self.session_id, total_cost_usd=0.01 * n,
                            usage={"input_tokens": 10 * n, "cache_read_input_tokens": 3000 * n,
                                   "cache_creation_input_tokens": 500, "output_tokens": 80 * n},
                            result=final)
