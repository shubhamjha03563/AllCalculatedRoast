"""
club_state.py — Tracks the currently active club for the bot session.

The active club can be switched at runtime with !setclub.
Defaults to DEFAULT_CLUB_ALIAS from config.
"""

from __future__ import annotations
import config

_active_alias: str = config.DEFAULT_CLUB_ALIAS


def get_active_club() -> tuple[str, dict]:
    """Return (alias, club_config_dict) for the currently active club."""
    alias = _active_alias
    cfg   = config.CLUBS.get(alias)
    if cfg is None:
        # Fallback to default
        alias = config.DEFAULT_CLUB_ALIAS
        cfg   = config.CLUBS[alias]
    return alias, cfg


def set_active_club(alias: str) -> None:
    """Switch the active club. Raises KeyError if alias is unknown."""
    global _active_alias
    if alias not in config.CLUBS:
        raise KeyError(f"Unknown club alias '{alias}'. Available: {list(config.CLUBS.keys())}")
    _active_alias = alias
