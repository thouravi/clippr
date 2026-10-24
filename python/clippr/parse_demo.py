"""Read a CS2 demo with demoparser2 and hand plain records to the detector."""

from __future__ import annotations

import gzip
import hashlib
import math
import shutil
from bisect import bisect_right
from collections.abc import Callable
from pathlib import Path

from clippr.models import Death, Kill, Round
from clippr.names import side_of
from clippr.paths import app_dir

Progress = Callable[[str, float], None]
DEFAULT_TICKRATE = 64.0


def ensure_dem_file(path: Path) -> Path:
    """Decompress .dem.gz and .dem.zst into the clippr cache."""
    suffix = path.suffix.lower()
    if suffix not in {".gz", ".zst"}:
        return path
    digest = hashlib.sha1(f"{path.resolve()}|{path.stat().st_mtime_ns}|{path.stat().st_size}".encode()).hexdigest()[:16]
    stem = path.name[: -len(suffix)]
    if not stem.lower().endswith(".dem"):
        stem += ".dem"
    target = app_dir() / "cache" / f"{digest}-{stem}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        return target
    if suffix == ".gz":
        with gzip.open(path, "rb") as source, target.open("wb") as dest:
            shutil.copyfileobj(source, dest)
    else:
        import zstandard

        with path.open("rb") as source, target.open("wb") as dest:
            zstandard.ZstdDecompressor().copy_stream(source, dest)
    return target


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value != value:  # NaN
            return default
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    try:
        if value != value:  # NaN
            return False
    except Exception:
        return False
    return bool(value)


def _cell(row, *names: str, default=None):
    for name in names:
        if name not in getattr(row, "index", ()):
            continue
        value = row[name]
        try:
            if value != value:
                continue
        except Exception:
            pass
        if value is None:
            continue
        return value
    return default


def _event(parser, name: str, **kwargs):
    import pandas as pd

    try:
        frame = parser.parse_event(name, **kwargs)
    except Exception:
        return pd.DataFrame()
    if frame is None:
        return pd.DataFrame()
    return frame


def _crosshairs(parser, rounds: list[Round]) -> dict[str, list[tuple[int, str]]]:
    """Share code per player, sampled at freeze end and round end.

    The sandboxed game loads a default crosshair. The code in effect at the
    highlight is applied later, so a mid-round change is kept when the sample
    is at or before the kill.
    """
    ticks = sorted(
        {
            tick
            for rnd in rounds
            for tick in (rnd.freeze_end_tick or rnd.start_tick, rnd.end_tick)
            if tick > 0
        }
    )
    if not ticks:
        return {}
    try:
        frame = parser.parse_ticks(["crosshair_code"], ticks=ticks)
        if frame is None or getattr(frame, "empty", True):
            return {}
        grouped: dict[str, list[tuple[int, str]]] = {}
        seen: set[tuple[str, int, str]] = set()
        for _, row in frame.iterrows():
            code = str(row.get("crosshair_code") or "").strip()
            steamid = str(row.get("steamid") or "").strip()
            if not steamid or steamid.lower() == "nan" or not code or code.lower() == "nan":
                continue
            tick = _safe_int(row.get("tick"))
            key = (steamid, tick, code)
            if key in seen:
                continue
            seen.add(key)
            grouped.setdefault(steamid, []).append((tick, code))
        for series in grouped.values():
            series.sort()
        return grouped
    except Exception:
        return {}


