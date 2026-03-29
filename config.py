"""
config.py — Central configuration for Calculated Chaos bot.

Set environment variables or replace the defaults below before running.
"""

import os

# ─────────────────────────────────────────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
BOT_PREFIX: str = os.getenv("BOT_PREFIX", "!")

# ─────────────────────────────────────────────────────────────────────────────
# CLUBS  —  add new clubs here, no other files need changing
# ─────────────────────────────────────────────────────────────────────────────
CLUBS: dict = {
    "allcalculated": {"id": "458209", "name": "All Calculated",  "platform": "common-gen5"},
    "blablafc":      {"id": "501527", "name": "Bla Bla FC",      "platform": "common-gen5"},
    "bluelock":      {"id": "28051",  "name": "Blue Lock F C",   "platform": "common-gen5"},
}

DEFAULT_CLUB_ALIAS: str = "allcalculated"

def crown_history_file(alias: str) -> str:
    return f"crown_history_{alias}.json"

def lifetime_stats_file(alias: str) -> str:
    return f"lifetime_stats_{alias}.json"

def get_club(alias: str) -> dict | None:
    """Case-insensitive club lookup by alias. Returns None if not found."""
    return CLUBS.get(alias.lower())

def list_clubs() -> list[tuple[str, dict]]:
    """Return list of (alias, cfg) tuples."""
    return list(CLUBS.items())

# ─────────────────────────────────────────────────────────────────────────────
# MATCH DATA SOURCE
# ─────────────────────────────────────────────────────────────────────────────
USE_MOCK_DATA: bool = False
API_ENDPOINT: str = os.getenv("API_ENDPOINT", "https://proclubs.ea.com/api/fc/clubs/matches")
API_KEY: str = os.getenv("API_KEY", "")
MOCK_DATA_PATH: str = os.getenv("MOCK_DATA_PATH", "mock_match_data.json")

# ─────────────────────────────────────────────────────────────────────────────
# BOT BEHAVIOUR
# ─────────────────────────────────────────────────────────────────────────────
LEADERBOARD_SIZE: int = 10
CROWN_HISTORY_FILE: str = "crown_history_{club_alias}.json"
LIFETIME_STATS_FILE: str = "lifetime_stats_{club_alias}.json"

# ─────────────────────────────────────────────────────────────────────────────
# AUTO REPORT
# ─────────────────────────────────────────────────────────────────────────────
AUTO_REPORT_INTERVAL_MINUTES: int = int(os.getenv("AUTO_REPORT_INTERVAL_MINUTES", "10"))
AUTO_REPORT_TIMEOUT_MINUTES: int  = int(os.getenv("AUTO_REPORT_TIMEOUT_MINUTES",  "60"))

# ─────────────────────────────────────────────────────────────────────────────
# OURPROCLUB IMAGE LISTENER
# ─────────────────────────────────────────────────────────────────────────────

# Discord user ID of the OurProClub bot (right-click bot → Copy User ID)
OURPROCLUBS_BOT_ID: str = os.getenv("OURPROCLUBS_BOT_ID", "1361001092917493921")

# Optional: restrict listener to one channel ID (blank = any channel)
OURPROCLUBS_WATCH_CHANNEL_ID: str = os.getenv("OURPROCLUBS_WATCH_CHANNEL_ID", "")

# Channel where roasts are posted
ROAST_CHANNEL_ID: str = os.getenv("ROAST_CHANNEL_ID", "1484188553561768058")  # roast + chaos report channel


# Anthropic API key — used by roast_engine.py for Claude-generated roasts