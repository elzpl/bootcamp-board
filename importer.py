"""
Imports historical posts from the goals forum into the DB.
Uses direct HTTP with proper Discord bot headers (avoids Cloudflare blocks).
Safe to call repeatedly — clears and re-imports each member's events.
"""
import urllib.request
import json
import asyncio
import aiosqlite
import os
import time

TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("GUILD_ID", "1503515961418842192")
GOALS_CHANNEL_ID = "1503516188855107634"
DB_PATH = os.getenv("DB_PATH", "bootcamp.db")

HEADERS = {
    "Authorization": f"Bot {TOKEN}",
    "User-Agent": "DiscordBot (https://github.com/bootcamp-board, 1.0)",
    "Content-Type": "application/json",
}


def http_get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def join_thread(thread_id: str):
    url = f"https://discord.com/api/v10/channels/{thread_id}/thread-members/@me"
    req = urllib.request.Request(url, headers=HEADERS, method="PUT")
    req.add_header("Content-Length", "0")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


async def run_import() -> dict:
    TOKEN_NOW = os.getenv("DISCORD_TOKEN", "")
    HEADERS["Authorization"] = f"Bot {TOKEN_NOW}"

    print("[importer] Starting goals forum import...")

    # Fetch active threads in goals forum
    try:
        data = http_get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/threads/active")
        threads = [t for t in data.get("threads", []) if t.get("parent_id") == GOALS_CHANNEL_ID]
    except Exception as e:
        msg = f"Failed to fetch threads: {e}"
        print(f"[importer] {msg}")
        return {"ok": False, "error": msg}

    print(f"[importer] Found {len(threads)} threads")

    # Fetch guild members for display names + avatars
    try:
        guild_members = http_get(f"https://discord.com/api/v10/guilds/{GUILD_ID}/members?limit=100")
        member_map = {}
        for m in guild_members:
            uid = m["user"]["id"]
            name = m.get("nick") or m["user"].get("global_name") or m["user"]["username"]
            avatar = m.get("avatar") or m["user"].get("avatar")
            if avatar:
                if m.get("avatar"):
                    url = f"https://cdn.discordapp.com/guilds/{GUILD_ID}/users/{uid}/avatars/{avatar}.png"
                else:
                    url = f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.png"
            else:
                url = None
            member_map[uid] = (name, url)
    except Exception as e:
        print(f"[importer] Could not fetch guild members: {e}")
        member_map = {}

    imported_members = 0
    imported_events = 0

    async with aiosqlite.connect(DB_PATH) as db:
        for thread in threads:
            thread_id = thread["id"]
            owner_id = str(thread["owner_id"])
            project_name = thread["name"]

            # Join thread so bot can read it
            join_thread(thread_id)
            time.sleep(0.3)

            # Fetch messages
            try:
                messages = http_get(f"https://discord.com/api/v10/channels/{thread_id}/messages?limit=50")
            except Exception as e:
                print(f"[importer] Could not read {project_name}: {e}")
                time.sleep(1)
                continue

            # Upsert member
            name, avatar_url = member_map.get(owner_id, (owner_id, None))
            await db.execute("""
                INSERT INTO members (discord_id, display_name, avatar_url, project_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    project_name=excluded.project_name
            """, (owner_id, name, avatar_url, project_name))
            await db.commit()

            async with db.execute("SELECT id FROM members WHERE discord_id=?", (owner_id,)) as cur:
                member_id = (await cur.fetchone())[0]

            # Clear old events and re-import
            await db.execute("DELETE FROM events WHERE member_id=?", (member_id,))

            count = 0
            for m in messages:
                if m["author"]["id"] != owner_id:
                    continue
                await db.execute("""
                    INSERT INTO events (member_id, tag, message_text, message_url, posted_at)
                    VALUES (?, 'standup', ?, ?, ?)
                """, (
                    member_id,
                    m["content"][:500],
                    f"https://discord.com/channels/{GUILD_ID}/{thread_id}/{m['id']}",
                    m["timestamp"],
                ))
                count += 1

            await db.commit()
            print(f"[importer] {name} / {project_name}: {count} posts")
            imported_members += 1
            imported_events += count
            time.sleep(0.5)

    print(f"[importer] Done — {imported_members} members, {imported_events} events")
    return {"ok": True, "members": imported_members, "events": imported_events}


async def import_goals_forum(bot=None):
    """Called on bot startup."""
    # Small delay to let the bot fully connect first
    await asyncio.sleep(5)
    await run_import()
