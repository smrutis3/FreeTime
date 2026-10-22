"""FreeTime backend: k-ID gate proxy, parent loop, tier-aware suggestions."""
from __future__ import annotations

import asyncio
import base64
import re
import socket
import datetime as dt
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from tiers import CITIES, CIVIL_AGE, CONSENT_AGE, PERMISSION_FOR, PREAMBLE, TIER_PROMPTS

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
DATA = HERE / "data"

KID_API_KEY = os.getenv("KID_API_KEY") or os.getenv("KID_SECRET_KEY") or ""
KID_BASE = os.getenv("KID_API_BASE_URL", "https://game-api.test.k-id.com/api/v1").rstrip("/")
KID_MOCK = (not KID_API_KEY) or os.getenv("KID_MOCK") == "1"
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
SF_LAT, SF_LON = 37.7749, -122.4194
PERMISSION_NAMES = ["ai-chat", "ai-voice-mode", "ai-memory"]

ACTIVITIES: list[dict] = json.loads((DATA / "activities.json").read_text())
CALENDARS: dict[str, list] = json.loads((DATA / "calendars.json").read_text())
PROFILES: dict = json.loads((DATA / "profiles.json").read_text())

# In-memory state. No database, by design.
users: dict[str, dict] = {}
parents: dict[str, dict] = {}
suggestions: dict[str, dict] = {}
llm_cache: dict[tuple, list] = {}
mock_challenges: dict[str, dict] = {}
mock_sessions: dict[str, dict] = {}
known_accounts: dict[str, dict] = {}
notifications: dict[str, list] = {}    # parent_email -> [{id, child, text, category, reason, at, read}]   # email -> {name, ip, devices, last_seen}: adults seen on this network/device
weather_cache: dict[str, Any] = {}

app = FastAPI(title="FreeTime")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def now() -> dt.datetime:
    return dt.datetime.now()


def age_from_dob(dob: str) -> int:
    parts = [int(p) for p in dob.split("-")]
    while len(parts) < 3:
        parts.append(1)
    b = dt.date(*parts)
    t = dt.date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def tier_from_status(status: str) -> str:
    """Map k-ID ageStatus to our tier. DIGITAL_MINOR = below consent age."""
    s = (status or "").upper()
    if s == "DIGITAL_MINOR":
        return "child"
    if s == "LEGAL_ADULT":
        return "adult"
    return "teen"  # LEGAL_MINOR: between digital consent age and civil age


def city_info(city: str | None) -> dict:
    j, lat, lon, region, country = CITIES.get(city or "", CITIES["San Francisco"])
    return {"city": city if city in CITIES else "San Francisco", "jurisdiction": j, "lat": lat, "lon": lon, "region": region, "country": country}


def mock_status(dob: str, jurisdiction: str) -> str:
    age = age_from_dob(dob)
    if not jurisdiction or jurisdiction == "UNKNOWN":
        consent = 16                      # no parent yet: assume the strictest consent age
    else:
        country = jurisdiction.split("-")[0].upper()
        consent = CONSENT_AGE.get(country, 13)
    if age < consent:
        return "DIGITAL_MINOR"
    if age >= CIVIL_AGE:
        return "LEGAL_ADULT"
    return "LEGAL_MINOR"


def default_permissions(tier: str) -> list[dict]:
    if tier == "child":
        return [
            {"name": "ai-chat", "enabled": True, "managedBy": "GUARDIAN"},
            {"name": "ai-voice-mode", "enabled": True, "managedBy": "GUARDIAN"},
            {"name": "ai-memory", "enabled": False, "managedBy": "GUARDIAN"},
        ]
    return [{"name": n, "enabled": True, "managedBy": "PLAYER"} for n in PERMISSION_NAMES]


def allowed(user: dict, name: str) -> bool:
    return any(p.get("name") == name and p.get("enabled") for p in user.get("permissions", []))


def require(user: dict, action: str) -> None:
    perm = PERMISSION_FOR[action]
    if not allowed(user, perm):
        raise HTTPException(403, f"k-ID permission '{perm}' is not enabled for this user")


def get_user(uid: str) -> dict:
    u = users.get(uid)
    if not u:
        raise HTTPException(404, "unknown user; pass the age gate first")
    return u


def public_user(u: dict) -> dict:
    return {k: v for k, v in u.items() if k not in ("session_id",)} | {"session_id": u.get("session_id")}


def upsert_user(kuid: str, tier: str, dob: str, jurisdiction: str, permissions: list,
                session_id: str | None, name: str | None = None, parent_email: str | None = None,
                age_status: str | None = None) -> dict:
    persona = PROFILES["personas"][tier]
    u = users.get(kuid) or {
        "id": kuid, "prefs": {}, "feedback": {}, "about_me": "", "notes": "", "calendar": None,
    }
    u.update({
        "name": name or u.get("name") or "Friend",
        "tier": tier,
        "age_status": age_status,
        "dob": dob,
        "age": age_from_dob(dob) if dob else None,
        "jurisdiction": jurisdiction,
        "city": u.get("city"), "lat": u.get("lat"), "lon": u.get("lon"),
        "permissions": permissions or default_permissions(tier),
        "session_id": session_id,
        "parent_email": parent_email or u.get("parent_email"),
    })
    if tier == "teen":
        u.setdefault("quiz_done", bool(u.get("prefs")))
    if tier == "adult" and not u["about_me"]:
        u["about_me"] = PROFILES["adult"]["about_me"]
        u["notes"] = PROFILES["adult"]["notes"]
    users[kuid] = u
    if tier == "child" and u.get("parent_email"):
        parent_settings(u["parent_email"], u["id"])
    return u


def parent_settings(email: str, child_id: str | None = None) -> dict:
    p = parents.get(email)
    if not p:
        p = dict(PROFILES["parent_defaults"]) | {"parent_email": email, "children": [], "used": {}, "pending": [], "require_approval": False}
        p.pop("used_today_min", None)
        parents[email] = p
    if child_id and child_id not in p["children"]:
        p["children"].append(child_id)
        p["used"].setdefault(child_id, 0)
    return p


def budget_for(p: dict, child_id: str) -> dict:
    used = p["used"].get(child_id, 0)
    return {"total": p["daily_budget_min"], "used": used, "remaining": max(0, p["daily_budget_min"] - used)}


# ---- weather ----------------------------------------------------------------
async def get_weather(lat: float = SF_LAT, lon: float = SF_LON) -> dict:
    wkey = f"{round(lat, 2)},{round(lon, 2)}"
    hit = weather_cache.get(wkey)
    if hit and time.time() - hit["at"] < 600:
        return hit["data"]
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,precipitation,weather_code",
                    "hourly": "precipitation_probability",
                    "forecast_days": 1, "timezone": "America/Los_Angeles",
                },
            )
            j = r.json()
        hour = now().hour
        probs = j["hourly"]["precipitation_probability"]
        rain = max(probs[hour: hour + 4] or [0])
        temp = j["current"]["temperature_2m"]
        code = j["current"]["weather_code"]
        summary = "Clear" if code in (0, 1) else "Cloudy" if code in (2, 3) else "Foggy" if code in (45, 48) else "Rainy"
        data = {"temp_c": temp, "rain_prob": rain, "summary": summary}
    except Exception:
        data = {"temp_c": 18, "rain_prob": 10, "summary": "Clear (offline default)"}
    weather_cache[wkey] = {"at": time.time(), "data": data}
    return data


