import aiosqlite
import os
from datetime import datetime, date, timedelta

DB_PATH = os.getenv("DB_PATH", "bootcamp.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                project_name TEXT DEFAULT 'TBD',
                avatar_url TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL REFERENCES members(id),
                tag TEXT NOT NULL CHECK(tag IN ('shipped', 'standup', 'blocker')),
                message_text TEXT,
                message_url TEXT,
                posted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_events_member ON events(member_id);
            CREATE INDEX IF NOT EXISTS idx_events_posted ON events(posted_at);
        """)
        await db.commit()


async def upsert_member(discord_id: str, display_name: str, avatar_url: str | None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO members (discord_id, display_name, avatar_url)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET
                display_name = excluded.display_name,
                avatar_url = excluded.avatar_url
        """, (discord_id, display_name, avatar_url))
        await db.commit()
        async with db.execute("SELECT id FROM members WHERE discord_id = ?", (discord_id,)) as cur:
            row = await cur.fetchone()
            return row[0]


async def set_project(discord_id: str, project_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE members SET project_name = ? WHERE discord_id = ?",
            (project_name, discord_id)
        )
        await db.commit()


async def record_event(member_id: int, tag: str, message_text: str, message_url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO events (member_id, tag, message_text, message_url)
            VALUES (?, ?, ?, ?)
        """, (member_id, tag, message_text[:500], message_url))
        await db.commit()


async def get_all_members(grid_days: int = 14):
    today = date.today()
    start = today - timedelta(days=grid_days - 1)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM members ORDER BY display_name") as cur:
            members = [dict(r) for r in await cur.fetchall()]

        for m in members:
            mid = m["id"]

            # tag counts
            async with db.execute("""
                SELECT tag, COUNT(*) as cnt FROM events
                WHERE member_id = ? GROUP BY tag
            """, (mid,)) as cur:
                m["tags"] = {r["tag"]: r["cnt"] for r in await cur.fetchall()}

            # total commits
            m["total_commits"] = sum(m["tags"].values())

            # daily activity for heatmap
            async with db.execute("""
                SELECT DATE(posted_at) as day, COUNT(*) as cnt
                FROM events WHERE member_id = ?
                AND DATE(posted_at) >= ?
                GROUP BY day
            """, (mid, start.isoformat())) as cur:
                daily = {r["day"]: r["cnt"] for r in await cur.fetchall()}

            grid = []
            for i in range(grid_days):
                d = (start + timedelta(days=i)).isoformat()
                grid.append({"date": d, "count": daily.get(d, 0)})
            m["grid"] = grid

            # streak: consecutive days with at least one event up to today
            streak = 0
            for i in range(grid_days):
                d = (today - timedelta(days=i)).isoformat()
                if daily.get(d, 0) > 0:
                    streak += 1
                else:
                    break
            m["streak"] = streak

        return members


async def get_global_stats(demo_day: date, grid_days: int = 14):
    today = date.today()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM events") as cur:
            total_commits = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM events WHERE tag = 'shipped'") as cur:
            total_shipped = (await cur.fetchone())[0]
        async with db.execute("""
            SELECT COUNT(DISTINCT member_id) FROM events
            WHERE DATE(posted_at) = DATE('now')
        """) as cur:
            on_streaks = (await cur.fetchone())[0]

    days_to_demo = max(0, (demo_day - today).days)
    return {
        "total_commits": total_commits,
        "total_shipped": total_shipped,
        "days_to_demo": days_to_demo,
        "on_streaks": on_streaks,
    }
