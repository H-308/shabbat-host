"""Unit tests for each API/harness module, using the scripted client (no key, no network)."""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HARNESS_QUIET", "1")
from fakes import ScriptedClient, fake_fetch, resp, text, tool_use  # noqa: E402

from harness import caching, compaction, context, loop  # noqa: E402
from harness.history import History  # noqa: E402
from harness.memory import Memory, tool_specs  # noqa: E402
from harness.tokens import TurnMeter, cost  # noqa: E402
from harness.tools import ToolRegistry  # noqa: E402
from shared.store import Store  # noqa: E402
from shared.tools_spec import ToolContext  # noqa: E402

TODAY = dt.date(2026, 10, 24)


def setup_parts(tmp: Path):
    store = Store(tmp / "domain")
    mem = Memory(tmp / "memory.json")
    hist = History(tmp / "history.jsonl")
    reg = ToolRegistry(ToolContext(store, TODAY, fetch=fake_fetch), extra=tool_specs(mem))
    return store, mem, hist, reg


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.mem, self.hist, self.reg = setup_parts(self.tmp)

    def run_loop(self, client):
        return loop.run(client, history=self.hist, registry=self.reg, meter=TurnMeter("claude-opus-5-5"),
                        system=context.system_blocks(), model="claude-opus-5-5", max_tokens=100, params={})

    def test_loops_while_tool_use_and_batches_results_in_one_message(self):
        client = ScriptedClient([
            resp(tool_use("save_guest", {"name": "דני"}), tool_use("search_recipes", {"course": "dessert"})),
            resp(text("סיימתי")),
        ])
        self.hist.add("user", "שמור את דני")
        res = self.run_loop(client)
        self.assertEqual((res.text, res.model_calls, res.stop_reason), ("סיימתי", 2, "end_turn"))
        second_call_msgs = client.requests[1]["messages"]
        tool_msg = second_call_msgs[-1]
        self.assertEqual(tool_msg["role"], "user")
        self.assertEqual([b["type"] for b in tool_msg["content"]], ["tool_result", "tool_result"])
        self.assertEqual(res.tools_used, ["save_guest", "search_recipes"])

    def test_errors_go_back_as_is_error(self):
        client = ScriptedClient([
            resp(tool_use("no_such_tool", {}), tool_use("save_menu", {"dish_ids": ["m01", "d03"], "guests": []})),
            resp(text("אוקיי")),
        ])
        self.hist.add("user", "x")
        self.run_loop(client)
        results = client.requests[1]["messages"][-1]["content"]
        self.assertTrue(all(r.get("is_error") for r in results))
        self.assertIn("unknown tool", results[0]["content"])
        self.assertIn("kashrut", results[1]["content"])

    def test_max_iters_keeps_history_valid(self):
        client = ScriptedClient([resp(tool_use("list_guests", {})) for _ in range(3)])
        self.hist.add("user", "x")
        res = loop.run(client, history=self.hist, registry=self.reg, meter=TurnMeter("claude-opus-5-5"),
                       system=context.system_blocks(), model="m", max_tokens=10, params={}, max_iters=3)
        self.assertEqual(res.stop_reason, "max_iters")
        self.assertEqual(self.hist.messages()[-1]["role"], "assistant")