# ---- calendar gaps ----------------------------------------------------------
def _hm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _fmt(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def free_windows(user: dict) -> list[dict]:
    """Gaps in today's calendar between 09:00 and 21:00, from now onward."""
    events = user.get("calendar") or CALENDARS[user["tier"]]
    day_start, day_end = _hm("09:00"), _hm("21:00")
    if user["tier"] == "teen" and now().weekday() < 5:
        day_start = _hm("15:00")  # school hours blocked
    cursor = max(day_start, now().hour * 60 + now().minute)
    cursor = (cursor + 14) // 15 * 15
    gaps = []
    for e in sorted(events, key=lambda e: _hm(e["start"])):
        s, en = _hm(e["start"]), _hm(e["end"])
        if s - cursor >= 45:
            gaps.append({"start": _fmt(cursor), "end": _fmt(s), "minutes": s - cursor})
        cursor = max(cursor, en)
    if day_end - cursor >= 45:
        gaps.append({"start": _fmt(cursor), "end": _fmt(day_end), "minutes": day_end - cursor})
    return gaps


# ---- candidate filter -------------------------------------------------------
STOP = {"what","can","i","do","this","the","a","an","to","and","is","it","me","my","we","for","of","with","some","something","want","like","today","now","afternoon","morning","evening","go","get","have","please","any","anything","should"}


def candidates(user: dict, weather: dict, windows: list[dict], request: str = "") -> list[dict]:
    tier, age = user["tier"], user.get("age") or 30
    out = []
    longest = max([w["minutes"] for w in windows] or [0])
    p = parent_settings(user["parent_email"]) if tier == "child" and user.get("parent_email") else None
    remaining = budget_for(p, user["id"])["remaining"] if p else None
    words = {w.strip("?!.,'\"").lower() for w in request.split()} - STOP
    local = (user.get("city") or "San Francisco") == "San Francisco"
    for a in ACTIVITIES:
        if not local and a["area"] != "At home":
            continue
        if not (a["min_age"] <= age <= a["max_age"]):
            continue
        if weather["rain_prob"] > 60 and not a["indoor"]:
            continue
        if tier == "child":
            if a["category"] not in p["allowed_categories"]:
                continue
            if a["topic"] not in p.get("allowed_topics", []):
                continue
            if p["adult_required_only"] and not a["needs_adult"]:
                continue
            if remaining is not None and a["duration_min"] > remaining:
                continue
        if tier == "teen":
            if a["min_age"] >= 18:
                continue
            if longest and a["duration_min"] > longest:
                continue
        out.append(a)

    # thumbs feedback and quiz weighting (+1/-1 per tag)
    fb = user.get("feedback", {})
    prefs = user.get("prefs", {})
    def score(a: dict) -> float:
        s = sum(fb.get(t, 0) for t in a["tags"])
        hay = " ".join(a["tags"] + [a["title"].lower(), a["category"], a["area"].lower()])
        s += 3 * sum(1 for w in words if w and w in hay)          # the question steers the pool
        if words & {"quiet", "calm", "rest", "tired", "sleepy"} and "quiet" in a["tags"]: s += 3
        if words & {"outside", "outdoors", "park", "sun"} and not a["indoor"]: s += 2
        if words & {"inside", "home", "rain", "indoors"} and a["indoor"]: s += 2
        if prefs:
            if prefs.get("setting") == "indoor" and a["indoor"]: s += 1
            if prefs.get("setting") == "outdoor" and not a["indoor"]: s += 1
            if prefs.get("budget") == "free" and a["cost_usd"] == 0: s += 1
            if prefs.get("budget") == "cheap" and a["cost_usd"] <= 15: s += 0.5
            s += sum(1 for i in prefs.get("interests", []) if i in a["tags"] or i == a["category"])
        return s
    recent = set(user.get("recent", []))
    fresh = [a for a in out if a["id"] not in recent]
    if len(fresh) >= 4:
        out = fresh
    out.sort(key=score, reverse=True)
    return out[:12]


# ---- Claude -----------------------------------------------------------------
SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "activity_id": {"type": "string"},
                    "title": {"type": "string"},
                    "why": {"type": "string"},
                    "with": {"type": "string"},
                    "window": {"type": "string"},
                },
                "required": ["activity_id", "title", "why", "with", "window"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


def fallback_pick(user: dict, cands: list[dict], weather: dict, windows: list[dict]) -> list[dict]:
    picks = []
    w0 = windows[0] if windows else None
    for a in cands[:3]:
        if user["tier"] == "child":
            why = f"It's {weather['summary'].lower()} out, perfect for this!"
            title = f"{a['title']} 🎈"
        elif user["tier"] == "teen":
            why = f"{weather['summary']}, {round(weather['temp_c'])}°C. Fits before your 9 pm cutoff."
            title = a["title"]
        else:
            why = f"Fits your {w0['start']}-{w0['end']} gap; {weather['summary'].lower()} and {round(weather['temp_c'])}°C." if w0 else f"{weather['summary']} today."
            title = a["title"]
        picks.append({"activity_id": a["id"], "title": title, "why": why,
                      "with": "friends" if "friends" in a["tags"] else "solo",
                      "window": f"{w0['start']}-{w0['end']}" if w0 and user["tier"] == "adult" else ""})
    return picks


def call_claude(user: dict, text: str, mood: str | None, cands: list[dict], weather: dict,
                windows: list[dict]) -> list[dict]:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return fallback_pick(user, cands, weather, windows)
    import anthropic  # local import keeps startup fast when unused

    p = parent_settings(user["parent_email"]) if user["tier"] == "child" and user.get("parent_email") else None
    ctx = {
        "tier": user["tier"],
        "name": user["name"],
        "request": text,
        "mood": mood,
        "weather": weather,
        "free_windows": windows,
        "remaining_budget_min": budget_for(p, user["id"])["remaining"] if p else None,
        "quiz": user.get("prefs") if user["tier"] == "teen" else None,
        "thumbs": user.get("feedback") if user["tier"] == "teen" else None,
        "about_me": user.get("about_me") if user["tier"] == "adult" else None,
        "notes": user.get("notes") if user["tier"] == "adult" else None,
        "candidates": cands,
    }
    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=PREAMBLE + "\n\n" + TIER_PROMPTS[user["tier"]],
            messages=[{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if resp.stop_reason == "refusal":
            return fallback_pick(user, cands, weather, windows)
        payload = json.loads(next(b.text for b in resp.content if b.type == "text"))
        picks = payload["suggestions"]
    except Exception as e:  # never let the demo die on the LLM
        print("claude error:", repr(e))
        return fallback_pick(user, cands, weather, windows)
    valid_ids = {a["id"] for a in cands}
    picks = [s for s in picks if s.get("activity_id") in valid_ids][:3]
    if len(picks) < 3:
        seen = {s["activity_id"] for s in picks}
        for fb in fallback_pick(user, [a for a in cands if a["id"] not in seen], weather, windows):
            if len(picks) == 3:
                break
            picks.append(fb)
    return picks


# ---- child prompt safety classifier ----------------------------------------
RISK_WORDS = {
    "dangerous": ["gun", "knife", "weapon", "fire", "matches", "lighter", "explode", "bomb", "kill", "die", "suicide",
                  "hurt myself", "cut myself", "pills", "bleach", "poison", "drugs", "vape", "smoke", "alcohol", "beer",
                  "porn", "naked", "sex", "nude", "choke", "choking game", "jump off", "roof", "highway", "train tracks"],
    "concerning": ["alone", "by myself", "stranger", "meet someone", "met online", "online friend", "address", "secret",
                   "don't tell", "dont tell", "run away", "sneak out", "night", "midnight", "dare", "fight", "steal",
                   "gamble", "bet", "money", "credit card", "password", "scary", "blood", "hate", "bully"],
}
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["safe", "casual", "concerning", "dangerous"]},
        "reason": {"type": "string"},
        "child_reply": {"type": "string"},
    },
    "required": ["category", "reason", "child_reply"],
    "additionalProperties": False,
}


