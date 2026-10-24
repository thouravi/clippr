"""Weapon labels and filesystem-safe clip names."""

from __future__ import annotations

import math
import re

WEAPON_LABELS = {
    "ak47": "AK-47",
    "aug": "AUG",
    "awp": "AWP",
    "bizon": "PP-Bizon",
    "deagle": "Desert Eagle",
    "elite": "Dual Berettas",
    "famas": "FAMAS",
    "fiveseven": "Five-SeveN",
    "g3sg1": "G3SG1",
    "galilar": "Galil AR",
    "glock": "Glock-18",
    "hkp2000": "P2000",
    "m4a1": "M4A4",
    "m4a1_silencer": "M4A1-S",
    "m249": "M249",
    "mac10": "MAC-10",
    "mag7": "MAG-7",
    "mp5sd": "MP5-SD",
    "mp7": "MP7",
    "mp9": "MP9",
    "negev": "Negev",
    "nova": "Nova",
    "p250": "P250",
    "p90": "P90",
    "revolver": "R8 Revolver",
    "sawedoff": "Sawed-Off",
    "scar20": "SCAR-20",
    "sg556": "SG 553",
    "ssg08": "SSG 08",
    "taser": "Zeus",
    "tec9": "Tec-9",
    "ump45": "UMP-45",
    "usp_silencer": "USP-S",
    "xm1014": "XM1014",
    "knife": "Knife",
    "knife_t": "Knife",
    "hegrenade": "HE Grenade",
    "inferno": "Molotov",
    "molotov": "Molotov",
    "incgrenade": "Incendiary",
    "flashbang": "Flashbang",
    "decoy": "Decoy",
    "smokegrenade": "Smoke",
    "c4": "C4",
}


def weapon_label(raw: str) -> str:
    text = (raw or "").strip()
    if text.lower().startswith("weapon_"):
        text = text[7:]
    key = text.lower()
    if key in WEAPON_LABELS:
        return WEAPON_LABELS[key]
    if not text:
        return "Unknown"
    return text.replace("_", " ").upper() if len(text) <= 6 else text.replace("_", " ").title()


def file_token(value: str) -> str:
    """Turn a player name or badge into a single path segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._")
    return cleaned or "player"


def clip_stems(player: str, round_number: int, badge: str) -> tuple[str, str]:
    stem = f"{file_token(player)}_Round{round_number}_{file_token(badge)}"
    return f"{stem}_16x9.mp4", f"{stem}_9x16.mp4"


def side_of(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return {2: "T", 3: "CT"}.get(int(value), "")
    text = str(value).strip().upper()
    if text in {"2", "2.0", "T"}:
        return "T"
    if text in {"3", "3.0", "CT"}:
        return "CT"
    if "COUNTER" in text:
        return "CT"
    if "TERROR" in text or text.startswith("T"):
        return "T"
    return ""
