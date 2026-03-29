"""
match_fetcher.py — Retrieves match data from either mock JSON or a live API.

The active club (ID, platform) is read from club_state at call-time,
so switching clubs with !setclub automatically affects match fetching.

Session warming: EA's API sometimes requires a lightweight "warm-up" request
on the same HTTPS connection before it will serve match data.  We reuse a
single requests.Session (with browser-like headers) across warm-up and fetch.
"""

from __future__ import annotations

import requests
import json
import logging
from pathlib import Path
from typing import Any

try:
    from curl_cffi import requests as curl_requests
    _USE_CURL = True
except ImportError:
    import requests as curl_requests
    _USE_CURL = False

import config
from club_state import get_active_club

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Shared session — browser-like headers help avoid 403/SSL resets from EA
# ─────────────────────────────────────────────────────────────────────────────

_EA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-US,en;q=0.9",
    "Accept-Encoding":    "gzip, deflate, br, zstd",
    "Origin":             "https://www.ea.com",
    "Referer":            "https://www.ea.com/games/ea-sports-fc/pro-clubs/overview",
    "Connection":         "keep-alive",
    "Sec-Fetch-Dest":     "empty",
    "Sec-Fetch-Mode":     "cors",
    "Sec-Fetch-Site":     "same-site",
    "Sec-Ch-Ua":          '"Chromium";v="134", "Google Chrome";v="134", "Not:A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile":   "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Cache-Control":      "no-cache",
    "Pragma":             "no-cache",
}

_WARM_URL = "https://proclubs.ea.com/api/fc/clubs/search"

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """Return (or create) the shared session with EA-friendly headers."""
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(_EA_HEADERS)
        if config.API_KEY:
            _session.headers["Authorization"] = f"Bearer {config.API_KEY}"
    return _session