def _tickrate(parser, header: dict, sample_ticks: list[int]) -> float:
    try:
        ticks = float(header.get("playback_ticks") or 0)
        seconds = float(header.get("playback_time") or 0)
        if seconds > 1 and ticks > seconds:
            rate = ticks / seconds
            if 16 <= rate <= 256:
                return float(round(rate))
    except (TypeError, ValueError):
        pass
    if len(sample_ticks) < 2:
        return DEFAULT_TICKRATE
    start, end = min(sample_ticks), max(sample_ticks)
    if end - start < 256:
        return DEFAULT_TICKRATE
    try:
        frame = parser.parse_ticks(["game_time"], ticks=[start, end])
    except Exception:
        return DEFAULT_TICKRATE
    if frame is None or frame.empty or "game_time" not in frame.columns:
        return DEFAULT_TICKRATE
    grouped = frame.groupby("tick")["game_time"].first()
    if len(grouped) < 2:
        return DEFAULT_TICKRATE
    delta_ticks = float(grouped.index.max() - grouped.index.min())
    delta_time = float(grouped.loc[grouped.index.max()] - grouped.loc[grouped.index.min()])
    if delta_time <= 0:
        return DEFAULT_TICKRATE
    rate = delta_ticks / delta_time
    if not math.isfinite(rate) or rate < 16 or rate > 256:
        return DEFAULT_TICKRATE
    return float(round(rate))


def _rounds(parser, match_start: int) -> list[Round]:
    starts = _event(parser, "round_start")
    ends = _event(parser, "round_end")
    freezes = _event(parser, "round_freeze_end")
    if ends.empty or "tick" not in ends.columns:
        return []
    start_ticks = sorted(_safe_int(tick) for tick in starts.get("tick", []))
    freeze_ticks = sorted(_safe_int(tick) for tick in freezes.get("tick", []))
    rounds: list[Round] = []
    ends = ends.sort_values("tick")
    for _, row in ends.iterrows():
        end_tick = _safe_int(_cell(row, "tick"))
        if end_tick < match_start:
            continue
        prior = [tick for tick in start_ticks if match_start <= tick <= end_tick]
        start_tick = prior[-1] if prior else max(match_start, 0)
        freeze = [tick for tick in freeze_ticks if start_tick <= tick <= end_tick]
        rounds.append(
            Round(
                number=len(rounds) + 1,
                start_tick=start_tick,
                freeze_end_tick=freeze[-1] if freeze else start_tick,
                end_tick=end_tick,
                winner=side_of(_cell(row, "winner", "round_winner")),
            )
        )
    return rounds


def _round_number(start_ticks: list[int], tick: int) -> int:
    index = bisect_right(start_ticks, tick) - 1
    return max(1, index + 1)


