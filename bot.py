import os
import sys
import io
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.getenv("GUILD_ID", "")
ADMIN_ROLE_IDS = [
    int(r) for r in os.getenv("ADMIN_ROLE_IDS", "").split(",") if r.strip()
]

ROBLOX_USERS_API = "https://users.roblox.com/v1"
ROBLOX_BADGES_API = "https://badges.roblox.com/v1"
ROBLOX_INVENTORY_API = "https://inventory.roblox.com/v1"
ROBLOX_THUMBNAILS_API = "https://thumbnails.roblox.com/v1"
ROBLOX_FRIENDS_API = "https://friends.roblox.com/v1"

# GAR (Group Administration & Ranking) badge ID
GAR_BADGE_ID = 2124469324

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class RobloxBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Synced commands to guild %s", GUILD_ID)
        else:
            await self.tree.sync()
            logger.info("Synced commands globally")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        await super().close()


bot = RobloxBot()


# ---------------------------------------------------------------------------
# Roblox API helpers
# ---------------------------------------------------------------------------

async def resolve_roblox_user(username: str) -> dict | None:
    """Resolve a Roblox username to user data (id, name, displayName)."""
    assert bot.session is not None
    payload = {"usernames": [username], "excludeBannedUsers": False}
    async with bot.session.post(
        f"{ROBLOX_USERS_API}/usernames/users", json=payload
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        users = data.get("data", [])
        return users[0] if users else None


async def get_roblox_user_by_id(user_id: int) -> dict | None:
    """Get Roblox user info by ID."""
    assert bot.session is not None
    async with bot.session.get(f"{ROBLOX_USERS_API}/users/{user_id}") as resp:
        if resp.status != 200:
            return None
        return await resp.json()


async def get_user_badges(user_id: int, limit: int = 100) -> list[dict]:
    """Fetch badges for a Roblox user (paginated)."""
    assert bot.session is not None
    badges: list[dict] = []
    cursor = ""
    while True:
        url = f"{ROBLOX_BADGES_API}/users/{user_id}/badges?limit={limit}&sortOrder=Desc"
        if cursor:
            url += f"&cursor={cursor}"
        async with bot.session.get(url) as resp:
            if resp.status != 200:
                break
            data = await resp.json()
            badges.extend(data.get("data", []))
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
    return badges


async def get_avatar_thumbnail(user_id: int, size: str = "420x420") -> str | None:
    """Get the avatar thumbnail URL for a Roblox user."""
    assert bot.session is not None
    url = (
        f"{ROBLOX_THUMBNAILS_API}/users/avatar"
        f"?userIds={user_id}&size={size}&format=Png&isCircular=false"
    )
    async with bot.session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        entries = data.get("data", [])
        if entries and entries[0].get("state") == "Completed":
            return entries[0].get("imageUrl")
    return None


async def get_friend_count(user_id: int) -> int | None:
    """Get friend count for a Roblox user."""
    assert bot.session is not None
    url = f"{ROBLOX_FRIENDS_API}/users/{user_id}/friends/count"
    async with bot.session.get(url) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("count")


async def check_badge_ownership(user_id: int, badge_id: int) -> bool:
    """Check if a user owns a specific badge."""
    assert bot.session is not None
    url = f"{ROBLOX_INVENTORY_API}/users/{user_id}/badges/{badge_id}"
    async with bot.session.get(url) as resp:
        return resp.status == 200


# ---------------------------------------------------------------------------
# /badge-graph
# ---------------------------------------------------------------------------

@bot.tree.command(name="badge-graph", description="Draw a badge graph for the specified user")
@app_commands.describe(user="Roblox username to look up")
async def badge_graph(interaction: discord.Interaction, user: str) -> None:
    await interaction.response.defer()

    roblox_user = await resolve_roblox_user(user)
    if not roblox_user:
        await interaction.followup.send(
            embed=discord.Embed(
                title="User Not Found",
                description=f"Could not find Roblox user **{user}**.",
                color=discord.Color.red(),
            )
        )
        return

    user_id = roblox_user["id"]
    display_name = roblox_user.get("displayName", roblox_user["name"])
    badges = await get_user_badges(user_id)

    if not badges:
        await interaction.followup.send(
            embed=discord.Embed(
                title="No Badges",
                description=f"**{display_name}** has no badges.",
                color=discord.Color.orange(),
            )
        )
        return

    # Group badges by month awarded
    month_counts: dict[str, int] = {}
    for badge in badges:
        awarded = badge.get("created", badge.get("updated", ""))
        if awarded:
            try:
                dt = datetime.fromisoformat(awarded.replace("Z", "+00:00"))
                key = dt.strftime("%Y-%m")
                month_counts[key] = month_counts.get(key, 0) + 1
            except ValueError:
                pass

    if not month_counts:
        # Fallback: show total badge count
        month_counts = {"Total": len(badges)}

    sorted_months = sorted(month_counts.keys())
    labels = sorted_months
    values = [month_counts[m] for m in sorted_months]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(labels, values, color="#5865F2")
    ax.set_xlabel("Month")
    ax.set_ylabel("Badges Earned")
    ax.set_title(f"Badge Graph for {display_name} ({len(badges)} total badges)")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    buf.seek(0)
    plt.close(fig)

    file = discord.File(buf, filename="badge_graph.png")
    embed = discord.Embed(
        title=f"Badge Graph — {display_name}",
        description=f"Total badges: **{len(badges)}**",
        color=discord.Color.blurple(),
    )
    embed.set_image(url="attachment://badge_graph.png")
    embed.set_footer(text=f"Roblox ID: {user_id}")
    await interaction.followup.send(embed=embed, file=file)


# ---------------------------------------------------------------------------
# /check-gar-badge
# ---------------------------------------------------------------------------

@bot.tree.command(name="check-gar-badge", description="Locate the GAR badge in a user's inventory")
@app_commands.describe(user="Roblox username to check")
async def check_gar_badge(interaction: discord.Interaction, user: str) -> None:
    await interaction.response.defer()

    roblox_user = await resolve_roblox_user(user)
    if not roblox_user:
        await interaction.followup.send(
            embed=discord.Embed(
                title="User Not Found",
                description=f"Could not find Roblox user **{user}**.",
                color=discord.Color.red(),
            )
        )
        return

    user_id = roblox_user["id"]
    display_name = roblox_user.get("displayName", roblox_user["name"])

    # Check via badge list
    badges = await get_user_badges(user_id)
    has_gar = any(b.get("id") == GAR_BADGE_ID for b in badges)

    if has_gar:
        embed = discord.Embed(
            title="GAR Badge Found",
            description=f"**{display_name}** has the GAR badge!",
            color=discord.Color.green(),
        )
    else:
        embed = discord.Embed(
            title="GAR Badge Not Found",
            description=f"**{display_name}** does **not** have the GAR badge.",
            color=discord.Color.red(),
        )

    embed.set_footer(text=f"Roblox ID: {user_id}")
    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /profile-check
# ---------------------------------------------------------------------------

@bot.tree.command(name="profile-check", description="Gives information on a user's profile")
@app_commands.describe(user="Roblox username to look up")
async def profile_check(interaction: discord.Interaction, user: str) -> None:
    await interaction.response.defer()

    roblox_user = await resolve_roblox_user(user)
    if not roblox_user:
        await interaction.followup.send(
            embed=discord.Embed(
                title="User Not Found",
                description=f"Could not find Roblox user **{user}**.",
                color=discord.Color.red(),
            )
        )
        return

    user_id = roblox_user["id"]
    full_user = await get_roblox_user_by_id(user_id)
    if not full_user:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Error",
                description="Failed to fetch user details.",
                color=discord.Color.red(),
            )
        )
        return

    display_name = full_user.get("displayName", full_user.get("name", "N/A"))
    username = full_user.get("name", "N/A")
    description = full_user.get("description", "") or "*No description*"
    created = full_user.get("created", "Unknown")
    is_banned = full_user.get("isBanned", False)

    if created and created != "Unknown":
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            created = dt.strftime("%B %d, %Y")
        except ValueError:
            pass

    # Fetch extra info in parallel
    avatar_url = await get_avatar_thumbnail(user_id)
    friend_count = await get_friend_count(user_id)
    badges = await get_user_badges(user_id)

    embed = discord.Embed(
        title=f"Profile — {display_name}",
        url=f"https://www.roblox.com/users/{user_id}/profile",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Username", value=username, inline=True)
    embed.add_field(name="Display Name", value=display_name, inline=True)
    embed.add_field(name="User ID", value=str(user_id), inline=True)
    embed.add_field(name="Account Created", value=created, inline=True)
    embed.add_field(name="Friends", value=str(friend_count) if friend_count is not None else "N/A", inline=True)
    embed.add_field(name="Badges", value=str(len(badges)), inline=True)
    embed.add_field(name="Banned", value="Yes" if is_banned else "No", inline=True)

    if description and len(description) > 1024:
        description = description[:1021] + "..."
    embed.add_field(name="Description", value=description, inline=False)

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.set_footer(text=f"Roblox ID: {user_id}")
    await interaction.followup.send(embed=embed)


# ---------------------------------------------------------------------------
# /purge-role
# ---------------------------------------------------------------------------

@bot.tree.command(name="purge-role", description="Purge a specific role from all members")
@app_commands.describe(role="The role to remove from all members")
@app_commands.checks.has_permissions(manage_roles=True)
async def purge_role(interaction: discord.Interaction, role: discord.Role) -> None:
    await interaction.response.defer(ephemeral=True)

    if interaction.guild is None:
        await interaction.followup.send("This command can only be used in a server.")
        return

    bot_member = interaction.guild.me
    if bot_member.top_role <= role:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Permission Error",
                description="I cannot manage a role that is equal to or higher than my top role.",
                color=discord.Color.red(),
            )
        )
        return

    members_with_role = [m for m in interaction.guild.members if role in m.roles]
    if not members_with_role:
        await interaction.followup.send(
            embed=discord.Embed(
                title="No Members",
                description=f"No members currently have the **{role.name}** role.",
                color=discord.Color.orange(),
            )
        )
        return

    removed = 0
    failed = 0
    for member in members_with_role:
        try:
            await member.remove_roles(role, reason=f"Role purge by {interaction.user}")
            removed += 1
        except discord.Forbidden:
            failed += 1
        except discord.HTTPException:
            failed += 1

    embed = discord.Embed(
        title="Role Purge Complete",
        description=f"Role **{role.name}** has been purged.",
        color=discord.Color.green(),
    )
    embed.add_field(name="Removed From", value=str(removed), inline=True)
    embed.add_field(name="Failed", value=str(failed), inline=True)
    await interaction.followup.send(embed=embed)


