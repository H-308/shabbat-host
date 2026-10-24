"""Fill the numeric sections of REPORT.md from results/api.json and results/sdk.json.

    python -m shared.report

Only text between <!-- AUTO:<name> --> and <!-- /AUTO:<name> --> is replaced;
the hand-written analysis around it is left alone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import ROOT
from .loc import PARTS, api_loc, sdk_loc

REPORT = ROOT / "REPORT.md"


def _load(name: str) -> dict | None:
    p = ROOT / "results" / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def totals_table(api: dict | None, sdk: dict | None) -> str:
    if not (api or sdk):
        return "_עדיין אין תוצאות. הריצי את שתי הפקודות בסעיף \"איך מריצים\" ואז `python -m shared.report`._"
    rows = [("input (לא מ-cache)", "input"), ("cache read", "cache_read"), ("cache write", "cache_write"),
            ("output", "output"), ("אחוז cache (מתוך צד ה-prompt)", "cache_hit_pct"), ("קריאות למודל", "model_calls"),
            ("קריאות לכלים", "tool_calls"), ("עלות (USD, אותו מחירון)", "cost_usd"), ("זמן (שניות)", "seconds")]
    out = ["| מדד | API | SDK |", "|---|---:|---:|"]
    for label, k in rows:
        a = api["totals"].get(k, "-") if api else "-"
        s = sdk["totals"].get(k, "-") if sdk else "-"
        if k == "cache_hit_pct":
            a, s = (f"{a}%" if a != "-" else a), (f"{s}%" if s != "-" else s)
        if k == "cost_usd":
            a, s = (f"${a:.4f}" if a != "-" else a), (f"${s:.4f}" if s != "-" else s)
        out.append(f"| {label} | {_fmt(a)} | {_fmt(s)} |")
    out.append(f"| בדיקות שעברו | {api['checks_passed'] if api else '-'} | {sdk['checks_passed'] if sdk else '-'} |")
    if sdk:
        rep = [t.get("sdk_reported_cost_usd") for t in sdk["turns"] if t.get("sdk_reported_cost_usd") is not None]
        if rep:
            out.append(f"\n`total_cost_usd` כפי שה-SDK דיווח בתור האחרון: ${rep[-1]:.4f}")
    return "\n".join(out)


def turns_table(api: dict | None, sdk: dict | None) -> str:
    if not (api and sdk):
        return "_יתמלא אחרי ששתי הריצות קיימות._"
    out = ["| תור | סשן | API prompt-side | API out | API calls | SDK prompt-side | SDK out | SDK calls | API $ | SDK $ |",
           "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for a, s in zip(api["turns"], sdk["turns"]):
        pa = a["tokens"]["input"] + a["tokens"]["cache_read"] + a["tokens"]["cache_write"]
        ps = s["tokens"]["input"] + s["tokens"]["cache_read"] + s["tokens"]["cache_write"]
        flag = " ✂" if a.get("compacted") else ""
        out.append(f"| {a['turn']}{flag} | {a['session']} | {pa:,} | {a['tokens']['output']:,} | {a['model_calls']} | "
                   f"{ps:,} | {s['tokens']['output']:,} | {s['model_calls']} | {a['cost_usd']:.4f} | {s['cost_usd']:.4f} |")
    out.append("\nprompt-side = input + cache read + cache write. ✂ = ה-API דחס את השיחה לפני התור הזה.")
    return "\n".join(out)


def checks_table(api: dict | None, sdk: dict | None) -> str:
    if not (api or sdk):
        return "_יתמלא אחרי הריצות._"
    base = (api or sdk)["checks"]
    am = {c["id"]: c for c in (api or {}).get("checks", [])}
    sm = {c["id"]: c for c in (sdk or {}).get("checks", [])}
    mark = lambda c: "-" if c is None else ("✅" if c["passed"] else "❌")
    out = ["| בדיקה | מה נבדק | API | SDK |", "|---|---|:---:|:---:|"]
    for c in base:
        out.append(f"| `{c['id']}` | {c['desc']} | {mark(am.get(c['id']))} | {mark(sm.get(c['id']))} |")
    return "\n".join(out)


def loc_table() -> str:
    a, s = api_loc(), sdk_loc()
    out = ["| חלק ב-harness | API (שורות לוגיות) | SDK (שורות `# replaces:`) |", "|---|---:|---:|"]
    for p in PARTS:
        out.append(f"| {p} | {a[p]} | {s[p]} |")
    out.append(f"| **סה\"כ** | **{sum(a.values())}** | **{sum(s.values())}** |")
    return "\n".join(out)


def hidden_calls(sdk: dict | None) -> str:
    if not sdk:
        return "_יתמלא אחרי ריצת ה-SDK._"
    models: dict = {}
    for t in sdk["turns"]:
        for m, u in (t.get("model_usage") or {}).items():
            agg = models.setdefault(m, {"in": 0, "out": 0, "cost": 0.0})
            agg["in"] += (u.get("inputTokens", 0) or 0) + (u.get("cacheReadInputTokens", 0) or 0) \
                + (u.get("cacheCreationInputTokens", 0) or 0)
            agg["out"] += u.get("outputTokens", 0) or 0
            agg["cost"] += u.get("costUSD", 0) or 0
    if not models:
        return "_ה-SDK לא החזיר model_usage._"
    out = ["| מודל | prompt tokens | output | costUSD |", "|---|---:|---:|---:|"]
    for m, u in models.items():
        out.append(f"| {m} | {u['in']:,} | {u['out']:,} | ${u['cost']:.4f} |")
    return "\n".join(out)


def main() -> None:
    api, sdk = _load("api"), _load("sdk")
    text = REPORT.read_text(encoding="utf-8")
    sections = {"totals": totals_table(api, sdk), "turns": turns_table(api, sdk), "checks": checks_table(api, sdk),
                "loc": loc_table(), "models": hidden_calls(sdk)}
    for name, body in sections.items():
        text = re.sub(rf"(<!-- AUTO:{name} -->)(.*?)(<!-- /AUTO:{name} -->)",
                      lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", text, flags=re.S)
    REPORT.write_text(text, encoding="utf-8")
    print(f"updated {REPORT.name}: api={'yes' if api else 'no'} sdk={'yes' if sdk else 'no'}")


if __name__ == "__main__":
    main()