def classify_keywords(text: str) -> tuple[str, str]:
    t = " " + text.lower() + " "
    for cat in ("dangerous", "concerning"):
        for w in RISK_WORDS[cat]:
            if f" {w}" in t or f"{w} " in t:
                return cat, f"mentions '{w}'"
    return "safe", ""


def CLASSIFY_SYSTEM(tier: str) -> str:
    who = "young child" if tier == "child" else "teenager"
    reply = ("In child_reply write one warm sentence (under 15 words) for a six-year-old: for safe/casual say you have "
             "ideas; for concerning/dangerous gently say that's a question for a grown-up, no scolding."
             if tier == "child" else
             "In child_reply write one sentence (under 18 words) in a casual teen tone, no exclamation marks: for "
             "safe/casual say you've got ideas; for dangerous say plainly that's not something you'll help with and "
             "that a parent has been told, no lecture.")
    return (f"You review one message a {who} typed into a free-time activity app. Classify it: "
            "'safe' = ordinary request for things to do; 'casual' = chit-chat or off-topic but harmless; "
            "'concerning' = could put the user at risk or a parent would want to know (being alone, strangers, "
            "secrets, going out at night, money, meeting online friends); 'dangerous' = weapons, fire, drugs, "
            "self-harm, sexual content, serious physical risk. Be calm and proportionate: asking to play outside, "
            "go to the park or hang out with friends is safe. " + reply + " Return JSON only.")


def classify_prompt(text: str, child_name: str, tier: str = "child") -> dict:
    """safe | casual | concerning | dangerous. Keywords first, Claude refines when available."""
    kw_cat, kw_reason = classify_keywords(text)
    base = {"category": kw_cat, "reason": kw_reason, "child_reply": "", "source": "keywords"}
    if not os.getenv("ANTHROPIC_API_KEY"):
        return base
    import anthropic
    try:
        resp = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=400,
            system=CLASSIFY_SYSTEM(tier),
            messages=[{"role": "user", "content": json.dumps({"child_name": child_name, "message": text})}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA}},
        )
        if resp.stop_reason == "refusal":
            return base | {"category": "dangerous", "reason": "declined by safety filter"}
        j = json.loads(next(b.text for b in resp.content if b.type == "text"))
        order = ["safe", "casual", "concerning", "dangerous"]
        # never let the model downgrade a keyword hit below 'concerning'
        cat = j["category"] if order.index(j["category"]) >= order.index(kw_cat) or kw_cat == "safe" else kw_cat
        return {"category": cat, "reason": j["reason"] or kw_reason, "child_reply": j["child_reply"], "source": "claude"}
    except Exception as e:
        print("classify error:", repr(e))
        return base


def notify_parent(user: dict, text: str, cls: dict) -> dict:
    n = {"id": "n_" + uuid.uuid4().hex[:8], "child": user["name"], "child_id": user["id"], "text": text,
         "category": cls["category"], "reason": cls["reason"], "at": time.time(), "read": False}
    notifications.setdefault(user["parent_email"], []).append(n)
    return n


# ---- agent: context + live web search (teen, adult) --------------------------
def web_tool(u: dict) -> dict:
    ci = city_info(u.get("city"))
    return {"type": "web_search_20260209", "name": "web_search", "max_uses": 3,
            "user_location": {"type": "approximate", "city": ci["city"], "region": ci["region"], "country": ci["country"]}}
AGENT_RULES = {
    "child": ("The user is a young child and a parent has approved the topics listed in allowed_topics. Only family "
              "activities a grown-up joins: playgrounds, parks, libraries, museums, zoos, pools, family workshops, things "
              "at home. Daytime only, no bars, no nightlife, no addresses, no prices in \"why\". Title under 6 words, "
              "\"why\" under 10 words, one emoji in the title. Set \"category\" to one of outdoor, sports, learning, "
              "creative, games, social, food and \"topic\" to one of education, entertainment, hobby."),
    "teen": ("The user is a teenager. Casual, direct, no exclamation marks. Only all-ages or under-18-friendly places and "
             "events: nothing 18+/21+, no bars or clubs, nothing after 21:00, nothing that needs a car alone. Give the "
             "neighbourhood, not a street address. Add \"with\": \"solo\" or \"friends\" and 3 short tags."),
    "adult": ("The user is an adult. Concise and specific. Fit each pick inside one of the free windows and set "
              "\"window\" to it like \"14:00-16:00\". Show cost. Reference their notes or goals in \"why\" when relevant."),
}
AGENT_PREAMBLE = (
    "You are FreeTime's planner for the user's city (see home_city). You get the user's context (date, weekday, time, weather, free "
    "windows, interests, notes) and a list of known_options. Read the request carefully. If it names an event, a "
    "place type, a day ('Friday'), 'tonight', 'this weekend', a neighbourhood, or anything the known_options don't "
    "cover, use web_search (at most 3 quick searches, then answer) to find real, current, specific options: venues, "
    "events, classes, meetups, with dates and prices. Prefer things happening on the day asked. Otherwise you may pick "
    "from known_options. Be fast: no deliberation, no extra verification passes. Keep \"why\" under 25 words. "
    "Return exactly three picks as JSON only, no prose before or after: "
    "{\"suggestions\":[{\"activity_id\": \"<id from known_options or null>\", \"title\": str, \"why\": str (one "
    "sentence that cites the weather, a free window or the person's interest), \"duration_min\": int, \"cost_usd\": "
    "int, \"indoor\": bool, \"area\": str, \"when\": str (e.g. 'Fri 19:00' or 'today 14:00-16:00'), \"source_url\": "
    "str or null, \"with\": str, \"window\": str, \"tags\": [str]}]}. Never invent a venue or event: if it is not from "
    "known_options it must come from a search result with its source_url."
)


def _json_from_text(txt: str) -> dict:
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}


WEB_WORDS = {"party", "parties", "event", "events", "concert", "gig", "show", "shows", "tonight", "weekend", "monday", "tuesday",
             "wednesday", "thursday", "friday", "saturday", "sunday", "class", "classes", "workshop", "market", "festival",
             "game", "match", "meetup", "open", "mic", "exhibition", "exhibit", "movie", "movies", "film", "screening",
             "where", "near", "nearby", "happening", "new", "best", "live", "music", "dance", "skate", "pop-up", "popup",
             "fair", "tournament", "league", "team", "club", "lesson", "lessons", "tour", "trivia", "karaoke", "comedy"}


def needs_web(text: str) -> bool:
    words = {w.strip("?!.,'\"").lower() for w in text.split()}
    return bool(words & WEB_WORDS)


