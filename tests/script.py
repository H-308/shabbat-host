"""A scripted 'ideal model' for the 7-turn scenario, used by both offline end-to-end tests.

Each turn is a list of rounds. A round is either a list of (tool, args) calls made in
one model response, or a string = the final answer of the turn.
"""
import json
from pathlib import Path

from fakes import ROOT, resp, text, tool_use

TODAY = "2026-10-24"
GUESTS3 = ["נועה", "יוסי", "דני"]
GUESTS4 = GUESTS3 + ["מיכל"]
MENU1 = ["s01", "m01", "m04", "x02", "d01"]
MENU2_BAD = ["s01", "m06", "m04", "x04", "d03"]   # cheesecake: not gluten-free for Michal, and breaks the parve rule
MENU2 = ["s01", "m06", "m04", "x04", "d02"]

TURNS = [
    [[("save_guest", {"name": "נועה", "restrictions": ["vegan"]}),
      ("save_guest", {"name": "יוסי", "restrictions": ["nut-free"]}),
      ("save_guest", {"name": "דני"})],
     "שמרתי את נועה, יוסי ודני."],
    [[("remember", {"key": "pref.max_prep_minutes", "value": "90"}),
      ("remember", {"key": "pref.dessert", "value": "הקינוח תמיד פרווה"}),
      ("remember", {"key": "pref.rain_plan", "value": "אם צפוי גשם אוכלים בפנים"})],
     "רשמתי: עד 90 דקות, קינוח פרווה, ובגשם בפנים."],
    [[("search_recipes", {"course": "main", "must": ["vegan"], "max_mins": 90})],
     [("check_menu", {"dish_ids": MENU1, "guests": GUESTS3, "max_prep": 90})],
     [("save_menu", {"dish_ids": MENU1, "guests": GUESTS3, "max_prep": 90})],
     "התפריט נשמר: סלט עגבניות, עוף בתנור עם תפוחי אדמה ורוזמרין ומקלובה ירקות, שעועית ירוקה, סלט פירות."],
    [[("shabbat_info", {"city": "גבעת שמואל"})],
     "כניסת שבת 17:03, סיכוי לגשם 70% - לפי מה שביקשת עורכים בפנים."],
    [[("past_menus", {"limit": 1})],
     "בפעם הקודמת הגשת עוף בתנור עם תפוחי אדמה ורוזמרין ומקלובה. נבחר עיקרית אחרת."],
    [[("save_guest", {"name": "נועה", "restrictions": ["vegetarian"]}),
      ("save_guest", {"name": "מיכל", "restrictions": ["gluten-free"]}),
      ("remember", {"key": "pref.max_prep_minutes", "value": "120"})],
     "עדכנתי: נועה צמחונית, מיכל ללא גלוטן, ומגבלת הזמן 120 דקות."],
    [[("save_menu", {"date": "2026-11-06", "dish_ids": MENU2_BAD, "guests": GUESTS4, "max_prep": 120})],
     [("save_menu", {"date": "2026-11-06", "dish_ids": MENU2, "guests": GUESTS4, "max_prep": 120})],
     "עוגת גבינה היא חלבית וגם לא ללא גלוטן, והכלל שלך הוא קינוח פרווה - שמרתי עוגת שוקולד פרווה בלי קמח."],
]


def api_script() -> list:
    out = []
    for turn in TURNS:
        for rnd in turn:
            out.append(resp(text(rnd)) if isinstance(rnd, str) else resp(*[tool_use(n, a) for n, a in rnd]))
    return out


def sdk_script() -> list:
    out = []
    for turn in TURNS:
        steps = []
        for rnd in turn:
            steps += [("text", rnd)] if isinstance(rnd, str) else [("tool", n, a) for n, a in rnd]
        out.append(steps)
    return out


def scenario_copy(tmp: Path, **overrides) -> Path:
    sc = json.loads((ROOT / "scenario.json").read_text(encoding="utf-8"))
    sc["today"] = TODAY
    sc.update(overrides)
    p = tmp / "scenario.json"
    p.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    return p
