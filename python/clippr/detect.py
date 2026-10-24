"""Group demo kills into a short list of shareable highlights.

A highlight is a multi-kill, a won clutch, or a single notable kill
(opening duel, noscope, wallbang, blind, or through smoke). Plain trades
are left out so the list stays short.
"""

from __future__ import annotations

from collections import defaultdict

from clippr.models import Death, Highlight, Kill, Round
from clippr.names import weapon_label

# Kills farther apart than this become separate clips, unless they form an ace.
MAX_GAP_SECONDS = 15.0
ACE_SPAN_SECONDS = 60.0


def badge_for(kills: int, clutch_x: int | None, notable: str | None) -> str | None:
    if kills >= 5:
        return "Ace"
    if clutch_x is not None and clutch_x >= 3:
        return f"1v{clutch_x}"
    if kills >= 4:
        return "4K"
    if clutch_x is not None and clutch_x >= 2:
        return f"1v{clutch_x}"
    if kills >= 3:
        return "3K"
    if clutch_x is not None and clutch_x >= 1:
        return f"1v{clutch_x}"
    if kills >= 2:
        return "2K"
    if notable:
        return notable
    return None


def _score(badge: str, kills: int) -> int:
    if badge.startswith("1v"):
        try:
            return 36 + 14 * int(badge[2:])
        except ValueError:
            return 40
    table = {
        "Ace": 100,
        "4K": 80,
        "3K": 55,
        "2K": 30,
        "Noscope": 28,
        "Wallbang": 22,
        "Blind": 18,
        "Smoke": 18,
        "Opening": 14,
    }
    return table.get(badge, 10) + min(kills, 5)


def _notable(kill: Kill) -> str | None:
    if kill.noscope:
        return "Noscope"
    if kill.penetrated > 0:
        return "Wallbang"
    if kill.attackerblind:
        return "Blind"
    if kill.thrusmoke:
        return "Smoke"
    return None


def _cluster(kills: list[Kill], tickrate: float) -> list[list[Kill]]:
    if not kills:
        return []
    ordered = sorted(kills, key=lambda kill: kill.tick)
    gap = int(MAX_GAP_SECONDS * tickrate)
    groups: list[list[Kill]] = [[ordered[0]]]
    for kill in ordered[1:]:
        if kill.tick - groups[-1][-1].tick <= gap:
            groups[-1].append(kill)
        else:
            groups.append([kill])
    if len(ordered) >= 5 and ordered[-1].tick - ordered[0].tick <= int(ACE_SPAN_SECONDS * tickrate):
        return [ordered]
    return groups


def _cluster_owns(cluster: list[Kill], started: int, clusters: list[list[Kill]]) -> bool:
    """True when this cluster is the one that should carry the round's clutch."""
    if cluster[0].tick <= started <= cluster[-1].tick:
        return True
    following = [item for item in clusters if item[-1].tick >= started]
    return bool(following) and following[0] is cluster