def agent_suggest(user: dict, text: str, mood: str | None, cands: list[dict], weather: dict, windows: list[dict]) -> list[dict] | None:
    """Web-aware planner. Returns None on any failure so the catalogue path takes over."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    n = now()
    must_search = needs_web(text) or city_info(user.get("city"))["city"] != "San Francisco" or len(cands) < 3
    ctx = {
        "request": text, "mood": mood, "name": user["name"], "tier": user["tier"],
        "date": n.strftime("%Y-%m-%d"), "weekday": n.strftime("%A"), "time_now": n.strftime("%H:%M"),
        "weather": weather, "free_windows": windows,
        "interests": user.get("prefs") if user["tier"] == "teen" else None,
        "thumbs": user.get("feedback") if user["tier"] == "teen" else None,
        "about_me": user.get("about_me") if user["tier"] == "adult" else None,
        "notes": user.get("notes") if user["tier"] == "adult" else None,
        "home_city": city_info(user.get("city"))["city"],
        "home_area": ("Mission" if user["tier"] != "adult" else "SoMa") if city_info(user.get("city"))["city"] == "San Francisco" else "city centre",
        "allowed_topics": (parent_settings(user["parent_email"]).get("allowed_topics") if user["tier"] == "child" and user.get("parent_email") else None),
        "known_options": [{k: a[k] for k in ("id", "title", "category", "indoor", "duration_min", "cost_usd", "area", "tags")} for a in cands],
        "instruction": ("This request is about events, places or a specific day. You MUST call web_search at least twice "
                        "(e.g. 'teen events San Francisco Friday', 'all-ages ... Mission this week') before answering, and at "
                        "least two of the three picks must come from search results with source_url. known_options are only "
                        "a fallback for the third pick. Stop searching after 3 calls and answer with what you have.") if must_search else
                       ("Pick from known_options unless something better and current is easy to find; searching is optional."),
    }
    try:
        resp = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=2500,
            system=AGENT_PREAMBLE + "\n\n" + AGENT_RULES[user["tier"]],
            tools=[web_tool(user)],
            messages=[{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
            output_config={"effort": "low"},
        )
        if resp.stop_reason == "refusal":
            return None
        searched = sum(1 for b in resp.content if b.type == "server_tool_use")
        print(f"agent: must_search={must_search} searches={searched} stop={resp.stop_reason}")
        txt = "\n".join(b.text for b in resp.content if b.type == "text")
        picks = _json_from_text(txt).get("suggestions") or []
    except Exception as e:
        print("agent error:", repr(e))
        return None
    out = []
    for i, sp in enumerate(picks[:3]):
        if not sp.get("title"):
            continue
        sp["_searched"] = searched
        out.append(sp)
    return out if len(out) == 3 else None


# ----------------------------------------------------------------------------
# k-ID gate (server-side; the API key never reaches the browser)
# ----------------------------------------------------------------------------
class AgeGateReq(BaseModel):
    dateOfBirth: Optional[str] = None
    age: Optional[int] = None
    city: Optional[str] = None
    jurisdiction: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    parent_email: Optional[str] = None


def remember_account(email: str | None, name: str | None, ip: str, device: str | None):
    if not email:
        return
    acc = known_accounts.setdefault(email, {"email": email, "name": name or email.split("@")[0], "ip": ip, "devices": set()})
    acc.update(name=name or acc["name"], ip=ip, last_seen=time.time())
    if device:
        acc["devices"].add(device)


async def kid_request(method: str, path: str, **kw) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, f"{KID_BASE}{path}",
                            headers={"Authorization": f"Bearer {KID_API_KEY}"}, **kw)
    if r.status_code >= 400:
        raise HTTPException(502, f"k-ID {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def user_from_session(sess: dict, dob: str, name: str | None, parent_email: str | None) -> dict:
    status = sess.get("ageStatus", "")
    tier = tier_from_status(status)
    return upsert_user(
        kuid=sess.get("kuid") or sess.get("sessionId") or str(uuid.uuid4()),
        tier=tier, dob=sess.get("dateOfBirth") or dob, jurisdiction=sess.get("jurisdiction", "US-CA"),
        permissions=sess.get("permissions") or default_permissions(tier),
        session_id=sess.get("sessionId"), name=name, parent_email=parent_email, age_status=status,
    )


@app.post("/api/kid/age-gate")
async def kid_age_gate(body: AgeGateReq, request: Request, x_device: str | None = Header(default=None)):
    """Age gate -> PASS (session), CHALLENGE (parental consent), or PROHIBITED."""
    if not body.dateOfBirth and body.age is None:
        raise HTTPException(400, "age or dateOfBirth required")
    if not body.dateOfBirth:
        body.dateOfBirth = f"{dt.date.today().year - body.age}-01-01"  # k-ID guidance: age -> YYYY-01-01
    if body.age is not None and body.age < 3:
        return {"status": "PROHIBITED", "mock": KID_MOCK}
    ci = city_info(body.city) if body.city else None
    if ci:
        body.jurisdiction = ci["jurisdiction"]
    elif not body.jurisdiction:
        body.jurisdiction = "UNKNOWN"        # under-16 path: inherits the parent's city at approval
    if KID_MOCK:
        status = mock_status(body.dateOfBirth, body.jurisdiction)
        if status == "DIGITAL_MINOR":
            cid = str(uuid.uuid4())
            mock_challenges[cid] = {"challengeId": cid, "state": "PENDING", "dob": body.dateOfBirth,
                                    "jurisdiction": body.jurisdiction, "name": body.name,
                                    "parent_email": None, "device": x_device, "ip": request.client.host,
                                    "created": time.time(), "oneTimePassword": str(uuid.uuid4().int)[:6]}
            return {"status": "CHALLENGE", "mock": True,
                    "challenge": {"challengeId": cid, "url": f"/parent?challenge={cid}",
                                  "oneTimePassword": mock_challenges[cid]["oneTimePassword"]}}
        tier = tier_from_status(status)
        sid = str(uuid.uuid4())
        sess = {"sessionId": sid, "kuid": str(uuid.uuid4()), "ageStatus": status,
                "dateOfBirth": body.dateOfBirth, "jurisdiction": body.jurisdiction,
                "permissions": default_permissions(tier)}
        mock_sessions[sid] = sess
        u = user_from_session(sess, body.dateOfBirth, body.name, body.parent_email)
        if ci:
            u.update(city=ci["city"], lat=ci["lat"], lon=ci["lon"])
        if tier == "adult":
            remember_account(body.email, body.name, request.client.host, x_device)
            u["email"] = body.email
        return {"status": "PASS", "mock": True, "user": public_user(u)}

    j = await kid_request("POST", "/age-gate/check",
                          json={"dateOfBirth": body.dateOfBirth, "jurisdiction": body.jurisdiction if body.jurisdiction != "UNKNOWN" else "US-CA"})
    status = j.get("status")
    if status == "PASS" and j.get("session"):
        u = user_from_session(j["session"], body.dateOfBirth, body.name, body.parent_email)
        if ci:
            u.update(city=ci["city"], lat=ci["lat"], lon=ci["lon"])
        if u["tier"] == "adult":
            remember_account(body.email, body.name, request.client.host, x_device)
            u["email"] = body.email
        return {"status": "PASS", "user": public_user(u)}
    if status == "CHALLENGE":
        ch = j.get("challenge", {})
        mock_challenges[ch.get("challengeId", "")] = {"dob": body.dateOfBirth, "name": body.name, "state": "PENDING",
                                                       "parent_email": None, "real": True, "device": x_device,
                                                       "ip": request.client.host, "created": time.time()}
        return {"status": "CHALLENGE", "challenge": ch}
    return {"status": status or "PROHIBITED", "raw": j}


@app.get("/api/kid/challenge/{challenge_id}")
async def kid_challenge_status(challenge_id: str):
    """Poll parental consent. On PASS, materialise the session and the user."""
    meta = mock_challenges.get(challenge_id, {})
    if KID_MOCK:
        if not meta:
            raise HTTPException(404, "unknown challenge")
        if meta["state"] == "PASS" and meta.get("user_id"):
            return {"state": "PASS", "user": public_user(users[meta["user_id"]])}
        return {"state": meta["state"]}

    j = await kid_request("GET", "/challenge/get-status", params={"challengeId": challenge_id})
    state = j.get("state") or j.get("status")
    if state == "PASS" and j.get("sessionId"):
        sess = await kid_request("GET", "/session/get", params={"sessionId": j["sessionId"]})
        sess = sess.get("session", sess)
        u = user_from_session(sess, meta.get("dob", ""), meta.get("name"), meta.get("parent_email"))
        par = parents.get(meta.get("parent_email") or "")
        if par and par.get("city"):
            ci = city_info(par["city"]); u.update(city=ci["city"], lat=ci["lat"], lon=ci["lon"])
            try:
                await kid_request("POST", "/session/update-jurisdiction", json={"sessionId": j["sessionId"], "jurisdiction": ci["jurisdiction"]})
                u["jurisdiction"] = ci["jurisdiction"]
            except HTTPException:
                pass
        return {"state": "PASS", "user": public_user(u)}
    return {"state": state, "raw": j}


class SessionReq(BaseModel):
    sessionId: Optional[str] = None
    claimToken: Optional[str] = None
    user_id: Optional[str] = None


@app.post("/api/kid/claim")
async def kid_claim(body: SessionReq):
    """Refresh permissions for a session (used by /settings and the SDK path)."""
    sid = body.sessionId or (users.get(body.user_id or "", {}).get("session_id"))
    if not sid:
        raise HTTPException(400, "sessionId required")
    if KID_MOCK:
        sess = mock_sessions.get(sid)
        if not sess:
            raise HTTPException(404, "unknown session")
    else:
        sess = await kid_request("GET", "/session/get", params={"sessionId": sid})
        sess = sess.get("session", sess)
    u = user_from_session(sess, sess.get("dateOfBirth", ""), None, None)
    return {"user_id": u["id"], "tier": u["tier"], "user": public_user(u)}


# ---- account linking: child picks a grown-up's account, no QR ---------------
@app.get("/api/kid/link-suggestions")
def link_suggestions(request: Request, x_device: str | None = Header(default=None)):
    """Grown-up accounts seen on this device or this network, most recent first."""
    ip = request.client.host
    out = []
    for a in known_accounts.values():
        same_device = bool(x_device and x_device in a["devices"])
        same_net = a["ip"].rsplit(".", 1)[0] == ip.rsplit(".", 1)[0]
        if same_device or same_net:
            out.append({"email": a["email"], "name": a["name"], "last_seen": a.get("last_seen"),
                        "via": "this device" if same_device else "this Wi-Fi"})
    out.sort(key=lambda a: -(a["last_seen"] or 0))
    return {"accounts": out[:5]}


class ParentLogin(BaseModel):
    email: str
    name: Optional[str] = None
    city: Optional[str] = None
    age: Optional[int] = None


@app.post("/api/parent/login")
def parent_login(body: ParentLogin, request: Request, x_device: str | None = Header(default=None)):
    p = parent_settings(body.email)
    ci = city_info(body.city)
    p.update(city=ci["city"], jurisdiction=ci["jurisdiction"], lat=ci["lat"], lon=ci["lon"], name=body.name or p.get("name"),
             age=body.age or p.get("age"))
    remember_account(body.email, body.name, request.client.host, x_device)
    return {"ok": True, "city": p["city"], "jurisdiction": p["jurisdiction"]}


class ParentChat(BaseModel):
    email: str


@app.post("/api/parent/chat")
async def parent_chat(body: ParentChat, request: Request, x_device: str | None = Header(default=None)):
    """The parent's own adult session, through the same gate as everyone else."""
    p = parents.get(body.email)
    if not p:
        raise HTTPException(404, "create the parent account first")
    if p.get("user_id") and p["user_id"] in users:
        return {"user": public_user(users[p["user_id"]])}
    r = await kid_age_gate(AgeGateReq(age=p.get("age") or 35, city=p.get("city"), name=p.get("name") or body.email.split("@")[0], email=body.email), request, x_device)
    if r.get("status") != "PASS":
        raise HTTPException(409, f"gate returned {r.get('status')}")
    u = users[r["user"]["id"]]
    u["parent_of"] = p["children"]
    p["user_id"] = u["id"]
    return {"user": public_user(u)}


