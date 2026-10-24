"""The agent loop: call the model while stop_reason == "tool_use".

Each iteration: rebuild messages from history -> add cache breakpoints -> call ->
append the assistant message -> run ALL tool_use blocks -> append ALL tool_results
in ONE user message -> repeat. Ends on any other stop_reason (end_turn, max_tokens...).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import caching, logger
from .history import History
from .tokens import TurnMeter
from .tools import ToolRegistry

log = logger(__file__)


@dataclass
class LoopResult:
    text: str
    stop_reason: str
    model_calls: int
    tools_used: list = field(default_factory=list)


def run(client, *, history: History, registry: ToolRegistry, meter: TurnMeter, system: list[dict],
        model: str, max_tokens: int, params: dict, max_iters: int = 12) -> LoopResult:
    tools_used: list[str] = []
    tool_schemas = registry.schemas()
    for i in range(1, max_iters + 1):
        sys_c, tools_c, msgs_c = caching.apply(system, tool_schemas, history.messages())
        log(f"iteration {i}: calling {model} with {len(msgs_c)} messages")
        resp = client.messages.create(model=model, max_tokens=max_tokens, system=sys_c, tools=tools_c,
                                      messages=msgs_c, **params)
        meter.record(resp.usage)
        history.add("assistant", resp.content)
        log(f"stop_reason={resp.stop_reason}")
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            return LoopResult(text, resp.stop_reason, i, tools_used)
        uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
        results = [registry.dispatch(u) for u in uses]
        tools_used += [u.name for u in uses]
        history.add("user", results)  # all tool_results together, in one message
        log(f"returned {len(results)} tool_result(s) in one message")
    log(f"hit max_iters={max_iters}; stopping")
    text = "(הסוכן עצר: יותר מדי צעדים ברצף)"
    history.add("assistant", [{"type": "text", "text": text}])  # keep user/assistant alternation valid
    return LoopResult(text, "max_iters", max_iters, tools_used)
