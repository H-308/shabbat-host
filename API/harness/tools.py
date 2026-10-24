"""Tool registry: JSON schemas for the API, dispatch by name, errors returned as is_error.

Domain tools come from shared/tools_spec.py, memory tools from memory.py.
Any exception becomes a tool_result with is_error=true so the model can recover
instead of the loop crashing. Results are capped at MAX_RESULT_CHARS.
"""
from __future__ import annotations

import json

from shared import tools_spec

from . import logger

log = logger(__file__)
MAX_RESULT_CHARS = 2000


class ToolRegistry:
    def __init__(self, ctx: tools_spec.ToolContext, extra: list[dict] = ()):
        self.ctx = ctx
        self._domain = dict(tools_spec.BY_NAME)
        self._extra = {t["name"]: t for t in extra}
        log(f"registered {len(self._domain)} domain + {len(self._extra)} memory tools")

    def schemas(self) -> list[dict]:
        out = [{"name": s.name, "description": s.description, "input_schema": s.schema} for s in self._domain.values()]
        out += [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]}
                for t in self._extra.values()]
        return out

    def _run(self, name: str, args: dict) -> str:
        if name in self._domain:
            return tools_spec.invoke(self._domain[name], self.ctx, args)
        if name in self._extra:
            return tools_spec.compact(self._extra[name]["fn"](args))
        raise KeyError(f"unknown tool '{name}'. available: {', '.join([*self._domain, *self._extra])}")

    def dispatch(self, tool_use) -> dict:
        """One tool_use block -> one tool_result block."""
        name, args, tid = _get(tool_use, "name"), _get(tool_use, "input") or {}, _get(tool_use, "id")
        try:
            text, is_error = self._run(name, args), False
        except Exception as e:  # noqa: BLE001 - everything goes back to the model
            text, is_error = f"{type(e).__name__}: {e}", True
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "…[truncated]"
        log(f"{name}({json.dumps(args, ensure_ascii=False)[:120]}) -> "
            f"{'ERROR ' if is_error else ''}{len(text)} chars")
        block = {"type": "tool_result", "tool_use_id": tid, "content": text}
        if is_error:
            block["is_error"] = True
        return block


def _get(block, key):
    return block.get(key) if isinstance(block, dict) else getattr(block, key)