class LinkReq(BaseModel):
    challengeId: str
    parent_email: str


@app.post("/api/kid/link-request")
async def link_request(body: LinkReq):
    """Ask a specific grown-up to approve. Real mode: k-ID emails them a Family Connect link."""
    m = mock_challenges.get(body.challengeId)
    if not m:
        raise HTTPException(404, "unknown challenge")
    m["parent_email"] = body.parent_email
    m["requested_at"] = time.time()
    parent_settings(body.parent_email)
    if m.get("real"):
        await kid_request("POST", "/challenge/send-email", json={"challengeId": body.challengeId, "email": body.parent_email})
        return {"state": "PENDING", "sent": "email via k-ID Family Connect"}
    return {"state": "PENDING", "sent": "in-app request (mock)"}


class LinkByCode(BaseModel):
    code: str
    parent_email: str


@app.post("/api/kid/link-by-code")
async def link_by_code(body: LinkByCode):
    """Parent types the 6-digit code shown on the child's screen (mock stand-in for k-ID's OTP)."""
    for cid, m in mock_challenges.items():
        if m.get("state") == "PENDING" and m.get("oneTimePassword") == body.code.strip():
            return await link_request(LinkReq(challengeId=cid, parent_email=body.parent_email))
    raise HTTPException(404, "No waiting child with that code")


# ---- mock-only helpers so the parent loop works with no k-ID key ------------
@app.get("/api/kid/mock-challenges")
def kid_mock_challenges(email: str | None = None):
    """Pending link requests addressed to this parent (both mock and real, for display)."""
    return [{"challengeId": c, "name": m.get("name"), "parent_email": m.get("parent_email"), "real": bool(m.get("real")),
             "requested_at": m.get("requested_at")}
            for c, m in mock_challenges.items()
            if m.get("state") == "PENDING" and m.get("parent_email") and (email is None or m["parent_email"] == email)]


class MockDecision(BaseModel):
    challengeId: str
    decision: str  # PASS | FAIL
    voice: bool = True
    allowed_topics: Optional[list[str]] = None
    allowed_categories: Optional[list[str]] = None
    adult_required_only: Optional[bool] = None
    daily_budget_min: Optional[int] = None


