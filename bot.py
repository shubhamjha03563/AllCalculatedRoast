"""
bot.py — Calculated Chaos Discord Bot

Commands:
  !roast          — Start session monitoring (polls EA every 5 min, auto-stops after 45 min idle)
  !report         — Manually fetch and post the latest match report
  !chaos          — Show bot status
  !spin           — Spin the Chaos Wheel
  !leaderboard    — Show Crown Leaderboard
  !powers         — Show active chaos powers
  !stats [n|all]  — Lifetime stats
  !lifetimestats  — Full lifetime leaderboard
  !setclub <name> — Switch active club
  !roast @mention — Roast a specific player with their real stats
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time

import discord
from discord.ext import commands, tasks

import config
from club_state import get_active_club
from achievements import evaluate_players
from match_fetcher import fetch_latest_match
from session_parser import parse_session_text, build_session_report
from roast_engine import (
    get_roast_victims, build_roast_embeds, get_fun_roast,
    is_boring_game, build_silent_treatment_embed,
)
from chaos_engine import (
    build_chaos_report,
    build_leaderboard_embed,
    build_spin_embed,
    build_status_embed,
    update_leaderboard,
)
from lifetime_stats import (
    record_match,
    build_lifetime_embed,
    build_top_stats_embed,
    build_all_players_embed,
    get_all_stats,
    get_player_stats,
    import_stats_from_file,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("calculated-chaos")

# ─────────────────────────────────────────────────────────────────────────────
# Bot setup
# ─────────────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents)

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────

_session_active:    bool       = False
_session_channel               = None       # channel to post into
_last_match_id:     str | None = None       # last match we reported
_last_activity_ts:  float      = 0.0        # last time a new match was found

_POLL_MINUTES    = 5
_TIMEOUT_MINUTES = 45

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_report_channel():
    """Always post chaos reports to the configured channel."""
    ch = bot.get_channel(int(config.ROAST_CHANNEL_ID))
    return ch or _session_channel


async def _send_pundit(embeds: list) -> None:
    """Send pundit verdict embeds to the roast channel."""
    if not embeds:
        return
    ch = _get_report_channel()
    if ch:
        for e in embeds:
            await ch.send(embed=e)


async def _run_match_report(match_data: dict) -> None:
    """Build and post the full chaos report + pundit verdicts for a match."""
    global _last_match_id

    ch = _get_report_channel()
    if not ch:
        logger.error("No report channel found")
        return

    players = match_data.get("players", [])
    if not players:
        await ch.send("⚠️ Match detected but no player data found.")
        return

    _last_match_id = match_data.get("match_id")

    results = evaluate_players(players)
    update_leaderboard(results)
    record_match(match_data, results)

    # ── Header ───────────────────────────────────────────────────────────────
    score    = match_data.get("score", "? - ?")
    opponent = match_data.get("opponent", "Unknown")
    result   = match_data.get("result", "?")
    date     = match_data.get("date", "")
    venue    = match_data.get("venue", "")
    our_club = match_data.get("our_club", get_active_club()[1]["name"])

    colour = {
        "Win":  discord.Colour.green(),
        "Draw": discord.Colour.gold(),
        "Loss": discord.Colour.red(),
    }.get(result, discord.Colour.blurple())

    result_emoji = {"Win": "[W]", "Loss": "[L]", "Draw": "[D]"}.get(result, "")
    desc_lines = [f"{result_emoji} **{score}** vs **{opponent}** — {result}"]
    if date:
        desc_lines.append(f"Date: {date}")
    if venue:
        desc_lines.append(f"Venue: {venue}")

    header = discord.Embed(
        title=f"Chaos Report — {our_club}",
        description="\n".join(desc_lines),
        colour=colour,
    )
    await ch.send(embed=header)

    # ── Achievements + chaos report ───────────────────────────────────────────
    embeds = build_chaos_report(match_data, results)
    for i in range(0, len(embeds), 10):
        await ch.send(embeds=embeds[i:i + 10])

    # ── Pundit verdicts ───────────────────────────────────────────────────────
    try:
        victims      = get_roast_victims(players)
        roast_embeds = build_roast_embeds(victims, match_data, all_players=players)

        if is_boring_game(players, results, match_data):
            silent = build_silent_treatment_embed(match_data)
            await _send_pundit([silent])

        await _send_pundit(roast_embeds)

    except Exception as exc:
        logger.warning("Pundit verdicts failed: %s", exc, exc_info=True)

    logger.info("Match report complete: %s %s vs %s", result, score, opponent)


# ─────────────────────────────────────────────────────────────────────────────
# Session polling loop
# ─────────────────────────────────────────────────────────────────────────────

@tasks.loop(minutes=_POLL_MINUTES)
async def _poll_ea() -> None:
    """Poll EA API every 5 minutes. Stop after 45 minutes of no new match."""
    global _session_active, _last_activity_ts

    if not _session_active:
        return

    # ── Check timeout ─────────────────────────────────────────────────────────
    idle_minutes = (time.monotonic() - _last_activity_ts) / 60
    if idle_minutes >= _TIMEOUT_MINUTES:
        logger.info("Session idle for %.0f min — shutting down", idle_minutes)
        await _stop_session(reason="timeout")
        return

    # ── Fetch from EA ─────────────────────────────────────────────────────────
    try:
        match_data = await asyncio.to_thread(fetch_latest_match)
    except Exception as exc:
        logger.warning("Poll: EA API error: %s", exc)
        return

    match_id = match_data.get("match_id")

    if match_id == _last_match_id:
        logger.info("Poll: no new match (still %s, idle %.0f min)", match_id, idle_minutes)
        return

    # ── New match found ───────────────────────────────────────────────────────
    logger.info("Poll: new match detected — %s", match_id)
    _last_activity_ts = time.monotonic()
    await _run_match_report(match_data)


@_poll_ea.before_loop
async def _before_poll():
    await bot.wait_until_ready()


async def _start_session(channel) -> None:
    global _session_active, _session_channel, _last_activity_ts, _last_match_id

    if _session_active:
        await channel.send(
            embed=discord.Embed(
                title="Already watching",
                description="Session is already active. I'm on it.",
                colour=discord.Colour.gold(),
            )
        )
        return

    # Grab current latest match ID so we don't report old matches
    try:
        current = await asyncio.to_thread(fetch_latest_match)
        _last_match_id = current.get("match_id")
        logger.info("Session started — baseline match_id: %s", _last_match_id)
    except Exception as exc:
        logger.warning("Couldn't fetch baseline match: %s", exc)
        _last_match_id = None

    _session_channel  = channel
    _last_activity_ts = time.monotonic()
    _session_active   = True

    if not _poll_ea.is_running():
        _poll_ea.start()

    report_ch = _get_report_channel()
    await (report_ch or channel).send(
        embed=discord.Embed(
            title="🎮 Session Started",
            description=(
                f"Watching for new matches. EA API polled every **{_POLL_MINUTES} min**.\n"
                f"Auto-stops after **{_TIMEOUT_MINUTES} min** of no new match.\n\n"
                f"Good luck out there."
            ),
            colour=discord.Colour.green(),
        )
    )


async def _stop_session(reason: str = "manual") -> None:
    global _session_active

    _session_active = False
    if _poll_ea.is_running():
        _poll_ea.stop()

    ch = _get_report_channel() or _session_channel
    if not ch:
        return

    if reason == "timeout":
        await ch.send(
            embed=discord.Embed(
                title="⏹️ Session Ended",
                description=(
                    f"No new match detected for **{_TIMEOUT_MINUTES} minutes**.\n"
                    f"Session closed automatically.\n\n"
                    f"Type `!roast` when you're playing again."
                ),
                colour=discord.Colour.orange(),
            )
        )
    else:
        await ch.send(
            embed=discord.Embed(
                title="⏹️ Session Stopped",
                description="Auto-reporting stopped manually.",
                colour=discord.Colour.blurple(),
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# Events
# ─────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    logger.info("Prefix: %s  |  Guilds: %d", config.BOT_PREFIX, len(bot.guilds))
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="your matches for chaos 👀",
        )
    )

    # Handle OurProClub session recap embeds if bot was offline
    await _check_missed_session_recap()


async def _check_missed_session_recap() -> None:
    """On startup scan for unprocessed OurProClub session recap embeds."""
    try:
        ch_id = config.OURPROCLUBS_WATCH_CHANNEL_ID
        if not ch_id:
            return
        channel = bot.get_channel(int(ch_id))
        if not channel:
            return

        recent = []
        async for msg in channel.history(limit=20):
            recent.append(msg)
        recent.reverse()

        triggers = ("Automatic Results: Session Recap", "Automatic Results was stopped")
        last_recap_msg = None
        for msg in recent:
            if str(msg.author.id) != config.OURPROCLUBS_BOT_ID:
                continue
            for emb in msg.embeds:
                text = (emb.title or "") + (emb.description or "")
                if any(t in text for t in triggers):
                    last_recap_msg = msg
                    break

        if not last_recap_msg:
            return

        # Check if we already replied
        already_processed = any(
            m.author == bot.user
            for m in recent[recent.index(last_recap_msg) + 1:]
        )
        if already_processed:
            return

        logger.info("Startup: found unprocessed session recap — processing")
        await _handle_session_recap(last_recap_msg, channel)

    except Exception as exc:
        logger.warning("Startup session check failed: %s", exc)


async def _handle_session_recap(message: discord.Message, channel) -> None:
    """Parse and post a session recap from an OurProClub embed."""
    import re as _re

    def _strip_md(t: str) -> str:
        t = _re.sub(r"\*\*(.*?)\*\*", r"\1", t)
        t = _re.sub(r"\*(.*?)\*",     r"\1", t)
        t = _re.sub(r"<@\d+>",        "",    t)
        t = _re.sub(r"^>\s*",         "",    t, flags=_re.MULTILINE)
        return t

    # Reconstruct text from embed fields
    for emb in message.embeds:
        combined = (emb.title or "") + "\n" + (emb.description or "")
        triggers = ("Automatic Results: Session Recap", "Automatic Results was stopped")
        if not any(t in combined for t in triggers):
            continue
        lines = [emb.title or "", _strip_md(emb.description or ""), ""]
        for field in emb.fields:
            lines.append(field.name)
            lines.append(_strip_md(field.value or ""))
            lines.append("")
        raw_text = "\n".join(lines)
        break
    else:
        return

    try:
        alias, cfg = get_active_club()
        session = parse_session_text(raw_text)
        logger.info("Session parsed: %dW %dD %dL %d players",
                    session['wins'], session['draws'], session['losses'], len(session['players']))

        all_embeds    = build_session_report(session, club_name=cfg["name"])
        report_embeds = [e for e in all_embeds if getattr(e, 'colour', None) != discord.Colour.orange()]
        pundit_embeds = [e for e in all_embeds if getattr(e, 'colour', None) == discord.Colour.orange()]

        for i in range(0, len(report_embeds), 10):
            await channel.send(embeds=report_embeds[i:i + 10])
        await _send_pundit(pundit_embeds)

    except Exception as exc:
        logger.error("Session recap failed: %s", exc, exc_info=True)
        await channel.send(
            embed=discord.Embed(
                title="⚠️ Session Report Failed",
                description=f"```{exc}```",
                colour=discord.Colour.orange(),
            )
        )


@bot.event
async def on_message(message: discord.Message) -> None:
    await bot.process_commands(message)

    if message.author == bot.user:
        return

    # Handle OurProClub session recap embeds live
    if str(message.author.id) != config.OURPROCLUBS_BOT_ID:
        return

    triggers = ("Automatic Results: Session Recap", "Automatic Results was stopped")
    for emb in message.embeds:
        text = (emb.title or "") + (emb.description or "")
        if any(t in text for t in triggers):
            await _handle_session_recap(message, message.channel)
            return


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(name="roast")
async def roast_cmd(ctx: commands.Context) -> None:
    """!roast — start session monitoring."""
    await _start_session(ctx.channel)


@bot.command(name="burn")
async def burn_cmd(ctx: commands.Context, member: discord.Member = None) -> None:
    """!burn @mention — roast a specific player with their lifetime stats."""
    if member is None:
        await ctx.send("Tag someone: `!burn @player`")
        return
    try:
        from roast_engine import DISCORD_TO_PLAYER
        in_game_name = DISCORD_TO_PLAYER.get(str(member.id))
        if not in_game_name:
            await ctx.send(f"No stats on file for {member.display_name}.")
            return
        stats = get_player_stats(in_game_name)
        if not stats or stats.get("matches", 0) < 3:
            await ctx.send(
                f"**{in_game_name}** has fewer than 3 matches — not enough to roast properly."
            )
            return
        roast_text = get_fun_roast(in_game_name, stats)
        embed = discord.Embed(
            title=f"🎤 {in_game_name}",
            description=roast_text,
            colour=discord.Colour.orange(),
        )
        embed.set_footer(text=f"Based on {stats['matches']} matches")
        await _send_pundit([embed])
    except Exception as exc:
        logger.exception("Burn command failed")
        await ctx.send(f"Couldn't roast {member.display_name}: `{exc}`")


@bot.command(name="stop")
async def stop_cmd(ctx: commands.Context) -> None:
    """!stop — manually stop the session."""
    if not _session_active:
        await ctx.send("No active session to stop.")
        return
    await _stop_session(reason="manual")


@bot.command(name="report")
async def report_cmd(ctx: commands.Context, match_type: str = "leagueMatch") -> None:
    """!report — manually fetch and post the latest match."""
    async with ctx.typing():
        try:
            match_data = await asyncio.to_thread(fetch_latest_match, match_type)
            await _run_match_report(match_data)
        except Exception as exc:
            logger.exception("Manual report failed")
            await ctx.send(
                embed=discord.Embed(
                    title="❌ Report Failed",
                    description=f"```{exc}```",
                    colour=discord.Colour.red(),
                )
            )


@bot.command(name="chaos")
async def chaos_cmd(ctx: commands.Context) -> None:
    """!chaos — show bot status."""
    alias, cfg = get_active_club()
    idle_min = int((time.monotonic() - _last_activity_ts) / 60) if _session_active else 0
    embed = build_status_embed(cfg["name"], alias)
    embed.add_field(
        name="Session",
        value=(
            f"🟢 Active — idle {idle_min}min / {_TIMEOUT_MINUTES}min"
            if _session_active else "⚫ Inactive — type `!roast` to start"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="spin")
async def spin_cmd(ctx: commands.Context) -> None:
    """!spin — spin the Chaos Wheel."""
    embed = build_spin_embed()
    await ctx.send(embed=embed)


@bot.command(name="leaderboard")
async def leaderboard_cmd(ctx: commands.Context) -> None:
    """!leaderboard — crown leaderboard."""
    embed = build_leaderboard_embed()
    await ctx.send(embed=embed)


@bot.command(name="powers")
async def powers_cmd(ctx: commands.Context) -> None:
    """!powers — show active chaos powers."""
    _, cfg = get_active_club()
    embed = discord.Embed(
        title="⚡ Active Chaos Powers",
        description="No powers currently active." ,
        colour=discord.Colour.purple(),
    )
    await ctx.send(embed=embed)


@bot.command(name="stats")
async def stats_cmd(ctx: commands.Context, arg: str = "1") -> None:
    """!stats [n|all] — lifetime stats."""
    async with ctx.typing():
        if arg.lower() == "all":
            embed = build_all_players_embed()
        else:
            try:
                n = int(arg)
            except ValueError:
                n = 1
            embed = build_top_stats_embed(top_n=n)
        await ctx.send(embed=embed)


@bot.command(name="lifetimestats")
async def lifetimestats_cmd(ctx: commands.Context) -> None:
    """!lifetimestats — full lifetime leaderboard."""
    async with ctx.typing():
        embed = build_lifetime_embed()
        await ctx.send(embed=embed)


@bot.command(name="setclub")
async def setclub_cmd(ctx: commands.Context, alias: str = "") -> None:
    """!setclub <alias> — switch active club."""
    from club_state import set_active_club
    if not alias:
        _, cfg = get_active_club()
        await ctx.send(f"Current club: **{cfg['name']}**. Available: {', '.join(config.CLUBS.keys())}")
        return
    try:
        set_active_club(alias)
        _, cfg = get_active_club()
        await ctx.send(f"Active club set to **{cfg['name']}**.")
    except Exception as exc:
        await ctx.send(f"Unknown club alias `{alias}`. Available: {', '.join(config.CLUBS.keys())}")


@bot.command(name="importstats")
async def importstats_cmd(ctx: commands.Context) -> None:
    """!importstats — import stats from attached JSON file."""
    if not ctx.message.attachments:
        await ctx.send("Attach a JSON stats file.")
        return
    att = ctx.message.attachments[0]
    data = await att.read()
    try:
        import json
        stats = json.loads(data)
        import_stats_from_file(stats)
        await ctx.send("Stats imported successfully.")
    except Exception as exc:
        await ctx.send(f"Import failed: `{exc}`")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    token = config.DISCORD_BOT_TOKEN
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.critical("DISCORD_BOT_TOKEN is not set!")
        sys.exit(1)
    logger.info("Starting Calculated Chaos bot…")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
