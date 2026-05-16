import os
from datetime import date
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from database import get_all_members, get_global_stats
from importer import run_import

DEMO_DAY = date.fromisoformat(os.getenv("DEMO_DAY", "2026-05-23"))
GRID_DAYS = int(os.getenv("GRID_DAYS", "13"))
BUILDER_THRESHOLD = int(os.getenv("BUILDER_THRESHOLD", "10"))

_raw_sessions = os.getenv("SESSION_DATES", "")
SESSION_DATES = [date.fromisoformat(s.strip()) for s in _raw_sessions.split(",") if s.strip()]

app = FastAPI()


@app.get("/api/stats")
async def stats():
    today = date.today()
    base = await get_global_stats(DEMO_DAY, GRID_DAYS)

    # Next upcoming session
    upcoming = [s for s in SESSION_DATES if s >= today]
    next_session = upcoming[0] if upcoming else None
    base["next_session"] = next_session.isoformat() if next_session else None
    base["days_to_next_session"] = (next_session - today).days if next_session else None
    base["session_dates"] = [s.isoformat() for s in SESSION_DATES]

    return base


@app.get("/api/members")
async def members():
    all_members = await get_all_members(GRID_DAYS)
    builders = sorted(
        [m for m in all_members if m["total_commits"] >= BUILDER_THRESHOLD],
        key=lambda m: m["total_commits"], reverse=True
    )
    finding = sorted(
        [m for m in all_members if m["total_commits"] < BUILDER_THRESHOLD],
        key=lambda m: m["total_commits"], reverse=True
    )
    return {"builders": builders, "finding_footing": finding}


@app.post("/api/import")
async def trigger_import():
    result = await run_import()
    return result


app.mount("/", StaticFiles(directory="web", html=True), name="static")