@app.post("/api/kid/mock-approve")
def kid_mock_approve(body: MockDecision):
    m = mock_challenges.get(body.challengeId)
    if not m or m.get("real"):
        raise HTTPException(404, "unknown mock challenge")
    if body.decision != "PASS":
        m["state"] = "FAIL"
        return {"state": "FAIL"}
    sid = str(uuid.uuid4())
    par = parent_settings(m["parent_email"])
    ci = city_info(par.get("city"))                      # the child lives where the parent lives
    status = mock_status(m["dob"], ci["jurisdiction"])   # re-derive the band in the parent's country
    tier = tier_from_status(status)
    perms = default_permissions(tier)
    if tier == "child":
        for p in perms:
            if p["name"] == "ai-voice-mode":
                p["enabled"] = body.voice
    sess = {"sessionId": sid, "kuid": str(uuid.uuid4()), "ageStatus": status,
            "dateOfBirth": m["dob"], "jurisdiction": ci["jurisdiction"], "permissions": perms}
    mock_sessions[sid] = sess
    u = user_from_session(sess, m["dob"], m.get("name"), m.get("parent_email"))
    u.update(city=ci["city"], lat=ci["lat"], lon=ci["lon"])
    m.update(state="PASS", user_id=u["id"])
    p = parent_settings(u["parent_email"], u["id"])
    for k in ("allowed_topics", "allowed_categories", "adult_required_only", "daily_budget_min"):
        v = getattr(body, k)
        if v is not None:
            p[k] = v
    return {"state": "PASS", "user": public_user(u)}


class MockPerm(BaseModel):
    user_id: str
    name: str
    enabled: bool


@app.post("/api/kid/mock-permission")
def kid_mock_permission(body: MockPerm):
    """Stand-in for a parent flipping a permission in Family Connect."""
    u = get_user(body.user_id)
    for p in u["permissions"]:
        if p["name"] == body.name:
            p["enabled"] = body.enabled
    if u.get("session_id") in mock_sessions:
        mock_sessions[u["session_id"]]["permissions"] = u["permissions"]
    return public_user(u)


# ---- "what changed" summary shown to judges --------------------------------
def adaptation(user: dict) -> dict:
    tier = user["tier"]
    country = (user.get("jurisdiction") or "US").split("-")[0].upper()
    consent_age = CONSENT_AGE.get(country, 13)
    p = parent_settings(user["parent_email"]) if tier == "child" else None
    base = {
        "tier": tier, "age": user.get("age"), "jurisdiction": user.get("jurisdiction"), "city": user.get("city"),
        "age_status": user.get("age_status"), "consent_age": consent_age, "civil_age": CIVIL_AGE,
        "age_source": "k-ID (mock rules)" if KID_MOCK else "k-ID age gate",
        "permissions": user.get("permissions", []),
    }
    if tier == "child":
        base |= {"gate": "parental consent in Family Connect before anything is shown",
                 "approval": "a parent approves every suggestion" if p.get("require_approval") else "none needed; a parent is notified only if an ask looks risky",
                 "filters": [f"only topics a parent allowed ({', '.join(p.get('allowed_topics', []))})",
                             f"only categories a parent allowed ({', '.join(p['allowed_categories'])})",
                             f"daily free-time budget {p['daily_budget_min']} min",
                             "no prices, no addresses, nothing alone"] + (["only activities a grown-up joins"] if p["adult_required_only"] else []),
                 "tone": "six-year-old, big cards, emoji, read aloud", "memory": "off: nothing remembered",
                 "connectors": "none"}
    elif tier == "teen":
        base |= {"gate": "age gate only, no consent", "approval": "none" + ("; a parent is alerted on dangerous asks" if user.get("parent_email") else ""),
                 "filters": ["school hours blocked on weekdays", "9 pm cutoff", "no 18+ activities", "neighbourhood only, no exact locations"],
                 "tone": "casual, direct, no exclamation marks", "memory": "quiz + thumbs, in memory only",
                 "connectors": "none: under-18 privacy"}
    else:
        base |= {"gate": "age gate only", "approval": "none", "filters": ["none"],
                 "tone": "concise, time-boxed to calendar gaps, shows cost",
                 "memory": "about-me, notes and calendar", "connectors": "calendar (.ics), notes, profile"}
    return base


class CompareReq(BaseModel):
    ages: list[int] = [8, 14, 30]
    jurisdictions: list[str] = ["US-CA", "DE", "BR"]


@app.post("/api/compare")
async def compare(body: CompareReq):
    """Same person, several countries: what k-ID decides for each cell."""
    cells = []
    for j in body.jurisdictions:
        for a in body.ages:
            dob = f"{dt.date.today().year - a}-01-01"
            if KID_MOCK:
                status = mock_status(dob, j)
                st = "CHALLENGE" if status == "DIGITAL_MINOR" else "PASS"
            else:
                try:
                    r = await kid_request("POST", "/age-gate/check", json={"dateOfBirth": dob, "jurisdiction": j})
                    st = r.get("status")
                    status = (r.get("session") or {}).get("ageStatus") or ("DIGITAL_MINOR" if st == "CHALLENGE" else "")
                except HTTPException as e:
                    st, status = "ERROR", str(e.detail)[:80]
            tier = tier_from_status(status) if st != "ERROR" else None
            country = j.split("-")[0].upper()
            cells.append({"age": a, "jurisdiction": j, "status": st, "age_status": status, "tier": tier,
                          "consent_age": CONSENT_AGE.get(country, 13),
                          "needs_parent": st == "CHALLENGE",
                          "voice": tier != "child" or True, "memory": tier != "child",
                          "approval": tier == "child", "connectors": tier == "adult"})
    return {"cells": cells, "source": "k-ID mock rules" if KID_MOCK else "k-ID test API"}


# ----------------------------------------------------------------------------
# App endpoints
# ----------------------------------------------------------------------------
def lan_ip() -> str:
    try:
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sk.connect(("8.8.8.8", 80)); ip = sk.getsockname()[0]; sk.close(); return ip
    except Exception:
        return "localhost"


@app.get("/api/cities")
def cities():
    return [{"city": c, "jurisdiction": v[0], "country": v[4]} for c, v in CITIES.items()]


@app.get("/api/health")
def health():
    return {"ok": True, "lan_ip": lan_ip(), "web_search": True, "kid_mock": KID_MOCK, "kid_base": KID_BASE, "model": MODEL,
            "claude": bool(os.getenv("ANTHROPIC_API_KEY")), "modulate": bool(os.getenv("MODULATE_KEY")), "inworld": bool(os.getenv("INWORLD_KEY"))}


@app.get("/api/weather")
async def weather(lat: float = SF_LAT, lon: float = SF_LON):
    return await get_weather(lat, lon)


def user_weather(u: dict):
    return get_weather(u.get("lat") or SF_LAT, u.get("lon") or SF_LON)


@app.get("/api/me/{uid}")
async def me(uid: str):
    u = get_user(uid)
    w = await user_weather(u)
    out = {"user": public_user(u), "weather": w, "windows": free_windows(u),
           "calendar": u.get("calendar") or CALENDARS[u["tier"]], "adaptation": adaptation(u)}
    if u["tier"] == "child":
        p = parent_settings(u["parent_email"], u["id"])
        out["budget"] = budget_for(p, u["id"])
        out["rules"] = {k: p[k] for k in ("allowed_topics", "allowed_categories", "adult_required_only", "require_approval", "daily_budget_min")}
        out["topics"] = PROFILES["topics"]
    if u["tier"] == "teen":
        out["quiz"] = PROFILES["teen"]["questions"]
        out["quiz_done"] = bool(u.get("quiz_done"))
    return out


class SuggestReq(BaseModel):
    user_id: str
    text: str
    mood: Optional[str] = None


