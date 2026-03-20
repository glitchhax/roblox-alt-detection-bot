# Roblox Discord Bot

A Discord bot that examines Roblox accounts for badges, profiles, and more.

## Commands

| Command | Description |
|---------|-------------|
| `/badge-graph <user>` | Draw a badge graph showing badges earned over time for a Roblox user |
| `/check-gar-badge <user>` | Check if a Roblox user has the GAR badge in their inventory |
| `/profile-check <user>` | Get detailed profile information for a Roblox user |
| `/purge-role <role>` | Remove a specific role from all members (requires Manage Roles) |
| `/restart` | Restart the bot (admin only) |
| `/send <channel> <title> <description>` | Send a formatted embed message to a channel (requires Manage Messages) |

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. Go to the **Bot** tab and click **Reset Token** to get your bot token
4. Enable these **Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
5. Go to **OAuth2 > URL Generator**, select `bot` and `applications.commands` scopes
6. Select these bot permissions:
   - Manage Roles
   - Send Messages
   - Embed Links
   - Attach Files
   - Manage Messages
7. Copy the generated URL and use it to invite the bot to your server

### 2. Install Dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your bot token:
```
DISCORD_BOT_TOKEN=your_token_here
```

Optional settings:
- `GUILD_ID` — Set this to your server's ID for instant slash command registration (otherwise commands take up to 1 hour to appear globally)
- `ADMIN_ROLE_IDS` — Comma-separated role IDs that can use `/restart`

### 4. Run the Bot

```bash
python3 bot.py
```

## Requirements

- Python 3.10+
- discord.py 2.3+
- aiohttp
- matplotlib
- Pillow
- python-dotenv
