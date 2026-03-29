"""
achievements.py — Rule engine that evaluates player stats and assigns
                  achievements (crowns) and curses.

Adding a new achievement or curse:
  1.  Write a function that accepts a player dict and returns True/False.
  2.  Add an entry to ACHIEVEMENTS or CURSES with:
        - key        : unique identifier (used in leaderboard storage)
        - label      : display name shown in Discord
        - emoji      : single emoji prefix
        - condition  : the function you wrote
        - power/curse: the flavour text shown in the Chaos Report
  3.  That's it — the engine picks it up automatically.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

# ─────────────────────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────────────────────

Player = dict[str, Any]


class AchievementDef(TypedDict):
    key: str
    label: str
    emoji: str
    condition: Callable[[Player], bool]
    power: str


class CurseDef(TypedDict):
    key: str
    label: str
    emoji: str
    condition: Callable[[Player], bool]
    curse: str


class PlayerResult(TypedDict):
    player: Player
    achievements: list[AchievementDef]
    curses: list[CurseDef]


# ─────────────────────────────────────────────────────────────────────────────
# Condition helpers
# ─────────────────────────────────────────────────────────────────────────────

def _perfect_passing(p: Player) -> bool:
    """100% pass accuracy with at least 10 passes attempted."""
    return p["passes_attempted"] >= 10 and p["passes_completed"] == p["passes_attempted"]


def _holy_trifecta(p: Player) -> bool:
    """Goal + 2 assists + 100% passing (min 10 passes) in one match."""
    return p["goals"] >= 1 and p["assists"] >= 2 and _perfect_passing(p)


def _sniper(p: Player) -> bool:
    """Score 2 or more long-range goals."""
    return p["long_goals"] >= 2


def _hat_trick(p: Player) -> bool:
    """Score 5 or more goals in a single match."""
    return p["goals"] >= 5


def _midfield_wizard(p: Player) -> bool:
    """3 or more assists in one match — any position."""
    return p["assists"] >= 3


def _midfield_maestro(p: Player) -> bool:
    """Midfielder with 90%+ passing (min 15 attempts) AND 2+ interceptions."""
    pos = p.get("position", "").lower()
    is_mid = any(k in pos for k in ("midfield", "creator", "magician", "recycler",
                                     "maestro", "spark", "cam", "cm", "cdm", "box"))
    if not is_mid:
        return False
    pas_pct = (p["passes_completed"] / max(p["passes_attempted"], 1) * 100
               if p["passes_attempted"] >= 15 else 0)
    return pas_pct >= 90 and p["interceptions"] >= 2


def _defensive_titan(p: Player) -> bool:
    """Defender/CDM with 10+ combined tackles+interceptions."""
    pos = p.get("position", "").lower()
    is_def = any(k in pos for k in ("defend", "boss", "cdm", "sweeper",
                                     "centre back", "fullback", "wall", "recycler"))
    if not is_def:
        return False
    return (p["tackles"] + p["interceptions"]) >= 10


def _iron_wall(p: Player) -> bool:
    """Any position — interceptions + tackles reach 12 or more."""
    return (p["interceptions"] + p["tackles"]) >= 12


def _own_goal_jester(p: Player) -> bool:
    """Score an own goal."""
    return p["own_goals"] >= 1


def _brickfoot(p: Player) -> bool:
    """Miss 3 or more big chances in one match."""
    return p["big_chances_missed"] >= 3


def _ice_cold(p: Player) -> bool:
    """Striker who took zero shots."""
    return p.get("position", "").upper() in {"ST", "CF", "LW", "RW"} and p["shots"] == 0


def _ghost(p: Player) -> bool:
    """Played the full match but 0 goals, 0 assists, 0 interceptions, 0 tackles."""
    return (
        p["goals"] == 0
        and p["assists"] == 0
        and p["interceptions"] == 0
        and p["tackles"] == 0
        and p.get("passes_attempted", 0) >= 5   # actually played, not a sub
    )


def _playmaker(p: Player) -> bool:
    """5 or more assists in one match."""
    return p["assists"] >= 5


# ─────────────────────────────────────────────────────────────────────────────
# Achievement catalogue
# ─────────────────────────────────────────────────────────────────────────────

ACHIEVEMENTS: list[AchievementDef] = [
    {
        "key": "holy_trifecta",
        "label": "Holy Trifecta Crown",
        "emoji": "👑",
        "condition": _holy_trifecta,
        "power": "Controls lineup and positions for the next 3 matches",
    },
    {
        "key": "sniper",
        "label": "Sniper",
        "emoji": "🎯",
        "condition": _sniper,
        "power": "Must attempt at least 5 long shots next match",
    },
    {
        "key": "hat_trick_tyrant",
        "label": "Hat-Trick Tyrant",
        "emoji": "🎩",
        "condition": _hat_trick,
        "power": "Team must feed this player exclusively for one half",
    },
    {
        "key": "midfield_wizard",
        "label": "Midfield Wizard",
        "emoji": "🧙",
        "condition": _midfield_wizard,
        "power": "Chooses the team formation next match",
    },
    {
        "key": "playmaker",
        "label": "Playmaker",
        "emoji": "🎪",
        "condition": _playmaker,
        "power": "Everyone must attempt at least one assist next match — no solo goals",
    },
    {
        "key": "midfield_maestro",
        "label": "Midfield Maestro",
        "emoji": "🎼",
        "condition": _midfield_maestro,
        "power": "Calls all set pieces next match — corners, free kicks, everything",
    },
    {
        "key": "defensive_titan",
        "label": "Defensive Titan",
        "emoji": "🧱",
        "condition": _defensive_titan,
        "power": "Chooses who plays at the back next match",
    },
    {
        "key": "iron_wall",
        "label": "Iron Wall",
        "emoji": "🛡️",
        "condition": _iron_wall,
        "power": "Team must play ultra-defensive next match",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Curse catalogue
# ─────────────────────────────────────────────────────────────────────────────

CURSES: list[CurseDef] = [
    {
        "key": "own_goal_jester",
        "label": "Own Goal Jester",
        "emoji": "🤡",
        "condition": _own_goal_jester,
        "curse": "Team votes your position next match",
    },
    {
        "key": "brickfoot",
        "label": "Brickfoot",
        "emoji": "🧱",
        "condition": _brickfoot,
        "curse": "Must play as a defender next match",
    },
    {
        "key": "ice_cold",
        "label": "Ice Cold",
        "emoji": "🥶",
        "condition": _ice_cold,
        "curse": "Cannot shoot next match — passes only",
    },
    {
        "key": "ghost",
        "label": "Ghost",
        "emoji": "👻",
        "condition": _ghost,
        "curse": "Must announce every touch in voice chat next match",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Public engine function
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_players(players: list[Player]) -> list[PlayerResult]:
    """Run every rule against every player and return structured results."""
    results: list[PlayerResult] = []

    for player in players:
        earned_achievements = [a for a in ACHIEVEMENTS if a["condition"](player)]
        earned_curses       = [c for c in CURSES       if c["condition"](player)]

        results.append({
            "player":       player,
            "achievements": earned_achievements,
            "curses":       earned_curses,
        })

    return results


def count_crowns(results: list[PlayerResult]) -> dict[str, int]:
    """Return {player_name: crown_count} for all players with at least one crown."""
    return {
        r["player"]["name"]: len(r["achievements"])
        for r in results
        if r["achievements"]
    }