@app.post("/api/suggest")
async def suggest(body: SuggestReq):
    u = get_user(body.user_id)
    if not allowed(u, "ai-chat"):
        raise HTTPException(403, "k-ID permission 'ai-chat' is not enabled")
    w = await user_weather(u)
    windows = free_windows(u)
    cands = candidates(u, w, windows, body.text)
    if not cands and not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(409, "Nothing fits right now (budget, weather or calendar). Try later.")
    key = (u["id"], body.text.strip().lower(), body.mood or "", json.dumps(u.get("feedback"), sort_keys=True))
    flag = None
    p = parent_settings(u["parent_email"], u["id"]) if u["tier"] == "child" and u.get("parent_email") else None
    def cache_get(k):
        hit = llm_cache.get(k)
        return hit[1] if hit and time.time() - hit[0] < 90 else None   # 90 s: a retry is instant, a new ask is fresh

    def plan(safe_text):
        local = city_info(u.get("city"))["city"] == "San Francisco"
        if u["tier"] != "child" or not local or len(cands) < 4:
            got = agent_suggest(u, safe_text, body.mood, cands, w, windows)
            if got:
                return got
        return call_claude(u, safe_text, body.mood, cands, w, windows)

    if u["tier"] in ("child", "teen"):
        ckey = ("cls", u["tier"], body.text.strip().lower())
        cls = cache_get(ckey)
        picks = cache_get(key)
        jobs = []
        if cls is None:
            jobs.append(asyncio.to_thread(classify_prompt, body.text, u["name"], u["tier"]))
        if picks is None:
            safe_text = body.text if classify_keywords(body.text)[0] == "safe" else "something fun and safe to do this afternoon"
            jobs.append(asyncio.to_thread(plan, safe_text))
        results = await asyncio.gather(*jobs) if jobs else []
        if cls is None:
            cls = results.pop(0); llm_cache[ckey] = (time.time(), cls)
        if picks is None:
            picks = results.pop(0); llm_cache[key] = (time.time(), picks)
        alert_on = ("concerning", "dangerous") if u["tier"] == "child" else ("dangerous",)
        if cls["category"] in alert_on:
            flag = {"category": cls["category"], "reason": cls["reason"], "alerted": bool(u.get("parent_email")),
                    "message": cls.get("child_reply") or ("That's a question for a grown-up. Here are some other ideas!" if u["tier"] == "child" else "Not something I'll help with. A parent has been told.")}
            if u.get("parent_email") and not any(n["text"] == body.text and n["child_id"] == u["id"] for n in notifications.get(u["parent_email"], [])):
                notify_parent(u, body.text, cls)
        elif cls.get("child_reply"):
            flag = {"category": cls["category"], "message": cls["child_reply"]}
    else:
        picks = cache_get(key)
        if picks is None:
            picks = await asyncio.to_thread(plan, body.text)
            llm_cache[key] = (time.time(), picks)
    needs_approval = bool(p and p.get("require_approval"))
    by_id = {a["id"]: a for a in ACTIVITIES}
    out = []
    for s in picks:
        a = by_id.get(s.get("activity_id") or "")
        if a:
            base = {"activity_id": a["id"], "duration_min": a["duration_min"], "cost_usd": a["cost_usd"], "indoor": a["indoor"],
                    "area": a["area"], "needs_adult": a["needs_adult"], "category": a["category"], "topic": a["topic"],
                    "tags": a["tags"], "source_url": s.get("source_url"), "when": s.get("when")}
        else:  # found on the web by the agent
            base = {"activity_id": None, "duration_min": int(s.get("duration_min") or 90), "cost_usd": int(s.get("cost_usd") or 0),
                    "indoor": bool(s.get("indoor")), "area": s.get("area") or city_info(u.get("city"))["city"], "needs_adult": u["tier"] == "child",
                    "category": s.get("category") or "web", "topic": s.get("topic") or "entertainment", "tags": s.get("tags") or [], "source_url": s.get("source_url"),
                    "when": s.get("when")}
        sug = base | {
            "id": "s_" + uuid.uuid4().hex[:8], "user_id": u["id"],
            "title": s["title"], "why": s["why"], "searched": bool(s.get("_searched")),
            "needs_approval": needs_approval,
            "status": "pending" if needs_approval else "none",
            "with": s.get("with") if u["tier"] == "teen" else None,
            "window": s.get("window") if u["tier"] == "adult" else None,
            "created": time.time(),
        }
        suggestions[sug["id"]] = sug
        if needs_approval:
            p["pending"].append(sug["id"])
        out.append(sug)
    u["recent"] = ([x["activity_id"] for x in out if x["activity_id"]] + u.get("recent", []))[:6]
    return {"suggestions": out, "weather": w, "windows": windows, "flag": flag, "searched": any(x["searched"] for x in out)}


class CalendarAdd(BaseModel):
    user_id: str
    suggestion_id: str


def _ics(title: str, start: dt.datetime, end: dt.datetime, desc: str, loc: str) -> str:
    f = lambda d: d.strftime("%Y%m%dT%H%M%S")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FreeTime//EN", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@freetime", f"DTSTAMP:{f(dt.datetime.utcnow())}Z",
        f"DTSTART;TZID=America/Los_Angeles:{f(start)}", f"DTEND;TZID=America/Los_Angeles:{f(end)}",
        f"SUMMARY:{title}", f"DESCRIPTION:{desc}", f"LOCATION:{loc}, San Francisco",
        "END:VEVENT", "END:VCALENDAR", ""])


@app.post("/api/calendar/add")
def calendar_add(body: CalendarAdd):
    """Put a suggestion on today's calendar: updates the in-app calendar (so free windows shrink)
    and returns an .ics the browser hands to Apple/Google Calendar."""
    u = get_user(body.user_id)
    s = suggestions.get(body.suggestion_id)
    if not s or s["user_id"] != u["id"]:
        raise HTTPException(410, "That idea expired (server restarted). Ask again and pick it fresh.")
    if s.get("window"):
        start_s, end_s = s["window"].split("-")
    else:
        w = free_windows(u)
        if not w:
            raise HTTPException(409, "no free window left today")
        start_s = w[0]["start"]; end_s = _fmt(min(_hm(w[0]["end"]), _hm(start_s) + s["duration_min"]))
    cal = list(u.get("calendar") or CALENDARS[u["tier"]])
    cal.append({"title": s["title"], "start": start_s, "end": end_s, "added": True})
    u["calendar"] = cal
    s["status"] = "added"
    u.setdefault("chosen", []).append({"title": s["title"], "start": start_s, "end": end_s, "duration_min": s["duration_min"], "at": time.time()})
    if u["tier"] == "child" and u.get("parent_email"):
        pp = parent_settings(u["parent_email"], u["id"])
        pp["used"][u["id"]] = min(pp["daily_budget_min"], pp["used"].get(u["id"], 0) + s["duration_min"])
    llm_cache.clear()
    today = dt.date.today()
    st = dt.datetime.combine(today, dt.time(*map(int, start_s.split(":"))))
    en = dt.datetime.combine(today, dt.time(*map(int, end_s.split(":"))))
    ics = _ics(s["title"], st, en, s["why"], s["area"])
    return {"ok": True, "event": cal[-1], "ics": ics, "calendar": cal, "windows": free_windows(u)}


@app.get("/api/child/{uid}/pending")
def child_pending(uid: str):
    u = get_user(uid)
    mine = sorted((s for s in suggestions.values() if s["user_id"] == uid), key=lambda s: s["created"])
    p = parent_settings(u["parent_email"], u["id"])
    return {"suggestions": mine[-3:], "budget": budget_for(p, u["id"])}


