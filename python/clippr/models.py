"""Plain records shared by the parser, detector, and recorder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Kill:
    tick: int
    round_number: int
    attacker_steamid: str
    attacker_name: str
    attacker_side: str
    victim_steamid: str
    victim_name: str
    victim_side: str
    weapon: str
    headshot: bool = False
    noscope: bool = False
    penetrated: int = 0
    thrusmoke: bool = False
    attackerblind: bool = False


@dataclass
class Death:
    tick: int
    round_number: int
    victim_steamid: str
    attacker_steamid: str = ""
    attacker_side: str = ""
    victim_side: str = ""


@dataclass
class Round:
    number: int
    start_tick: int
    freeze_end_tick: int
    end_tick: int
    winner: str


@dataclass
class Highlight:
    id: str
    player: str
    steamid: str
    side: str
    round: int
    type: str
    detail: str
    weapon: str
    kills: int
    headshots: int
    focus_start_tick: int
    focus_end_tick: int
    round_start_tick: int
    round_end_tick: int
    spec_slot: int | None
    score: int
    crosshair_code: str = ""
    kill_ticks: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
