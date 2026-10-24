"""Domain logic, compact tool output, external tool parsing, checks."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import fakes  # noqa: F401  (sets sys.path)
from shared import checks, domain, external, tools_spec as T
from shared.store import Store

TODAY = dt.date(2026, 10, 24)


class DomainTests(unittest.TestCase):
    def test_kashrut_meat_with_dairy_fails(self):
        v = domain.validate_menu(["m01", "d03"], [])
        self.assertFalse(v["ok"])
        self.assertTrue(any("kashrut" in i for i in v["issues"]))

    def test_every_guest_needs_a_dish_in_every_course(self):
        noa = {"name": "נועה", "restrictions": ["vegan"]}
        self.assertFalse(domain.validate_menu(["m01", "d01"], [noa])["ok"])        # only a meat main
        self.assertTrue(domain.validate_menu(["m01", "m04", "d01"], [noa])["ok"])  # vegan main added

    def test_prep_limit(self):
        v = domain.validate_menu(["m02", "d01"], [], max_prep=90)
        self.assertIn("prep", " ".join(v["issues"]))

    def test_next_friday(self):
        self.assertEqual(domain.next_friday(TODAY), dt.date(2026, 10, 30))
        self.assertEqual(domain.next_friday(dt.date(2026, 10, 30)), dt.date(2026, 10, 30))


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.ctx = T.ToolContext(Store(tempfile.mkdtemp()), TODAY, fetch=fakes.fake_fetch)

    def call(self, name, args):
        return json.loads(T.invoke(T.BY_NAME[name], self.ctx, args))

    def test_search_output_is_compact(self):
        raw = T.invoke(T.BY_NAME["search_recipes"], self.ctx, {"course": "main"})
        self.assertNotIn("\n", raw)
        self.assertNotIn(": ", raw)
        self.assertLessEqual(len(json.loads(raw)["rows"]), 6)
        self.assertLess(len(raw), 800)

    def test_save_guest_overwrites_restrictions_and_reports_change(self):
        self.call("save_guest", {"name": "נועה", "restrictions": ["טבעונית"]})
        out = self.call("save_guest", {"name": "נועה", "restrictions": ["vegetarian"]})
        self.assertEqual(out["changed"], {"from": ["vegan"], "to": ["vegetarian"]})
        self.assertEqual(self.ctx.store.find_guest("נועה")["restrictions"], ["vegetarian"])

    def test_save_menu_rejects_invalid_and_logs_failure(self):
        with self.assertRaises(T.ToolError):
            self.call("save_menu", {"dish_ids": ["m01", "d03"], "guests": []})
        self.assertEqual(self.ctx.store.menus(), [])
        self.assertFalse(self.ctx.store.tool_log()[-1]["ok"])

    def test_external_tool_is_tiny(self):
        out = self.call("shabbat_info", {"city": "גבעת שמואל"})
        self.assertEqual(out["candles"], "17:03")
        self.assertEqual(out["eve_rain_pct"], 70)
        self.assertLess(len(json.dumps(out, ensure_ascii=False)), 200)

    def test_external_failure_becomes_tool_error(self):
        self.ctx.fetch = fakes.broken_fetch
        with self.assertRaises(T.ToolError):
            self.call("shabbat_info", {})

    def test_unknown_city(self):
        with self.assertRaises(T.ToolError):
            self.call("shabbat_info", {"city": "אטלנטיס"})


class CheckTests(unittest.TestCase):
    def test_memory_check_contradiction(self):
        store = Store(tempfile.mkdtemp())
        c = {"id": "x", "type": "memory_value", "key": "pref.max_prep_minutes", "matches": r"\b120\b",
             "not_matches": r"\b90\b"}
        self.assertFalse(checks.evaluate(c, store, {"pref.max_prep_minutes": "90"}, {})[0])
        self.assertTrue(checks.evaluate(c, store, {"pref.max_prep_minutes": "120"}, {})[0])


if __name__ == "__main__":
    unittest.main()
