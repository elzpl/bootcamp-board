# Bootcamp Progress Board

## Setup

### 1. Create a Discord bot
1. Go to https://discord.com/developers/applications → New Application
2. Bot tab → Add Bot → copy the token
3. Under "Privileged Gateway Intents" enable: **Message Content Intent** + **Server Members Intent**
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Read Messages/View Channels`
5. Visit the generated URL to invite the bot to your server

### 2. Configure
```bash
cd bootcamp-board
cp .env.example .env
# Edit .env with your token, server ID, channels, and demo day
```

To get your server ID: right-click your server name in Discord → Copy Server ID (enable Developer Mode in Discord settings first).

### 3. Install and run
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Board is live at http://localhost:8000

## How it works

Every message posted in a watched channel = one commit square on the grid.

| Channel | Tag |
|---|---|
| `#standup` | `#standup` |
| `#shipped` | `#shipped` |
| `#blockers` | `#blocker` |

Inline hashtags (`#shipped`, `#standup`, `#blocker`) also work in any channel.

## Slash commands (in Discord)
- `/setproject My App Name` — sets the project name shown on the board
- `/board` — returns the board URL

## Tiers
- **Builders**: 10+ total commits
- **Finding Their Footing**: fewer than 10

Change the threshold via `BUILDER_THRESHOLD=10` in `.env`.
