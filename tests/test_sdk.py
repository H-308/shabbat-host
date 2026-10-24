"""SDK configuration and tool wrappers (no Claude Code process is started)."""
import asyncio
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fakes import ROOT, FakeSDKClient, fake_fetch  # noqa: F401
from test_e2e import sdk_main  # noqa: F401  (loads SDK/agent.py as sdk_agent)

sdk_agent = sys.modules["sdk_agent"]
import sdk_tools  # noqa: E402

from shared import loc  # noqa: E402


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.agent = sdk_agent.SDKShabbatAgent(tempfile.mkdtemp(), today=dt.date(2026, 10, 24), fetch=fake_fetch)
        self.opt = self.agent.options()

    def test_required_settings(self):
        self.assertTrue(self.opt.strict_mcp_config)
        self.assertEqual(self.opt.tools, [])                       # no built-in tools at all
        self.assertEqual(self.opt.setting_sources, ["project"])    # loads CLAUDE.md from cwd only
        self.assertTrue(self.opt.system_prompt.startswith('You are "Shabbat Host"'))
        self.assertEqual((self.opt.model, self.opt.effort), ("claude-opus-5-5", "medium"))
        self.assertEqual(len(self.opt.allowed_tools), 8)
        self.assertTrue(all(t.startswith("mcp__shabbat__") for t in self.opt.allowed_tools))
        self.assertTrue(Path(self.opt.cwd, "CLAUDE.md").exists())

    def test_prompt_carries_date_only(self):
        p = self.agent._prompt("שלום")
        self.assertTrue(p.startswith("[today 2026-10-24 (Sat); next friday 2026-10-30]"))


class ToolWrapperTests(unittest.TestCase):
    def setUp(self):
        self.agent = sdk_agent.SDKShabbatAgent(tempfile.mkdtemp(), today=dt.date(2026, 10, 24), fetch=fake_fetch)

    def call(self, name, args):
        return asyncio.run(sdk_tools.LAST_BUILT[name].handler(args))

    def test_success_and_is_error(self):
        ok = self.call("search_recipes", {"course": "dessert"})
        self.assertNotIn("is_error", ok)
        bad = self.call("save_menu", {"dish_ids": ["m01", "d03"], "guests": []})
        self.assertTrue(bad["is_error"])
        self.assertIn("kashrut", bad["content"][0]["text"])

    def test_remember_upserts_claude_md(self):
        self.call("remember", {"key": "pref.max_prep_minutes", "value": "90"})
        out = json.loads(self.call("remember", {"key": "pref.max_prep_minutes", "value": "120"})["content"][0]["text"])
        self.assertEqual(out["replaced"], "90")
        self.assertEqual(self.agent.memory(), {"pref.max_prep_minutes": "120"})
        self.assertIn("## Host memory", self.agent.memory_file.read_text(encoding="utf-8"))


class ReplacesMarkerTests(unittest.TestCase):
    def test_every_part_accounted_for(self):
        counts = loc.sdk_loc()
        for part in ("loop", "tools", "history", "memory", "context", "tokens"):
            self.assertGreater(counts[part], 0, part)
        self.assertEqual(counts["caching"], 0)      # automatic in Claude Code
        self.assertEqual(counts["compaction"], 0)   # automatic in Claude Code
        api = loc.api_loc()
        self.assertGreater(sum(api.values()), 3 * sum(counts.values()))


if __name__ == "__main__":
    unittest.main()
