"""
Imports historical posts from the goals forum into the DB.
Runs on startup and can be triggered via POST /api/import.
"""
import urllib.request
import json
import asyncio
import aiosqlite
import os
import time

GOALS_CHANNEL_ID = "1503516188855107634"
GUILD_ID = "1503515961418842192"
DB_PATH = os.getenv("DB_PATH", "bootcamp.db")


def _headers():
    token = os.getenv("DISCORD_TOKEN", "")
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "DiscordBot (https://github.com/bootcamp-board, 1.0)",
    }


def _http_get(url: str):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _join_thread(thread_id: str):
    url = f"https://discord.com/api/v10/channels/{thread_id}/thread-members/@me"
    req = urllib.request.Request(url, headers=_headers(), method="PUT")
    req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def _fetch_all_data() -> dict:
    """All blocking HTTP work in one function — runs in a thread."""
    # Active threads in goals forum
    data = _http_get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/threads/active")
    threads = [t for t in data.get("threads", []) if t.get("parent_id") == GOALS_CHANNEL_ID]

    # Guild members for display names + avatars
    guild_members = _http_get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/members?limit=100")
    member_map = {}
    for m in guild_members:
        uid = m["user"]["id"]
        name = m.get("nick") or m["user"].get("global_name") or m["user"]["username"]
        avatar = m.get("avatar") or m["user"].get("avatar")
        if avatar:
            if m.get("avatar"):
                avatar_url = f"https://cdn.discordapp.com/guilds/{GUILD_ID}/users/{uid}/avatars/{avatar}.png"
            else:
                avatar_url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png"
        else:
            avatar_url = None
        member_map[uid] = (name, avatar_url)

    # Messages from each thread
    results = []
    for thread in threads:
        thread_id = thread["id"]
        owner_id = str(thread["owner_id"])

        _join_thread(thread_id)
        time.sleep(0.4)

        try:
            messages = _http_get(f"https://discord.com/api/v10/channels/{thread_id}/messages?limit=50")
        except Exception as e:
            print(f"[importer] Could not read {thread['name']}: {e}")
            time.sleep(1)
            continue

        results.append({
            "thread_id": thread_id,
            "project": thread["name"],
            "owner_id": owner_id,
            "messages": [
                {"id": m["id"], "content": m["content"], "timestamp": m["timestamp"], "author_id": m["author"]["id"]}
                for m in messages
            ],
        })
        time.sleep(0.3)

    return {"threads": results, "members": member_map}


async def run_import() -> dict:
    print("[importer] Fetching data from Discord...")
    try:
        # Run all blocking HTTP in a thread so the event loop stays free
        data = await asyncio.to_thread(_fetch_all_data)
    except Exception as e:
        msg = f"Failed to fetch from Discord: {e}"
        print(f"[importer] {msg}")
        return {"ok": False, "error": msg}

    threads = data["threads"]
    member_map = data["members"]
    print(f"[importer] Got {len(threads)} threads, writing to DB...")

    imported_members = 0
    imported_events = 0

    async with aiosqlite.connect(DB_PATH) as db:
        for t in threads:
            owner_id = t["owner_id"]
            name, avatar_url = member_map.get(owner_id, (owner_id, None))

            await db.execute("""
                INSERT INTO members (discord_id, display_name, avatar_url, project_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    project_name=excluded.project_name
            """, (owner_id, name, avatar_url, t["project"]))
            await db.commit()

            async with db.execute("SELECT id FROM members WHERE discord_id=?", (owner_id,)) as cur:
                member_id = (await cur.fetchone())[0]

            await db.execute("DELETE FROM events WHERE member_id=?", (member_id,))

            count = 0
            for m in t["messages"]:
                if m["author_id"] != owner_id:
                    continue
                await db.execute("""
                    INSERT INTO events (member_id, tag, message_text, message_url, posted_at)
                    VALUES (?, 'standup', ?, ?, ?)
                """, (
                    member_id,
                    m["content"][:500],
                    f"https://discord.com/channels/{GUILD_ID}/{t['thread_id']}/{m['id']}",
                    m["timestamp"],
                ))
                count += 1

            await db.commit()
            print(f"[importer] {name} / {t['project']}: {count} posts")
            imported_members += 1
            imported_events += count

    print(f"[importer] Done — {imported_members} members, {imported_events} events")
    return {"ok": True, "members": imported_members, "events": imported_events}


async def import_goals_forum(bot=None):
    """Called on bot startup — waits a few seconds for bot to connect first."""
    await asyncio.sleep(5)
    await run_import()