@app.get("/api/parent/{email}")
def parent_get(email: str):
    p = parent_settings(email)
    pend = [suggestions[i] for i in p["pending"] if i in suggestions and suggestions[i]["status"] == "pending"]
    kids = [users[c] for c in p["children"] if c in users]
    child = kids[-1] if kids else None
    notes = sorted(notifications.get(email, []), key=lambda n: -n["at"])
    return {"settings": {k: v for k, v in p.items() if k not in ("pending", "used")}, "pending": pend, "notifications": notes,
            "unread": sum(1 for n in notes if not n["read"]),
            "children": [public_user(k) | {"budget": budget_for(p, k["id"]), "chosen": k.get("chosen", [])[-5:]} for k in kids],
            "child": public_user(child) if child else None,
            "categories": sorted({a["category"] for a in ACTIVITIES}), "topics": PROFILES["topics"],
            "activities": [{"id": a["id"], "title": a["title"], "topic": a["topic"], "category": a["category"]} for a in ACTIVITIES if a["min_age"] <= 12]}


class ParentSettings(BaseModel):
    allowed_categories: Optional[list[str]] = None
    require_approval: Optional[bool] = None
    allowed_topics: Optional[list[str]] = None
    daily_budget_min: Optional[int] = None
    adult_required_only: Optional[bool] = None
    reset_used_for: Optional[str] = None


@app.post("/api/parent/{email}/notifications/read")
def notifications_read(email: str):
    for n in notifications.get(email, []):
        n["read"] = True
    return {"ok": True}


@app.put("/api/parent/{email}/settings")
def parent_put(email: str, body: ParentSettings):
    p = parent_settings(email)
    for k, v in body.model_dump(exclude_none=True).items():
        if k == "reset_used_for":
            p["used"][v] = 0
        else:
            p[k] = v
    llm_cache.clear()
    return {k: v for k, v in p.items() if k not in ("pending", "used")}


class Approve(BaseModel):
    parent_email: str
    suggestion_id: str
    decision: str  # approved | rejected


@app.post("/api/approve")
def approve(body: Approve):
    s = suggestions.get(body.suggestion_id)
    if not s:
        raise HTTPException(404, "unknown suggestion")
    p = parent_settings(body.parent_email)
    s["status"] = "approved" if body.decision == "approved" else "rejected"
    if s["status"] == "approved":
        p["used"][s["user_id"]] = min(p["daily_budget_min"], p["used"].get(s["user_id"], 0) + s["duration_min"])
        # the other two from the same batch are resolved implicitly
        for other in suggestions.values():
            if other["user_id"] == s["user_id"] and other["status"] == "pending" and other["id"] != s["id"]:
                other["status"] = "rejected"
    p["pending"] = [i for i in p["pending"] if suggestions.get(i, {}).get("status") == "pending"]
    return s


class Feedback(BaseModel):
    user_id: str
    suggestion_id: str
    vote: str  # up | down


@app.post("/api/feedback")
def feedback(body: Feedback):
    u = get_user(body.user_id)
    require(u, "feedback")
    s = suggestions.get(body.suggestion_id)
    if not s:
        raise HTTPException(404, "unknown suggestion")
    tags = s.get("tags") or []
    cat = s.get("category") or "web"
    delta = 1 if body.vote == "up" else -1
    for t in tags + [cat]:
        u["feedback"][t] = u["feedback"].get(t, 0) + delta
    s["vote"] = body.vote
    return {"feedback": u["feedback"]}


class TeenOnboard(BaseModel):
    user_id: str
    answers: dict


@app.post("/api/onboard/teen")
def onboard_teen(body: TeenOnboard):
    u = get_user(body.user_id)
    require(u, "onboard_teen")
    u["prefs"] = body.answers
    u["quiz_done"] = True
    llm_cache.clear()
    return {"prefs": u["prefs"]}


class AdultContext(BaseModel):
    user_id: str
    about_me: Optional[str] = None
    notes_text: Optional[str] = None
    ics_text: Optional[str] = None


@app.post("/api/context/adult")
def context_adult(body: AdultContext):
    u = get_user(body.user_id)
    require(u, "context_adult")
    if body.about_me is not None:
        u["about_me"] = body.about_me
    if body.notes_text is not None:
        u["notes"] = body.notes_text
    if body.ics_text:
        from icalendar import Calendar
        cal = Calendar.from_ical(body.ics_text)
        today = dt.date.today()
        evs = []
        for comp in cal.walk("VEVENT"):
            s, e = comp.get("dtstart").dt, comp.get("dtend").dt
            if isinstance(s, dt.datetime) and s.date() == today:
                evs.append({"title": str(comp.get("summary", "Busy")), "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")})
        u["calendar"] = evs or None
    llm_cache.clear()
    return {"about_me": u["about_me"], "notes": u["notes"], "calendar": u.get("calendar") or CALENDARS["adult"]}


# ---- voice (behind k-ID 'ai-voice-mode') -----------------------------------
AUDIO_EXT = {"audio/webm": "webm", "video/webm": "webm", "audio/mp4": "mp4", "audio/mpeg": "mp3",
             "audio/wav": "wav", "audio/x-wav": "wav", "audio/ogg": "ogg", "audio/aac": "aac", "audio/flac": "flac"}
TTS_VOICE = {"child": "Ashley", "teen": "Alex", "adult": "Dennis"}


@app.post("/api/transcribe")
async def transcribe(user_id: str, audio: UploadFile = File(...)):
    """Speech-to-text via Modulate Velma-2 batch STT."""
    u = get_user(user_id)
    require(u, "transcribe")
    key = os.getenv("MODULATE_KEY")
    if not key:
        raise HTTPException(501, "Modulate not configured (MODULATE_KEY)")
    raw = await audio.read()
    ctype = (audio.content_type or "audio/webm").split(";")[0]
    ext = AUDIO_EXT.get(ctype, "webm")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://platform.modulate.ai/api/velma-2-stt-batch",
                         headers={"X-API-Key": key},
                         files={"upload_file": (f"clip.{ext}", raw, ctype)})
    if r.status_code >= 400:
        raise HTTPException(502, f"Modulate {r.status_code}: {r.text[:200]}")
    j = r.json()
    return {"text": j.get("text", ""), "duration_ms": j.get("duration_ms"),
            "language": (j.get("utterances") or [{}])[0].get("language")}


class SpeakReq(BaseModel):
    user_id: str
    text: str


@app.post("/api/speak")
async def speak(body: SpeakReq):
    """Text-to-speech via Inworld TTS-2. Voice and pace follow the tier."""
    u = get_user(body.user_id)
    require(u, "speak")
    key = os.getenv("INWORLD_KEY")
    if not key:
        raise HTTPException(501, "Inworld not configured (INWORLD_KEY)")
    payload = {
        "text": body.text[:1900], "voiceId": TTS_VOICE[u["tier"]], "modelId": "inworld-tts-2",
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": 0.9 if u["tier"] == "child" else 1.0},
        "applyTextNormalization": "ON",
    }
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.inworld.ai/tts/v1/voice",
                         headers={"Authorization": f"Basic {key}", "Content-Type": "application/json"},
                         json=payload)
    if r.status_code >= 400:
        raise HTTPException(502, f"Inworld {r.status_code}: {r.text[:200]}")
    return Response(content=base64.b64decode(r.json()["audioContent"]), media_type="audio/mpeg")


@app.post("/api/dev/reset")
def dev_reset():
    users.clear(); parents.clear(); suggestions.clear(); llm_cache.clear()
    mock_challenges.clear(); mock_sessions.clear(); known_accounts.clear(); notifications.clear()
    return {"ok": True}