class HistoryTests(unittest.TestCase):
    def test_append_only_and_reload(self):
        tmp = Path(tempfile.mkdtemp())
        h = History(tmp / "h.jsonl")
        h.add("user", "שלום")
        h.add("assistant", [text("היי")])
        size_before = (tmp / "h.jsonl").read_text(encoding="utf-8").count("\n")
        h.add_compaction("סיכום", 999)
        h.add("user", "עוד")
        raw = (tmp / "h.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(raw), size_before + 2)  # nothing rewritten
        h2 = History(tmp / "h.jsonl")  # new session
        msgs = h2.messages()
        self.assertIn("סיכום", msgs[0]["content"])
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(msgs[-1]["content"], "עוד")
        self.assertEqual(len(msgs), 3)


class MemoryTests(unittest.TestCase):
    def test_overwrite_keeps_history_and_persists(self):
        tmp = Path(tempfile.mkdtemp())
        m = Memory(tmp / "m.json")
        m.remember("pref.max_prep_minutes", "90")
        out = m.remember("pref.max_prep_minutes", "120")
        self.assertEqual(out["replaced"], "90")
        m2 = Memory(tmp / "m.json")
        self.assertEqual(m2.as_dict()["pref.max_prep_minutes"], "120")
        self.assertEqual(m2.facts["pref.max_prep_minutes"]["history"], ["90"])

    def test_relevant_selects_not_dumps(self):
        m = Memory(Path(tempfile.mkdtemp()) / "m.json")
        m.remember("pref.dessert", "תמיד פרווה")
        for i in range(10):
            m.remember(f"decision.misc{i}", f"דבר לא קשור מספר {i}")
        m.remember("decision.wine", "יין אדום יבש לקידוש")
        picked, left = m.relevant("איזה יין לקנות לקידוש?", k=3)
        self.assertIn("pref.dessert", picked)      # prefs always in
        self.assertIn("decision.wine", picked)     # keyword match
        self.assertLessEqual(len(picked), 3)
        self.assertEqual(left, 12 - len(picked))


class ContextTests(unittest.TestCase):
    def test_context_block_contents(self):
        tmp = Path(tempfile.mkdtemp())
        store, mem, _, _ = setup_parts(tmp)
        store.upsert_guest({"name": "נועה", "restrictions": ["vegan"], "dislikes": []})
        store.add_menu({"date": "2026-10-30", "guests": ["נועה"], "dish_ids": ["s01", "m04", "d01"]})
        mem.remember("pref.dessert", "פרווה")
        menu_turn = context.build_user_turn("תציע תפריט", store, mem, TODAY)
        other_turn = context.build_user_turn("מתי כניסת שבת?", store, mem, TODAY)
        self.assertIn("next friday: 2026-10-30", menu_turn)
        self.assertIn("נועה[vegan]", menu_turn)
        self.assertIn("pref.dessert=פרווה", menu_turn)
        self.assertIn("last menu", menu_turn)
        self.assertNotIn("last menu", other_turn)       # only when relevant
        self.assertNotIn("מקלובה", menu_turn)           # recipe catalog never injected

    def test_system_prompt_is_static(self):
        self.assertEqual(context.system_blocks(), context.system_blocks())


class CachingTests(unittest.TestCase):
    def test_breakpoints_on_copies_only(self):
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": [{"type": "text", "text": "b"}]},
                {"role": "user", "content": "c"}]
        sysb = context.system_blocks()
        s2, _, m2 = caching.apply(sysb, [], msgs)
        self.assertEqual(s2[-1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(m2[-1]["content"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", json.dumps([sysb, msgs]))  # originals untouched
        self.assertLessEqual(json.dumps([s2, m2]).count("cache_control"), 4)


class CompactionTests(unittest.TestCase):
    def test_threshold_and_summary_replace_old_messages(self):
        tmp = Path(tempfile.mkdtemp())
        h = History(tmp / "h.jsonl")
        h.add("user", "x" * 500)
        h.add("assistant", [tool_use("list_guests", {}).model_dump()])
        h.add("user", [{"type": "tool_result", "tool_use_id": "t", "content": "y" * 1000}])
        h.add("assistant", [text("ok")])
        self.assertFalse(compaction.should_compact(100, 1000))
        self.assertTrue(compaction.should_compact(5000, 1000))
        meter = TurnMeter("claude-opus-5-5")
        client = ScriptedClient([])
        summary = compaction.compact(client, h, "claude-opus-5-5", meter, 5000)
        self.assertIn("סיכום", summary)
        req = client.requests[0]
        self.assertNotIn("tools", req)
        self.assertIn("assistant -> list_guests", req["messages"][0]["content"])
        self.assertLess(len(req["messages"][0]["content"]), 1200)  # tool result clipped
        self.assertEqual(len(h.messages()), 2)
        self.assertEqual(meter.calls[0]["kind"], "compaction")


class TokenTests(unittest.TestCase):
    def test_cost_math(self):
        u = {"input": 1_000_000, "cache_read": 1_000_000, "cache_write": 1_000_000, "output": 1_000_000}
        self.assertAlmostEqual(cost(u, "claude-opus-5-5"), 4 + 0.2 + 5 + 20)

    def test_meter_aggregates_calls(self):
        from fakes import Usage
        m = TurnMeter("claude-opus-5-5")
        m.record(Usage(100, 10, 1000, 0))
        m.record(Usage(50, 20, 1100, 30))
        self.assertEqual(m.usage, {"input": 150, "cache_read": 2100, "cache_write": 30, "output": 30})
        self.assertEqual(m.context_size(), 50 + 1100 + 30 + 20)


if __name__ == "__main__":
    unittest.main()
