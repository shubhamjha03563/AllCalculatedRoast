"""
session_parser.py — Parses OurProClub Session Recap from Discord embed fields.

Public interface:
    parse_session_text(text)               -> dict
    build_session_report(session, club)    -> list[discord.Embed]
"""

from __future__ import annotations

import re
import logging
from typing import Any

import discord

from lifetime_stats import get_player_stats, get_all_stats
from roast_engine import get_roast_victims, build_roast_embeds

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Text cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    """Strip emoji, Discord quote markers, markdown bold/italic, mentions."""
    text = re.sub(r'[^\x00-\x7F]+', '', text)   # strip all non-ASCII (emoji)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)  # > quote prefix
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*(.*?)\*',     r'\1', text)  # *italic*
    text = re.sub(r'<@\d+>',        '',    text)  # @mentions
    # Collapse multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────────────────────────────────────

_NON_NAME = {
    "automatic", "here's", "as a team", "you completed", "club results",
    "session", "no matches", "summary", "results", "wins", "draws", "losses",
    "appearances", "goals", "on target", "conversion", "assists", "second",
    "dribbles", "passes", "successful", "tackles", "interceptions",
    "recap", "stopped",
}


def parse_session_text(text: str) -> dict[str, Any]:
    """Parse cleaned session recap text into structured dict."""
    text = _clean(text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # ── Club-level stats ──────────────────────────────────────────────────
    wins_m   = re.search(r"(\d+) wins?",   text)
    draws_m  = re.search(r"(\d+) draws?",  text)
    losses_m = re.search(r"(\d+) losses?", text)
    wins   = int(wins_m.group(1))   if wins_m   else 0
    draws  = int(draws_m.group(1))  if draws_m  else 0
    losses = int(losses_m.group(1)) if losses_m else 0

    team_goals_m   = re.search(r"scored (\d+) goals",       text)
    team_shots_m   = re.search(r"from (\d+) shots",         text)
    team_assists_m = re.search(r"accumulated (\d+) assists", text)
    team_pas_m     = re.search(r"completed (\d+)/(\d+).*?passes", text)
    team_tkl_m     = re.search(r"made (\d+)/(\d+).*?tackles", text)

    # ── Find player block starts ──────────────────────────────────────────
    block_starts = []
    for i, line in enumerate(lines):
        if not line or line[0].isdigit():
            continue
        if any(line.lower().startswith(k) for k in _NON_NAME):
            continue
        # Next non-empty line must start with a digit
        next_lines = [l for l in lines[i+1:i+5] if l]
        if next_lines and re.match(r"\d+", next_lines[0]):
            block_starts.append(i)

    # ── Parse each player block ───────────────────────────────────────────
    players = []
    for idx, start in enumerate(block_starts):
        end   = block_starts[idx + 1] if idx + 1 < len(block_starts) else len(lines)
        block = "\n".join(lines[start:end])
        name  = lines[start].strip()

        def _int(pattern: str, default: int = 0) -> int:
            m = re.search(pattern, block)
            return int(m.group(1)) if m else default

        # Passes: "187 passes\n145 successful (78%)"
        pas_total = _int(r"(\d+) passes")
        pas_m     = re.search(r"(\d+) passes\n(\d+) successful", block)
        pas_done  = int(pas_m.group(2)) if pas_m else 0

        # Tackles: "53 tackles\n10 successful (19%)"
        tkl_total = _int(r"(\d+) tackles")
        tkl_m     = re.search(r"(\d+) tackles\n(\d+) successful", block)
        tkl_done  = int(tkl_m.group(2)) if tkl_m else 0

        players.append({
            "name":              name,
            "appearances":       _int(r"(\d+) appearances"),
            "goals":             _int(r"(\d+) goals"),
            "shots_on_target":   _int(r"(\d+) on target"),
            "assists":           _int(r"(\d+) assists"),
            "second_assists":    _int(r"(\d+) second assists"),
            "dribbles":          _int(r"(\d+) dribbles"),
            "passes_attempted":  pas_total,
            "passes_completed":  pas_done,
            "tackles":           tkl_done,
            "tackles_attempted": tkl_total,
            "interceptions":     _int(r"(\d+) interceptions"),
        })

    logger.info("Parsed session: %dW %dD %dL, %d players", wins, draws, losses, len(players))

    return {
        "wins":          wins,
        "draws":         draws,
        "losses":        losses,
        "played":        wins + draws + losses,
        "team_goals":    int(team_goals_m.group(1))   if team_goals_m   else 0,
        "team_shots":    int(team_shots_m.group(1))   if team_shots_m   else 0,
        "team_assists":  int(team_assists_m.group(1)) if team_assists_m else 0,
        "team_pas_done": int(team_pas_m.group(1))     if team_pas_m     else 0,
        "team_pas_att":  int(team_pas_m.group(2))     if team_pas_m     else 0,
        "team_tkl_done": int(team_tkl_m.group(1))     if team_tkl_m     else 0,
        "team_tkl_att":  int(team_tkl_m.group(2))     if team_tkl_m     else 0,
        "players":       players,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────────────────────

def build_session_report(session: dict[str, Any], club_name: str = "All Calculated") -> list[discord.Embed]:
    embeds = []
    wins, draws, losses, played = session["wins"], session["draws"], session["losses"], session["played"]

    # ── Overview ──────────────────────────────────────────────────────────
    if wins > losses:
        colour, mood = discord.Colour.green(), "Good session"
    elif wins == losses:
        colour, mood = discord.Colour.gold(), "Mixed session"
    else:
        colour, mood = discord.Colour.red(), "Rough session"

    pas_pct = round(session["team_pas_done"] / max(session["team_pas_att"], 1) * 100)
    tkl_pct = round(session["team_tkl_done"] / max(session["team_tkl_att"], 1) * 100)

    embeds.append(discord.Embed(
        title=f"Day-End Session Report -- {club_name}",
        description=(
            f"{mood}\n\n"
            f"**{wins}W / {draws}D / {losses}L** across {played} matches\n\n"
            f"Goals: **{session['team_goals']}** from **{session['team_shots']}** shots\n"
            f"Assists: **{session['team_assists']}**\n"
            f"Passing: **{session['team_pas_done']}/{session['team_pas_att']}** ({pas_pct}%)\n"
            f"Tackles: **{session['team_tkl_done']}/{session['team_tkl_att']}** ({tkl_pct}%)"
        ),
        colour=colour,
    ))

    # ── Player performances ───────────────────────────────────────────────
    all_lifetime = get_all_stats()
    player_lines = []

    for p in session["players"]:
        name       = p["name"]
        apps       = max(p.get("appearances", 1), 1)
        lt         = _fuzzy_lookup(all_lifetime, name)
        lt_matches = lt.get("matches", 0) if lt else 0

        gpg_s = round(p["goals"] / apps, 2)
        gpg_c = round(lt.get("goals", 0) / max(lt_matches, 1), 2) if lt else 0
        g_arr = "up" if gpg_s - gpg_c > 0.1 else ("down" if gpg_s - gpg_c < -0.1 else "~")

        apg_s = round(p["assists"] / apps, 2)
        apg_c = round(lt.get("assists", 0) / max(lt_matches, 1), 2) if lt else 0
        a_arr = "up" if apg_s - apg_c > 0.1 else ("down" if apg_s - apg_c < -0.1 else "~")

        pas_s = round(p["passes_completed"] / max(p["passes_attempted"], 1) * 100)
        pas_c = round(lt.get("passes_completed", 0) / max(lt.get("passes_attempted", 1), 1) * 100) if lt else 0
        p_arr = "up" if pas_s - pas_c > 3 else ("down" if pas_s - pas_c < -3 else "~")

        player_lines.append(
            f"**{name}** ({apps} games)\n"
            f"  Goals: {p['goals']} ({gpg_s}/g {g_arr} vs {gpg_c})  "
            f"Assists: {p['assists']} ({apg_s}/g {a_arr})\n"
            f"  Pass: {pas_s}% {p_arr}  "
            f"Tackles: {p['tackles']}/{p['tackles_attempted']}  "
            f"Int: {p['interceptions']}"
        )

    embeds.append(discord.Embed(
        title="Player Performances",
        description="\n\n".join(player_lines) or "No player data.",
        colour=discord.Colour.blurple(),
    ))

    # ── Awards ────────────────────────────────────────────────────────────
    players = session["players"]
    awards  = []

    def _best(key, label, per_game=False):
        cands = [p for p in players if p.get(key, 0) > 0]
        if not cands:
            return
        best = max(cands, key=lambda p: p[key] / max(p.get("appearances", 1) or 1, 1) if per_game else p.get(key, 0))
        val  = round(best[key] / max(best.get("appearances", 1) or 1, 1), 2) if per_game else best[key]
        awards.append(f"**{label}**: {best['name']} ({val})")

    _best("goals",        "Golden Boot")
    _best("assists",      "Playmaker")
    _best("interceptions","Pickpocket")
    _best("dribbles",     "Dribble Machine", per_game=True)

    pas_cands = [p for p in players if p.get("passes_attempted", 0) >= 20]
    if pas_cands:
        best_pas = max(pas_cands, key=lambda p: p["passes_completed"] / max(p["passes_attempted"], 1))
        pct = round(best_pas["passes_completed"] / max(best_pas["passes_attempted"], 1) * 100)
        awards.append(f"**Metronome**: {best_pas['name']} ({pct}% pass accuracy)")

    tkl_cands = [p for p in players if p.get("tackles_attempted", 0) >= 10]
    if tkl_cands:
        worst = min(tkl_cands, key=lambda p: p["tackles"] / max(p["tackles_attempted"], 1))
        pct = round(worst["tackles"] / max(worst["tackles_attempted"], 1) * 100)
        awards.append(f"**Flailing Legs** (curse): {worst['name']} ({pct}% from {worst['tackles_attempted']} attempts)")

    embeds.append(discord.Embed(
        title="Session Awards",
        description="\n".join(awards) if awards else "No standout performances.",
        colour=discord.Colour.gold(),
    ))

    # ── Story ─────────────────────────────────────────────────────────────
    embeds.append(discord.Embed(
        title="The Story",
        description=_narrative(session, club_name),
        colour=discord.Colour.dark_blue(),
    ))

    # ── Roasts ───────────────────────────────────────────────────────────
    roast_players = [{
        "name":              p["name"],
        "position":          "",
        "goals":             p["goals"],
        "shots":             p["shots_on_target"],
        "passes_completed":  p["passes_completed"],
        "passes_attempted":  p["passes_attempted"],
        "tackles":           p["tackles"],
        "tackles_attempted": p["tackles_attempted"],
        "interceptions":     p["interceptions"],
    } for p in session["players"]]

    victims = get_roast_victims(roast_players)
    roast_embeds = build_roast_embeds(victims, {
        "score":    f"{wins}W/{draws}D/{losses}L",
        "opponent": "Session",
    })
    embeds.extend(roast_embeds)

    return embeds


# ─────────────────────────────────────────────────────────────────────────────
# Narrative
# ─────────────────────────────────────────────────────────────────────────────

def _narrative(session: dict, club_name: str) -> str:
    wins, draws, losses, played = session["wins"], session["draws"], session["losses"], session["played"]
    players = session["players"]

    if wins > losses:
        opener = f"{club_name} had a strong session, {wins} win{'s' if wins>1 else ''} from {played} matches."
    elif losses > wins + draws:
        opener = f"Tough session for {club_name}. {losses} losses from {played} games."
    else:
        opener = f"{club_name} went {wins}W/{draws}D/{losses}L across {played} matches."

    scorer = max(players, key=lambda p: p["goals"]) if players else None
    s_line = f" **{scorer['name']}** led with **{scorer['goals']} goals**." if scorer and scorer["goals"] > 0 else ""

    assister = max(players, key=lambda p: p["assists"]) if players else None
    a_line = (
        f" **{assister['name']}** chipped in with {assister['assists']} assists."
        if assister and assister["assists"] > 0 and assister != scorer else ""
    )

    top_def = max(players, key=lambda p: p["interceptions"]) if players else None
    d_line = f" **{top_def['name']}** disrupted with {top_def['interceptions']} interceptions." if top_def and top_def["interceptions"] >= 8 else ""

    pas_pct = round(session["team_pas_done"] / max(session["team_pas_att"], 1) * 100)
    p_line = (
        f" Passing was sharp at {pas_pct}%." if pas_pct >= 85
        else f" Passing was sloppy at {pas_pct}%." if pas_pct < 75
        else ""
    )

    return opener + s_line + a_line + d_line + p_line


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_lookup(all_stats: dict, name: str) -> dict | None:
    if name in all_stats:
        return all_stats[name]
    nl = name.lower()
    for k, v in all_stats.items():
        if k.lower() == nl:
            return v
    for k, v in all_stats.items():
        if k.lower().startswith(nl) or nl.startswith(k.lower()):
            return v
    return None
