from dotenv import load_dotenv
load_dotenv()  # must run before any module that reads env vars at import time

import asyncio
import os
import uvicorn
from database import init_db
from bot import BootcampBot, register_commands
from importer import import_goals_forum
from api import app


async def run_bot(bot: BootcampBot):
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("WARNING: DISCORD_TOKEN not set — bot disabled")
        return
    async with bot:
        asyncio.ensure_future(import_goals_forum(bot))
        await bot.start(token)


async def run_api():
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    await init_db()

    bot = BootcampBot()
    register_commands(bot)

    await asyncio.gather(
        run_bot(bot),
        run_api(),
    )


if __name__ == "__main__":
    asyncio.run(main())