def parse_demo(path: Path, progress: Progress | None = None) -> dict:
    def log(message: str, percent: float) -> None:
        if progress:
            progress(message, percent)

    log("Opening demo", 5)
    demo_path = ensure_dem_file(path)
    try:
        from demoparser2 import DemoParser
    except ImportError as exc:
        raise RuntimeError(
            "demoparser2 is not installed. From the repo root run: "
            ".venv\\Scripts\\python -m pip install -r python\\requirements.txt"
        ) from exc

    parser = DemoParser(str(demo_path))
    try:
        header = dict(parser.parse_header() or {})
    except Exception:
        header = {}
    map_name = str(header.get("map_name") or "unknown")

    log("Reading rounds", 20)
    new_match = _event(parser, "begin_new_match")
    match_start = 0
    if not new_match.empty and "tick" in new_match.columns:
        match_start = max(_safe_int(tick) for tick in new_match["tick"])
    rounds = _rounds(parser, match_start)
    if not rounds:
        raise RuntimeError("No rounds found. The demo may be incomplete or not a CS2 file.")
    start_ticks = [rnd.start_tick for rnd in rounds]

    log("Reading kills", 45)
    deaths_frame = _event(
        parser,
        "player_death",
        player=["team_name"],
        other=["is_warmup_period"],
    )
    if deaths_frame.empty:
        raise RuntimeError("No kills found. The demo may be incomplete or not a CS2 file.")

    kills: list[Kill] = []
    deaths: list[Death] = []
    for _, row in deaths_frame.sort_values("tick").iterrows():
        tick = _safe_int(_cell(row, "tick"))
        if tick < match_start or _safe_bool(_cell(row, "is_warmup_period", default=False)):
            continue
        victim = str(_cell(row, "user_steamid", default="") or "")
        attacker = str(_cell(row, "attacker_steamid", default="") or "")
        victim_side = side_of(_cell(row, "user_team_name", "user_team_num"))
        attacker_side = side_of(_cell(row, "attacker_team_name", "attacker_team_num"))
        round_number = _round_number(start_ticks, tick)
        if victim:
            deaths.append(
                Death(
                    tick=tick,
                    round_number=round_number,
                    victim_steamid=victim,
                    attacker_steamid=attacker,
                    attacker_side=attacker_side,
                    victim_side=victim_side,
                )
            )
        if not attacker or attacker == victim:
            continue
        if attacker_side and victim_side and attacker_side == victim_side:
            continue
        kills.append(
            Kill(
                tick=tick,
                round_number=round_number,
                attacker_steamid=attacker,
                attacker_name=str(_cell(row, "attacker_name", default="") or ""),
                attacker_side=attacker_side,
                victim_steamid=victim,
                victim_name=str(_cell(row, "user_name", default="") or ""),
                victim_side=victim_side,
                weapon=str(_cell(row, "weapon", default="") or ""),
                headshot=_safe_bool(_cell(row, "headshot", default=False)),
                noscope=_safe_bool(_cell(row, "noscope", default=False)),
                penetrated=_safe_int(_cell(row, "penetrated", default=0)),
                thrusmoke=_safe_bool(_cell(row, "thrusmoke", default=False)),
                attackerblind=_safe_bool(_cell(row, "attackerblind", default=False)),
            )
        )

    log("Reading players", 70)
    names: dict[str, str] = {}
    try:
        info = parser.parse_player_info()
        for _, row in info.iterrows():
            steamid = str(row.get("steamid") or "")
            if steamid:
                names[steamid] = str(row.get("name") or "")
    except Exception:
        pass
    for kill in kills:
        names.setdefault(kill.attacker_steamid, kill.attacker_name)
        kill.attacker_name = names.get(kill.attacker_steamid, kill.attacker_name)

    log("Sampling rosters", 82)
    rosters: dict[int, dict[str, str]] = {rnd.number: {} for rnd in rounds}
    slots: dict[str, int] = {}
    sample_ticks = []
    sample_round: dict[int, int] = {}
    for rnd in rounds:
        sample = rnd.freeze_end_tick + 16
        sample_ticks.append(sample)
        sample_round[sample] = rnd.number
    try:
        sampled = parser.parse_ticks(["team_num", "is_alive", "user_id"], ticks=sample_ticks)
    except Exception:
        sampled = None
    if sampled is not None and not sampled.empty:
        for _, row in sampled.iterrows():
            tick = _safe_int(row.get("tick"))
            round_number = sample_round.get(tick)
            if round_number is None:
                continue
            steamid = str(row.get("steamid") or "")
            if not steamid:
                continue
            if "is_alive" in sampled.columns and not _safe_bool(row.get("is_alive")):
                continue
            side = side_of(row.get("team_num"))
            if side in {"T", "CT"}:
                rosters[round_number][steamid] = side
            user_id = row.get("user_id")
            if user_id is not None and steamid not in slots:
                try:
                    if user_id == user_id:
                        slots[steamid] = int(user_id) + 1
                except (TypeError, ValueError):
                    pass

    log("Reading crosshairs", 90)
    crosshairs = _crosshairs(parser, rounds)
    tickrate = _tickrate(parser, header, [kill.tick for kill in kills] or [rounds[-1].end_tick])
    log("Demo ready", 100)
    return {
        "source_path": str(path),
        "demo_path": str(demo_path),
        "map_name": map_name,
        "tickrate": tickrate,
        "duration_seconds": round(rounds[-1].end_tick / tickrate, 1),
        "rounds": rounds,
        "kills": kills,
        "deaths": deaths,
        "rosters": rosters,
        "slots": slots,
        "player_names": names,
        "crosshairs": crosshairs,
    }
