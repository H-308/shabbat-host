"""Full 7-turn scenario through API/main.py and SDK/main.py with scripted models.

Proves the plumbing end to end: two sessions on fresh instances, state reloaded from
disk, all scenario checks evaluated, results files written in the required shape.
"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HARNESS_QUIET", "1")
from fakes import ROOT, FakeSDKClient, ScriptedClient, fake_fetch  # noqa: E402
from script import api_script, scenario_copy, sdk_script  # noqa: E402


def load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


api_main = load("api_main", ROOT / "API" / "main.py")
sdk_main = load("sdk_main", ROOT / "SDK" / "main.py")

TURN_KEYS = {"session", "turn", "prompt", "tokens", "model_calls", "tools", "cost_usd", "seconds", "answer"}


class ResultsShape:
    def assert_results(self, payload, n_parts_nonzero):
        self.assertEqual(len(payload["turns"]), 7)
        for t in payload["turns"]:
            self.assertTrue(TURN_KEYS <= set(t), t.keys())
            self.assertEqual(set(t["tokens"]), {"input", "cache_read", "cache_write", "output"})
        failed = [c for c in payload["checks"] if not c["passed"]]
        self.assertEqual(failed, [], json.dumps(failed, ensure_ascii=False, indent=1))
        self.assertEqual(len(payload["checks"]), 18)
        self.assertEqual(set(payload["loc"]), {"loop", "tools", "history", "memory", "context", "compaction",
                                               "caching", "tokens"})
        self.assertGreaterEqual(sum(1 for v in payload["loc"].values() if v), n_parts_nonzero)


class APIEndToEnd(unittest.TestCase, ResultsShape):
    def test_full_scenario(self):
        tmp = Path(tempfile.mkdtemp())
        client = ScriptedClient(api_script())
        sc = scenario_copy(tmp, compact_threshold_tokens=2500)  # low threshold so compaction really happens
        payload = api_main.run_scenario(sc, tmp / "api.json", tmp / "state", client_factory=lambda: client,
                                        fetch=fake_fetch)
        self.assert_results(payload, 8)
        self.assertEqual(client.script, [])                      # every scripted response consumed
        self.assertGreaterEqual(payload["compactions"], 1)
        self.assertGreater(payload["totals"]["cache_read"], 0)
        hist = (tmp / "state" / "api" / "history.jsonl").read_text(encoding="utf-8")
        self.assertIn('"t": "compact"', hist)
        self.assertIn("נועה", hist)
        # session 2 got a fresh agent: its first request still carried last week's state via context
        first_s2 = next(r for r in client.requests if "tools" in r and "חזרתי" in json.dumps(r["messages"][-1], ensure_ascii=False))
        self.assertIn("pref.max_prep_minutes=90", json.dumps(first_s2["messages"][-1], ensure_ascii=False))


class SDKEndToEnd(unittest.TestCase, ResultsShape):
    def test_full_scenario_and_resume(self):
        tmp = Path(tempfile.mkdtemp())
        turns = sdk_script()
        sessions = [turns[:4], turns[4:]]
        FakeSDKClient.instances.clear()

        def client_cls(options):
            return FakeSDKClient(options, script=sessions.pop(0))

        payload = asyncio.run(sdk_main.run_scenario(scenario_copy(tmp), tmp / "sdk.json", tmp / "state",
                                                    client_cls=client_cls, fetch=fake_fetch))
        self.assert_results(payload, 5)
        first, second = FakeSDKClient.instances
        self.assertIsNone(first.options.resume)
        self.assertEqual(second.options.resume, "sess-fake-1")  # session 2 resumes from disk
        md = (tmp / "state" / "sdk" / "workdir" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("- [pref.max_prep_minutes] 120", md)
        self.assertEqual(md.count("pref.max_prep_minutes"), 1)  # overwritten, not duplicated
        self.assertEqual(payload["loc"]["caching"], 0)
        self.assertEqual(payload["loc"]["compaction"], 0)


if __name__ == "__main__":
    unittest.main()