def _warm_session(platform: str, timeout: int) -> None:
    """Hit the lightweight club-search endpoint to prime the HTTPS session.

    EA's infrastructure seems to require a valid session cookie / TLS state
    before the match endpoint responds.  We fire a low-cost search request
    first and swallow any errors — the warm-up is best-effort.
    """
    session = _get_session()
    try:
        logger.info("EA session warm-up: GET %s", _WARM_URL)
        resp = session.get(
            _WARM_URL,
            params={"platform": platform, "clubName": "a"},
            timeout=timeout,
        )
        logger.info("EA warm-up response: HTTP %s", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EA warm-up failed (non-fatal): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

def fetch_latest_match(match_type: str = "leagueMatch") -> dict[str, Any]:
    """Return the latest match data as a normalised dict for the active club.

    Returns a dict with at minimum:
        {
            "match_id": str,
            "date": str,
            "result": str,
            "opponent": str,
            "players": [ { ...player stats... }, ... ]
        }

    Raises:
        RuntimeError: if data cannot be loaded from any source.
    """
    if config.USE_MOCK_DATA:
        logger.info("Using mock match data from %s", config.MOCK_DATA_PATH)
        return _load_mock_data()

    alias, cfg = get_active_club()
    logger.info(
        "Fetching live match data for %s (club_id=%s) from %s",
        cfg["name"], cfg["id"], config.API_ENDPOINT,
    )
    return _fetch_live_data(cfg["id"], cfg.get("platform", "common-gen5"), match_type)


# ─────────────────────────────────────────────────────────────────────────────
# Mock data loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_mock_data() -> dict[str, Any]:
    path = Path(config.MOCK_DATA_PATH)
    if not path.exists():
        raise RuntimeError(
            f"Mock data file not found: {path.resolve()}\n"
            "Make sure mock_match_data.json is in the project root."
        )
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    _validate_match_payload(data)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Live API fetcher
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_live_data(club_id: str, platform: str = "common-gen5", match_type: str = "leagueMatch") -> dict[str, Any]:
    """Fetch the latest match from EA API. match_type: leagueMatch | playoffMatch | friendlyMatch"""
    """Fetch the latest match from the configured API endpoint.

    Warms the HTTPS session first, then retries up to MAX_RETRIES times
    with exponential backoff to handle EA's flaky proclubs.ea.com API.
    """
    import time

    MAX_RETRIES = 3
    TIMEOUT     = 30          # seconds — EA often takes 15-20 s to respond
    BACKOFF     = [2, 5, 10]  # wait this many seconds between attempts

    session = _get_session()
    params: dict[str, str] = {"clubIds": club_id, "platform": platform, "matchType": match_type}

    # Warm-up: prime the HTTPS session before the real request
    _warm_session(platform, timeout=TIMEOUT)

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(
                "EA API request (attempt %d/%d) club_id=%s",
                attempt, MAX_RETRIES, club_id,
            )
            response = session.get(
                config.API_ENDPOINT,
                params=params,
                timeout=TIMEOUT,
            )
            response.raise_for_status()

            raw: Any = response.json()
            normalised = _default_normalise(raw)
            _validate_match_payload(normalised)
            return normalised

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = BACKOFF[attempt - 1]
                logger.warning(
                    "EA API timeout/connection error on attempt %d — retrying in %ds: %s",
                    attempt, wait, exc,
                )
                time.sleep(wait)
            else:
                logger.error("EA API failed after %d attempts: %s", MAX_RETRIES, exc)

        except requests.RequestException as exc:
            # Non-transient error (4xx, bad JSON, etc.) — don't retry
            raise RuntimeError(f"Failed to fetch match data from API: {exc}") from exc

    raise RuntimeError(
        f"Failed to fetch match data after {MAX_RETRIES} attempts "
        f"(EA API may be down): {last_exc}"
    ) from last_exc


def _default_normalise(raw: Any) -> dict[str, Any]:
    """Parse EA API response into normalised match dict.

    EA returns:
    [
      {
        "matchId": "523052763790389",
        "timestamp": 1774738016,
        "clubs": {
          "458209": {
            "goals": "4", "goalsAgainst": "0", "result": "1",
            "details": {"name": "All Calculated", ...}
          },
          "<opp_id>": { ... }
        },
        "players": {
          "458209": {
            "<player_id>": { "playername": "RoyalBannaJi", "goals": "2", ... }
          }
        },
        "aggregate": { ... }
      }
    ]
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    if "match_id" in raw and "players" in raw:
        return raw   # already normalised

    alias, cfg = get_active_club()
    our_club_id = str(cfg["id"])

    match_id  = str(raw.get("matchId", ""))
    timestamp = raw.get("timestamp", 0)
    clubs     = raw.get("clubs", {})
    players_d = raw.get("players", {})

    # ── Club data ────────────────────────────────────────────
    our_club  = clubs.get(our_club_id, {})
    opp_clubs = {k: v for k, v in clubs.items() if k != our_club_id}
    opp_club  = next(iter(opp_clubs.values()), {})

    our_goals = int(our_club.get("goals", 0))
    opp_goals = int(our_club.get("goalsAgainst", 0))
    result_raw = our_club.get("result", "0")  # "1"=win "2"=loss "0"=draw

    result = {"1": "Win", "2": "Loss", "0": "Draw"}.get(str(result_raw), "Draw")
    score  = f"{our_goals} - {opp_goals}"

    opp_name = (opp_club.get("details", {}) or {}).get("name", "Unknown")
    our_name = (our_club.get("details", {}) or {}).get("name", cfg["name"])
    venue    = (our_club.get("details", {}) or {}).get("customKit", {}).get("stadName", "")

    import datetime as _dt
    try:
        date_str = _dt.datetime.fromtimestamp(timestamp).strftime("%A %dst %B").replace("  ", " ")
    except Exception:
        date_str = ""

    match_type_map = {"1": "League Match", "2": "Playoff Match", "5": "Friendly"}
    match_type = match_type_map.get(str(our_club.get("matchType", "1")), "Match")

    # ── Players ──────────────────────────────────────────────
    our_players_raw = players_d.get(our_club_id, {})
    players = []

    for pid, p in our_players_raw.items():
        def _i(k, default=0):
            try: return int(p.get(k, default) or default)
            except (ValueError, TypeError): return default
        def _f(k, default=0.0):
            try: return float(p.get(k, default) or default)
            except (ValueError, TypeError): return default

        # ── Parse match_event_aggregate into a dict ───────────────────────
        # Format: "event_id:value,event_id:value,..."
        events: dict[int, int] = {}
        for agg_key in ("match_event_aggregate_0", "match_event_aggregate_1"):
            raw_agg = p.get(agg_key, "") or ""
            for part in raw_agg.split(","):
                if ":" in part:
                    try:
                        eid, val = part.split(":", 1)
                        events[int(eid)] = int(val)
                    except (ValueError, TypeError):
                        pass

        def _ev(event_id: int, default: int = 0) -> int:
            return events.get(event_id, default)

        # ── EA event ID reference ─────────────────────────────────────────
        # 6=shots_on_target  8=shots_total   13=tackles_made  29=interceptions
        # 32=tackle_attempts 145=2nd_assists  152=big_chances_missed
        # 157=long_goals     174=dribbles     177=own_goals    178=red_cards

        shots    = _ev(8)   or _i("shots")
        sot      = _ev(6)   or _i("shotsongoal")
        tkl      = _ev(13)  or _i("tacklesmade")
        tkl_att  = _ev(32)  or _i("tackleattempts")
        ints     = _ev(29)  or _i("interceptions")
        dribbles = _ev(174) or _i("dribbles")
        long_g   = _ev(157) or _i("longgoals")
        own_g    = _ev(177) or _i("owngoals")
        red_c    = _ev(178) or _i("redcards")
        bcm      = _ev(152) or _i("bigchancesmissed")
        ast2     = _ev(5)   or _i("secondassists")   # event 5 = second assists

        # Goals: trust direct field only — event IDs are unreliable for goals
        goals_raw = _i("goals")
        goals     = min(goals_raw, shots) if shots > 0 else 0
        goals     = min(goals, 6)

        # Passes + tackles: direct fields are reliable, use as primary
        pas_att  = _i("passattempts")
        pas_made = _i("passesmade")
        # For tackles_attempted prefer direct field over event aggregate
        if _i("tackleattempts") > 0:
            tkl_att = _i("tackleattempts")
        # Sanity: tackles made can't exceed attempts
        if tkl > tkl_att:
            tkl, tkl_att = tkl_att, tkl

        players.append({
            "name":               p.get("playername", "Unknown"),
            "position":           p.get("pos", p.get("position", "")),
            "rating":             _f("rating"),
            "goals":              goals,
            "assists":            _i("assists"),
            "second_assists":     ast2,
            "shots":              shots,
            "shots_on_target":    sot,
            "passes_attempted":   pas_att,
            "passes_completed":   pas_made,
            "tackles":            tkl,
            "tackles_attempted":  tkl_att,
            "interceptions":      ints,
            "dribbles":           dribbles,
            "long_goals":         long_g,
            "big_chances_missed": bcm,
            "own_goals":          own_g,
            "red_cards":          red_c,
            "saves":              _i("saves"),
        })

    return {
        "match_id":      match_id,
        "date":          date_str,
        "result":        result,
        "score":         score,
        "our_score":     our_goals,
        "opp_score":     opp_goals,
        "opponent":      opp_name,
        "our_club":      our_name,
        "venue":         venue,
        "match_type":    match_type,
        "minutes_played": 0,
        "players":       players,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_MATCH_KEYS = {"match_id", "result", "players"}


def _validate_match_payload(data: dict[str, Any]) -> None:
    missing_match = _REQUIRED_MATCH_KEYS - data.keys()
    if missing_match:
        raise ValueError(f"Match payload is missing keys: {missing_match}")
    if not data.get("players"):
        raise ValueError("Match payload has no players")
