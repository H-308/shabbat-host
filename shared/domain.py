"""Pure domain logic for planning a Friday-night dinner. No I/O besides the recipe file."""
from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache

from .config import DATA_DIR

COURSES = ("starter", "main", "side", "dessert")
RESTRICTIONS = {  # guest restriction -> recipe tag that satisfies it
    "vegan": "vegan",
    "vegetarian": "vegetarian",
    "gluten-free": "gluten_free",
    "nut-free": "nut_free",
}
ALIASES = {
    "טבעוני": "vegan", "טבעונית": "vegan", "vegan": "vegan",
    "צמחוני": "vegetarian", "צמחונית": "vegetarian", "vegetarian": "vegetarian",
    "ללא גלוטן": "gluten-free", "צליאק": "gluten-free", "gluten-free": "gluten-free", "gluten_free": "gluten-free",
    "אלרגי לאגוזים": "nut-free", "אלרגיה לאגוזים": "nut-free", "nut-free": "nut-free", "nut_free": "nut-free",
}


def canon_restriction(r: str) -> str | None:
    r = str(r).strip().lower()
    return ALIASES.get(r, r if r in RESTRICTIONS else None)


@lru_cache(maxsize=1)
def recipes() -> tuple[dict, ...]:
    return tuple(json.loads((DATA_DIR / "recipes.json").read_text(encoding="utf-8")))


def recipe(rid: str) -> dict | None:
    return next((r for r in recipes() if r["id"] == rid), None)


def fits_guest(r: dict, guest: dict) -> str | None:
    """Return None if the dish is fine for the guest, otherwise a short reason."""
    for res in guest.get("restrictions", []):
        tag = RESTRICTIONS.get(res)
        if tag and tag not in r["tags"]:
            return res
    for bad in guest.get("dislikes", []):
        if any(bad and bad in ing for ing in r["ing"]):
            return f"dislikes {bad}"
    return None


def search(course=None, must=(), kind=None, max_mins=None, exclude=(), query=None, limit=6) -> list[dict]:
    out = []
    for r in recipes():
        if course and r["course"] != course:
            continue
        if kind and r["kind"] != kind:
            continue
        if max_mins and r["mins"] > max_mins:
            continue
        if r["id"] in exclude:
            continue
        tags = set(r["tags"])
        if any(RESTRICTIONS.get(m, m) not in tags for m in must):
            continue
        if query and query not in r["name"] and not any(query in i for i in r["ing"]):
            continue
        out.append(r)
    return out[:limit]


def validate_menu(dish_ids: list[str], guests: list[dict], max_prep: int | None = None) -> dict:
    """Check a menu against kashrut, every guest's restrictions, and prep time.

    Rule per guest: every course on the menu must offer at least one dish the guest can eat.
    """
    issues: list[str] = []
    dishes = []
    for d in dish_ids:
        r = recipe(d)
        if r is None:
            issues.append(f"unknown dish {d}")
        else:
            dishes.append(r)
    meat = [r["name"] for r in dishes if r["kind"] == "meat"]
    dairy = [r["name"] for r in dishes if r["kind"] == "dairy"]
    if meat and dairy:
        issues.append(f"kashrut: meat ({meat[0]}) with dairy ({dairy[0]})")
    courses = {c: [r for r in dishes if r["course"] == c] for c in COURSES}
    for c in ("main", "dessert"):
        if not courses[c]:
            issues.append(f"missing {c}")
    for g in guests:
        for c, rs in courses.items():
            if rs and all(fits_guest(r, g) for r in rs):
                issues.append(f"{g['name']}: nothing in {c} ({fits_guest(rs[0], g)})")
    if max_prep:
        for r in dishes:
            if r["mins"] > max_prep:
                issues.append(f"prep: {r['name']} {r['mins']}>{max_prep}min")
    return {"ok": not issues, "issues": issues}


def next_friday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=(4 - today.weekday()) % 7)
