"""
Runs on bot startup — fetches all threads from the goals forum and imports
historical messages into the DB. Skips members already in the DB so it's
safe to call on every restart (only back-fills what's missing).
"""
import discord
import asyncio
from database import upsert_member, record_event, set_project, init_db
import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "bootcamp.db")
GOALS_CHANNEL_NAME = "goals"


async def member_exists(discord_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE member_id = (SELECT id FROM members WHERE discord_id = ?)",
            (discord_id,)
        ) as cur:
            count = (await cur.fetchone())[0]
    return count > 0


async def import_goals_forum(bot: discord.Client):
    await bot.wait_until_ready()
    guild = bot.guilds[0] if bot.guilds else None
    if not guild:
        print("[importer] No guild found, skipping import")
        return

    # Find the goals forum channel
    goals_channel = discord.utils.get(guild.channels, name=GOALS_CHANNEL_NAME)
    if not goals_channel:
        print("[importer] Could not find #goals channel")
        return

    if not isinstance(goals_channel, discord.ForumChannel):
        print(f"[importer] #goals is not a forum channel (type={type(goals_channel)})")
        return

    # Get all active threads
    threads = goals_channel.threads
    # Also fetch archived threads
    try:
        async for thread in goals_channel.archived_threads(limit=100):
            threads = list(threads) + [thread]
    except Exception:
        pass

    print(f"[importer] Found {len(threads)} threads in #goals")

    imported = 0
    for thread in threads:
        owner_id = str(thread.owner_id)

        # Fetch all messages in this thread
        try:
            messages = [m async for m in thread.history(limit=100, oldest_first=True)]
        except discord.Forbidden:
            try:
                await thread.join()
                messages = [m async for m in thread.history(limit=100, oldest_first=True)]
            except Exception as e:
                print(f"[importer] Could not read {thread.name}: {e}")
                continue
        except Exception as e:
            print(f"[importer] Error reading {thread.name}: {e}")
            continue

        if not messages:
            continue

        # Upsert member from thread owner info
        owner = thread.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(thread.owner_id)
            except Exception:
                pass

        display_name = owner.display_name if owner else str(thread.owner_id)
        avatar_url = str(owner.display_avatar.url) if owner and owner.display_avatar else None

        member_id = await upsert_member(
            discord_id=owner_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        await set_project(owner_id, thread.name)

        # Import only messages from the thread owner, with real timestamps
        async with aiosqlite.connect(DB_PATH) as db:
            # Clear existing events for this member so we don't double-count on restart
            await db.execute("DELETE FROM events WHERE member_id = ?", (member_id,))
            await db.commit()

            count = 0
            for m in messages:
                if str(m.author.id) != owner_id:
                    continue
                await db.execute("""
                    INSERT INTO events (member_id, tag, message_text, message_url, posted_at)
                    VALUES (?, 'standup', ?, ?, ?)
                """, (
                    member_id,
                    m.content[:500],
                    m.jump_url,
                    m.created_at.isoformat(),
                ))
                count += 1

            await db.commit()

        print(f"[importer] {display_name} / {thread.name}: {count} posts")
        imported += count

    print(f"[importer] Done — {imported} total posts imported across {len(threads)} threads")
