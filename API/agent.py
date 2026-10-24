"""Shabbat Host on the raw Messages API: wires the eight harness modules together.

A new ShabbatAgent instance = a new session. Everything it knows comes from disk:
history.jsonl (conversation), memory.json (preferences), and the shared domain store.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared import config  # noqa: E402
from shared.store import Store  # noqa: E402
from shared.tools_spec import ToolContext  # noqa: E402

from harness import caching, compaction, context, loop  # noqa: E402
from harness.history import History  # noqa: E402
from harness.memory import Memory, tool_specs  # noqa: E402
from harness.tokens import TurnMeter  # noqa: E402
from harness.tools import ToolRegistry  # noqa: E402


@dataclass
class TurnResult:
    answer: str
    usage: dict
    cost: float
    model_calls: int
    tools: list
    seconds: float
    compacted: bool
    stop_reason: str


def make_client():
    try:
        import anthropic
    except ImportError as e:
        raise SystemExit("pip install -r requirements.txt  (anthropic is required for the API version)") from e
    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment only


class ShabbatAgent:
    def __init__(self, state_dir: str | Path, client=None, *, session: int = 1, today: dt.date | None = None,
                 model: str = config.MODEL, effort: str = config.EFFORT, compact_threshold: int = 50_000,
                 fetch=None):
        self.dir = Path(state_dir)
        self.client = client or make_client()
        self.model, self.effort, self.compact_threshold = model, effort, compact_threshold
        self.today = today or dt.date.today()
        self.store = Store(self.dir / "domain", session=session)
        self.history = History(self.dir / "api" / "history.jsonl")
        self.memory = Memory(self.dir / "api" / "memory.json")
        ctx = ToolContext(self.store, self.today, **({"fetch": fetch} if fetch else {}))
        self.tools = ToolRegistry(ctx, extra=tool_specs(self.memory))
        self.system = context.system_blocks()
        # A resumed session has no usage numbers yet: estimate the reloaded history so compaction can still fire.
        self._last_context = caching._est_tokens(self.history.messages()) if len(self.history) else 0
        # effort lives in output_config; sent via extra_body so it works whatever the SDK's typed signature is.
        self.params = {"thinking": {"type": "adaptive"}, "extra_body": {"output_config": {"effort": effort}}}

    def ask(self, text: str) -> TurnResult:
        t0 = time.time()
        meter = TurnMeter(self.model)
        compacted = False
        if compaction.should_compact(self._last_context, self.compact_threshold):
            compaction.compact(self.client, self.history, self.model, meter, self._last_context,
                               extra_body=self.params["extra_body"])
            compacted = True
        self.history.add("user", context.build_user_turn(text, self.store, self.memory, self.today))
        res = loop.run(self.client, history=self.history, registry=self.tools, meter=meter, system=self.system,
                       model=self.model, max_tokens=config.MAX_TOKENS, params=self.params)
        self._last_context = meter.context_size()
        meter.summary()
        return TurnResult(res.text, meter.usage, meter.cost, len(meter.calls), res.tools_used,
                          time.time() - t0, compacted, res.stop_reason)