def _primary_weapon(kills: list[Kill]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for kill in kills:
        counts[kill.weapon] += 1
    raw = max(counts, key=lambda weapon: (counts[weapon], weapon == kills[-1].weapon))
    return weapon_label(raw)


def _detail(kills: int, headshots: int, clutch_x: int | None, notes: list[str]) -> str:
    parts: list[str] = []
    if clutch_x:
        parts.append(f"1v{clutch_x} clutch")
    if kills > 1:
        parts.append(f"{kills} kills")
    elif kills == 1:
        parts.append("1 kill")
    elif kills == 0 and clutch_x:
        parts.append("round win")
    if headshots and kills > 1:
        parts.append(f"{headshots} headshots")
    elif headshots == 1 and kills <= 1:
        parts.append("headshot")
    for note in notes:
        if note not in " ".join(parts):
            parts.append(note)
    return " · ".join(parts)


def _mark_last_alive(
    alive: dict[str, str],
    clutch_x: dict[str, int],
    clutch_tick: dict[str, int],
    tick: int,
) -> None:
    by_side: dict[str, list[str]] = defaultdict(list)
    for steamid, side in alive.items():
        if side in {"T", "CT"}:
            by_side[side].append(steamid)
    if len(by_side) < 2:
        return
    for side, members in by_side.items():
        if len(members) != 1:
            continue
        steamid = members[0]
        if steamid in clutch_x:
            continue
        enemies = sum(len(group) for other, group in by_side.items() if other != side)
        if enemies >= 1:
            clutch_x[steamid] = enemies
            clutch_tick[steamid] = tick


def find_clutches(
    rounds: list[Round],
    deaths: list[Death],
    rosters: dict[int, dict[str, str]],
) -> dict[tuple[str, int], tuple[int, int]]:
    """Map (steamid, round) to (enemies faced, tick the clutch started).

    Only won clutches are returned. X is the number of enemies alive at the
    moment the player became the last teammate standing.
    """
    found: dict[tuple[str, int], tuple[int, int]] = {}
    deaths_by_round: dict[int, list[Death]] = defaultdict(list)
    for death in deaths:
        deaths_by_round[death.round_number].append(death)

    for rnd in rounds:
        if rnd.winner not in {"T", "CT"}:
            continue
        roster = {sid: side for sid, side in rosters.get(rnd.number, {}).items() if side in {"T", "CT"}}
        if len(roster) < 2:
            continue
        alive = dict(roster)
        clutch_x: dict[str, int] = {}
        clutch_tick: dict[str, int] = {}
        _mark_last_alive(alive, clutch_x, clutch_tick, rnd.freeze_end_tick or rnd.start_tick)
        for death in sorted(deaths_by_round.get(rnd.number, []), key=lambda item: item.tick):
            alive.pop(death.victim_steamid, None)
            _mark_last_alive(alive, clutch_x, clutch_tick, death.tick)
        for steamid, enemies in clutch_x.items():
            if roster.get(steamid) == rnd.winner:
                found[(steamid, rnd.number)] = (enemies, clutch_tick[steamid])
    return found


def detect_highlights(
    kills: list[Kill],
    deaths: list[Death],
    rounds: list[Round],
    rosters: dict[int, dict[str, str]],
    slots: dict[str, int],
    tickrate: float,
    crosshairs: dict[str, list[tuple[int, str]]] | None = None,
) -> list[Highlight]:
    tickrate = tickrate if tickrate >= 16 else 64.0
    rounds_by_number = {rnd.number: rnd for rnd in rounds}
    opening_tick: dict[int, int] = {}
    for kill in sorted(kills, key=lambda item: item.tick):
        opening_tick.setdefault(kill.round_number, kill.tick)

    by_player_round: dict[tuple[str, int], list[Kill]] = defaultdict(list)
    for kill in kills:
        by_player_round[(kill.attacker_steamid, kill.round_number)].append(kill)

    clutches = find_clutches(rounds, deaths, rosters)
    highlights: list[Highlight] = []
    consumed_clutches: set[tuple[str, int]] = set()

    for (steamid, round_number), grouped in by_player_round.items():
        rnd = rounds_by_number.get(round_number)
        if rnd is None:
            continue
        clutch = clutches.get((steamid, round_number))
        clusters = _cluster(grouped, tickrate)
        for cluster in clusters:
            notes: list[str] = []
            if any(kill.tick == opening_tick.get(round_number) for kill in cluster):
                notes.append("opening kill")
            kinds = {_notable(kill) for kill in cluster}
            kinds.discard(None)
            for kind in ("Noscope", "Wallbang", "Blind", "Smoke"):
                if kind in kinds:
                    notes.append(kind.lower())
            notable = next((kind for kind in ("Noscope", "Wallbang", "Blind", "Smoke") if kind in kinds), None)
            if notable is None and "opening kill" in notes and len(cluster) == 1:
                notable = "Opening"

            clutch_x = None
            focus_end = cluster[-1].tick
            if clutch is not None and _cluster_owns(cluster, clutch[1], clusters):
                enemies, _started = clutch
                clutch_x = enemies
                focus_end = max(focus_end, rnd.end_tick)
                consumed_clutches.add((steamid, round_number))

            badge = badge_for(len(cluster), clutch_x, notable)
            if badge is None:
                continue
            player = next((kill.attacker_name for kill in cluster if kill.attacker_name), steamid)
            side = next((kill.attacker_side for kill in cluster if kill.attacker_side), "")
            headshots = sum(1 for kill in cluster if kill.headshot)
            slot = slots.get(steamid)
            highlights.append(
                Highlight(
                    id=f"{steamid}-{round_number}-{cluster[0].tick}",
                    player=player,
                    steamid=steamid,
                    side=side,
                    round=round_number,
                    type=badge,
                    detail=_detail(len(cluster), headshots, clutch_x, notes),
                    weapon=_primary_weapon(cluster),
                    kills=len(cluster),
                    headshots=headshots,
                    focus_start_tick=cluster[0].tick,
                    focus_end_tick=focus_end,
                    round_start_tick=rnd.start_tick,
                    round_end_tick=rnd.end_tick,
                    spec_slot=slot,
                    score=_score(badge, len(cluster)),
                    crosshair_code=_crosshair_at(crosshairs, steamid, cluster[0].tick),
                    kill_ticks=[kill.tick for kill in cluster],
                )
            )

    for (steamid, round_number), (enemies, started) in clutches.items():
        if (steamid, round_number) in consumed_clutches:
            continue
        rnd = rounds_by_number.get(round_number)
        if rnd is None:
            continue
        badge = badge_for(0, enemies, None)
        if badge is None:
            continue
        name = ""
        side = rosters.get(round_number, {}).get(steamid, "")
        for kill in kills:
            if kill.attacker_steamid == steamid and kill.attacker_name:
                name = kill.attacker_name
                side = side or kill.attacker_side
                break
        highlights.append(
            Highlight(
                id=f"{steamid}-{round_number}-clutch-{started}",
                player=name or steamid,
                steamid=steamid,
                side=side,
                round=round_number,
                type=badge,
                detail=_detail(0, 0, enemies, []),
                weapon="Clutch",
                kills=0,
                headshots=0,
                focus_start_tick=started,
                focus_end_tick=rnd.end_tick,
                round_start_tick=rnd.start_tick,
                round_end_tick=rnd.end_tick,
                spec_slot=slots.get(steamid),
                score=_score(badge, 0),
                crosshair_code=_crosshair_at(crosshairs, steamid, started),
            )
        )

    highlights.sort(key=lambda item: (item.round, item.focus_start_tick, -item.score))
    return highlights


def _crosshair_at(samples: dict[str, list[tuple[int, str]]] | None, steamid: str, tick: int) -> str:
    series = (samples or {}).get(steamid) or []
    chosen = ""
    for sample_tick, code in series:
        if sample_tick <= tick:
            chosen = code
        else:
            break
    if chosen:
        return chosen
    return series[0][1] if series else ""


def clip_window(
    highlight: dict,
    tickrate: float,
    lead_in: float,
    lead_out: float,
) -> tuple[int, int, int, int]:
    """Return (seek, spec, record_start, record_end) ticks.

    spec is always after the seek target. Recording starts on a later tick
    than spec, because CS2 drops spec_player when it shares a tick with
    demo_gototick.
    """
    rate = tickrate if tickrate >= 16 else 64.0
    focus_start = int(highlight["focus_start_tick"])
    focus_end = int(highlight["focus_end_tick"])
    round_start = int(highlight.get("round_start_tick") or 0)
    record_start = max(128, round_start, focus_start - int(round(lead_in * rate)))
    record_end = max(record_start + int(rate), focus_end + int(round(lead_out * rate)))
    spec = max(96, record_start - max(32, int(rate // 2)))
    seek = max(96, spec - max(64, int(rate)))
    if spec >= record_start:
        spec = max(seek + 1, record_start - 1)
    if seek >= spec:
        seek = max(96, spec - 1)
    return seek, spec, record_start, record_end