@purge_role.error
async def purge_role_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Permission Denied",
                description="You need the **Manage Roles** permission to use this command.",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# /restart
# ---------------------------------------------------------------------------

def is_admin():
    """Check decorator: user must have Administrator permission or an admin role."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:  # type: ignore[union-attr]
            return True
        if ADMIN_ROLE_IDS:
            member_role_ids = {r.id for r in interaction.user.roles}  # type: ignore[union-attr]
            if member_role_ids & set(ADMIN_ROLE_IDS):
                return True
        return False
    return app_commands.check(predicate)


@bot.tree.command(name="restart", description="Restart the bot (restricted)")
@is_admin()
async def restart(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        embed=discord.Embed(
            title="Restarting...",
            description="The bot is restarting. Please wait a moment.",
            color=discord.Color.orange(),
        )
    )
    logger.info("Restart requested by %s", interaction.user)
    await bot.close()
    # The process manager (e.g. systemd, pm2) should restart the process.
    os.execv(sys.executable, [sys.executable] + sys.argv)


@restart.error
async def restart_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Access Denied",
                description="You do not have permission to restart the bot.",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# /send
# ---------------------------------------------------------------------------

@bot.tree.command(name="send", description="Send a formatted embed message")
@app_commands.describe(
    channel="Channel to send the message to",
    title="Embed title",
    description="Embed description (supports Discord markdown)",
    color="Embed color hex code (e.g. #5865F2)",
    image_url="Optional image URL to include",
)
@app_commands.checks.has_permissions(manage_messages=True)
async def send_message(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    description: str,
    color: str = "#5865F2",
    image_url: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)

    try:
        color_value = int(color.strip("#"), 16)
    except ValueError:
        color_value = 0x5865F2

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color(color_value),
        timestamp=datetime.now(timezone.utc),
    )

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"Sent by {interaction.user.display_name}")

    try:
        await channel.send(embed=embed)
        await interaction.followup.send(
            embed=discord.Embed(
                title="Message Sent",
                description=f"Your message has been sent to {channel.mention}.",
                color=discord.Color.green(),
            )
        )
    except discord.Forbidden:
        await interaction.followup.send(
            embed=discord.Embed(
                title="Permission Error",
                description=f"I don't have permission to send messages in {channel.mention}.",
                color=discord.Color.red(),
            )
        )


@send_message.error
async def send_message_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Permission Denied",
                description="You need the **Manage Messages** permission to use this command.",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN is not set. Create a .env file — see .env.example.")
        sys.exit(1)
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
