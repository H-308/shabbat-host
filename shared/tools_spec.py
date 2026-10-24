"""Domain tools, defined once and wrapped by each harness.

Every tool returns a small dict that is serialised with `compact()`: no indentation,
short keys, tables as rows. Tool output is the biggest token sink in an agent loop,
so this is where most of the token optimisation lives.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Callable

from . import domain, external
from .store import Store, norm


class ToolError(Exception):
    """A problem the model can fix (bad argument, validation failure)."""


@dataclass
class ToolContext:
    store: Store
    today: dt.date
    fetch: Callable = external.fetch_json


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    fn: Callable[[ToolContext, dict], dict]
    tags: list = field(default_factory=list)


def compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _str_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v]


# ---------------------------------------------------------------- tools ----
def search_recipes(ctx: ToolContext, a: dict) -> dict:
    rows = domain.search(
        course=a.get("course"), must=_str_list(a.get("must")), kind=a.get("kind"),
        max_mins=a.get("max_mins"), exclude=_str_list(a.get("exclude")), query=a.get("query"),
        limit=min(int(a.get("limit", 6)), 10),
    )
    return {"cols": ["id", "name", "course", "kind", "min", "tags"],
            "rows": [[r["id"], r["name"], r["course"], r["kind"], r["mins"],
                      ",".join(t.replace("vegetarian", "veg").replace("gluten_free", "gf").replace("nut_free", "nf")
                               for t in r["tags"])] for r in rows]}


def save_guest(ctx: ToolContext, a: dict) -> dict:
    name = norm(a.get("name", ""))
    if not name:
        raise ToolError("name is required")
    restrictions = None
    if a.get("restrictions") is not None:
        restrictions = []
        for r in _str_list(a["restrictions"]):
            c = domain.canon_restriction(r)
            if c is None:
                raise ToolError(f"unknown restriction '{r}'. use: {', '.join(domain.RESTRICTIONS)}")
            restrictions.append(c)
    dislikes = _str_list(a["dislikes"]) if a.get("dislikes") is not None else None
    if ctx.store.find_guest(name) is None:  # new guest: fill defaults
        restrictions, dislikes = restrictions or [], dislikes or []
    guest = {"name": name, "restrictions": restrictions, "dislikes": dislikes, "notes": a.get("notes")}
    saved, old = ctx.store.upsert_guest(guest)
    out = {"saved": saved["name"], "restrictions": saved.get("restrictions") or []}
    if old and old.get("restrictions") != saved.get("restrictions"):
        out["changed"] = {"from": old.get("restrictions"), "to": saved.get("restrictions")}
    return out


def list_guests(ctx: ToolContext, a: dict) -> dict:
    names = _str_list(a.get("names"))
    gs = ctx.store.guests()
    if names:
        gs = [g for g in (ctx.store.find_guest(n) for n in names) if g]
    return {"guests": [[g["name"], g.get("restrictions") or [], g.get("dislikes") or []] for g in gs]}


def _guests_for(ctx: ToolContext, names: list[str]) -> list[dict]:
    out = []
    for n in names:
        g = ctx.store.find_guest(n)
        out.append(g or {"name": norm(n), "restrictions": [], "dislikes": []})
    return out


def check_menu(ctx: ToolContext, a: dict) -> dict:
    ids = _str_list(a.get("dish_ids"))
    if not ids:
        raise ToolError("dish_ids is required")
    return domain.validate_menu(ids, _guests_for(ctx, _str_list(a.get("guests"))), a.get("max_prep"))


def save_menu(ctx: ToolContext, a: dict) -> dict:
    ids = _str_list(a.get("dish_ids"))
    guests = _str_list(a.get("guests"))
    date = a.get("date") or domain.next_friday(ctx.today).isoformat()
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise ToolError("date must be YYYY-MM-DD")
    v = domain.validate_menu(ids, _guests_for(ctx, guests), a.get("max_prep"))
    if not v["ok"]:
        raise ToolError("menu not saved: " + "; ".join(v["issues"]))
    n = ctx.store.add_menu({"date": date, "guests": [norm(g) for g in guests], "dish_ids": ids,
                            "max_prep": a.get("max_prep"), "notes": a.get("notes", "")})
    return {"saved": date, "dishes": len(ids), "menus_on_file": n}


def past_menus(ctx: ToolContext, a: dict) -> dict:
    ms = ctx.store.menus()[-int(a.get("limit", 2)):]
    out = []
    for m in ms:
        by_course: dict = {}
        for d in m["dish_ids"]:
            r = domain.recipe(d)
            if r:
                by_course.setdefault(r["course"], []).append(f"{r['id']}:{r['name']}")
        out.append({"date": m["date"], "guests": m["guests"], **by_course})
    return {"menus": out}


def shabbat_info(ctx: ToolContext, a: dict) -> dict:
    date = a.get("date")
    friday = dt.date.fromisoformat(date) if date else domain.next_friday(ctx.today)
    try:
        return external.shabbat_info(a.get("city", "גבעת שמואל"), friday, fetch=ctx.fetch)
    except external.ExternalError as e:
        raise ToolError(str(e))


# -------------------------------------------------------------- registry ---
_COURSE = {"type": "string", "enum": list(domain.COURSES)}
_RESTR = {"type": "array", "items": {"type": "string", "enum": list(domain.RESTRICTIONS)}}

SPECS: list[ToolSpec] = [
    ToolSpec("search_recipes",
             "Search the recipe catalog. Returns compact rows [id,name,course,kind,min,tags]. "
             "kind is meat/dairy/parve. tags: vegan, veg(etarian), gf (gluten-free), nf (nut-free).",
             {"type": "object", "properties": {
                 "course": _COURSE, "must": _RESTR,
                 "kind": {"type": "string", "enum": ["meat", "dairy", "parve"]},
                 "max_mins": {"type": "integer"}, "exclude": {"type": "array", "items": {"type": "string"}},
                 "query": {"type": "string", "description": "Hebrew substring of name/ingredient"},
                 "limit": {"type": "integer", "maximum": 10}}}, search_recipes),
    ToolSpec("save_guest",
             "Create or update a guest (first name). Passing restrictions REPLACES the old list.",
             {"type": "object", "properties": {
                 "name": {"type": "string"}, "restrictions": _RESTR,
                 "dislikes": {"type": "array", "items": {"type": "string"}}, "notes": {"type": "string"}},
              "required": ["name"]}, save_guest),
    ToolSpec("list_guests", "List saved guests as [name, restrictions, dislikes]. Optionally filter by names.",
             {"type": "object", "properties": {"names": {"type": "array", "items": {"type": "string"}}}}, list_guests),
    ToolSpec("check_menu",
             "Validate dish ids against kashrut (no meat+dairy), each guest's restrictions "
             "(every course needs a dish each guest can eat) and max prep minutes.",
             {"type": "object", "properties": {
                 "dish_ids": {"type": "array", "items": {"type": "string"}},
                 "guests": {"type": "array", "items": {"type": "string"}},
                 "max_prep": {"type": "integer"}}, "required": ["dish_ids"]}, check_menu),
    ToolSpec("save_menu",
             "Validate and save a Friday menu. Fails with the list of issues if invalid. date defaults to next Friday.",
             {"type": "object", "properties": {
                 "date": {"type": "string", "description": "YYYY-MM-DD"},
                 "dish_ids": {"type": "array", "items": {"type": "string"}},
                 "guests": {"type": "array", "items": {"type": "string"}},
                 "max_prep": {"type": "integer"}, "notes": {"type": "string"}},
              "required": ["dish_ids", "guests"]}, save_menu),
    ToolSpec("past_menus", "Most recent saved menus (default 2), dishes grouped by course.",
             {"type": "object", "properties": {"limit": {"type": "integer", "maximum": 5}}}, past_menus),
    ToolSpec("shabbat_info",
             "EXTERNAL (internet): candle-lighting & havdalah times, parasha, and Friday-evening "
             "temperature/rain chance for an Israeli city. date defaults to next Friday.",
             {"type": "object", "properties": {
                 "city": {"type": "string", "description": "e.g. גבעת שמואל"},
                 "date": {"type": "string", "description": "YYYY-MM-DD (a Friday)"}}}, shabbat_info,
             tags=["external"]),
]
BY_NAME = {s.name: s for s in SPECS}


def invoke(spec: ToolSpec, ctx: ToolContext, args: dict) -> str:
    """Run a tool, log it to the shared tool log, return compact text. Re-raises errors."""
    try:
        result = spec.fn(ctx, args or {})
    except Exception:
        ctx.store.log_tool(spec.name, args, ok=False)
        raise
    ctx.store.log_tool(spec.name, args, ok=True)
    return compact(result)
