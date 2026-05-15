import os
import discord
from discord import app_commands
from database import upsert_member, record_event, set_project

# channel_name -> tag, or "detect" for inline hashtag detection
def parse_watched_channels() -> dict[str, str]:
    raw = os.getenv("WATCHED_CHANNELS", "goals:standup,general:detect")
    result = {}
    for pair in raw.split(","):
        parts = pair.strip().split(":")
        if len(parts) == 2:
            result[parts[0].strip().lower()] = parts[1].strip().lower()
    return result


def detect_inline_tag(content: str) -> str | None:
    c = content.lower()
    if "#shipped" in c:
        return "shipped"
    if "#standup" in c:
        return "standup"
    if "#blocker" in c or "#blockers" in c:
        return "blocker"
    return None


class BootcampBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.watched: dict[str, str] = parse_watched_channels()
        self.guild_id: int | None = None

    async def setup_hook(self):
        # Sync slash commands once we know the guild
        pass

    async def on_ready(self):
        print(f"Bot online: {self.user}")
        if self.guilds:
            guild = self.guilds[0]
            self.guild_id = guild.id
            print(f"Server: {guild.name} (ID: {guild.id})")
            # Sync slash commands to this guild for instant availability
            guild_obj = discord.Object(id=guild.id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
            print("Slash commands synced")
        print(f"Watching channels: {list(self.watched.keys())}")

    async def _resolve_channel_name(self, message: discord.Message) -> str | None:
        """Return the relevant channel name for a message (handles threads/forums)."""
        channel = message.channel

        # Thread inside a forum or text channel
        if isinstance(channel, discord.Thread):
            parent = channel.parent
            if parent:
                return parent.name.lower()
            return None

        # Regular text channel
        if hasattr(channel, "name"):
            return channel.name.lower()

        return None

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        channel_name = await self._resolve_channel_name(message)
        if channel_name is None:
            return

        mapped_tag = self.watched.get(channel_name)
        if mapped_tag is None:
            return  # not a watched channel

        if mapped_tag == "detect":
            tag = detect_inline_tag(message.content)
            if tag is None:
                return  # general chat with no hashtag — ignore
        else:
            # Watched channel with a fixed tag — but still let inline override
            inline = detect_inline_tag(message.content)
            tag = inline if inline else mapped_tag

        avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else None
        member_id = await upsert_member(
            discord_id=str(message.author.id),
            display_name=message.author.display_name,
            avatar_url=avatar_url,
        )

        await record_event(member_id, tag, message.content, message.jump_url)
        print(f"[{tag}] {message.author.display_name} in #{channel_name}")

    async def on_thread_create(self, thread: discord.Thread):
        """Catch new forum posts — the starter message also fires on_message, but
        this ensures we don't miss posts where the message event races."""
        pass  # handled by on_message


def register_commands(bot: BootcampBot):
    @bot.tree.command(name="setproject", description="Set your project name on the progress board")
    @app_commands.describe(name="Your project name")
    async def setproject(interaction: discord.Interaction, name: str):
        await set_project(str(interaction.user.id), name)
        await interaction.response.send_message(
            f"Project set to **{name}** — visible on the board in moments.", ephemeral=True
        )

    @bot.tree.command(name="board", description="Get a link to the progress board")
    async def board_link(interaction: discord.Interaction):
        port = os.getenv("PORT", "8000")
        await interaction.response.send_message(
            f"**Builder Board** → http://localhost:{port}", ephemeral=True
        )
