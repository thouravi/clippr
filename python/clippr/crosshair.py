"""Turn a CS2 crosshair share code from a demo into console commands.

Demos store each player's code on CCSPlayerController.m_szCrosshairCodes.
Current codes are the cs2-v1 container: "CS" plus 44 base-57 characters,
which unpack to 32 bytes. The layout is the one CS2 has used since the
30 September 2026 share-code change.
"""

from __future__ import annotations

DICTIONARY = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"
_INDEX = {char: index for index, char in enumerate(DICTIONARY)}


def crosshair_commands(code: str) -> list[str]:
    """Commands that reproduce this share code. Empty when the code is unusable."""
    settings = decode_crosshair(code)
    if settings is None:
        return []
    commands = [f'apply_crosshair_code "{code}"']
    commands.extend(f"{name} {value}" for name, value in settings)
    return commands


def decode_crosshair(code: str) -> list[tuple[str, str]] | None:
    text = (code or "").strip()
    if len(text) != 46 or not text.startswith("CS"):
        return None
    if any(char not in _INDEX for char in text[2:]):
        return None
    raw = _chars_to_bytes(text[2:], 32)
    if raw[0] != sum(raw[1:]) % 256 or raw[1] != 1:
        return None
    height = int.from_bytes(raw[2:4], "little")
    if height < 240:
        return None
    flags = raw[4]
    style = min(9, flags & 0x1F)
    thickness = min(32, raw[13] & 0x3F)
    outline = min(2, (raw[13] >> 6) & 0x3)
    gap = max(-3840, min(3840, int.from_bytes(raw[14:16], "little", signed=True)))
    field = int.from_bytes(raw[18:22], "little")
    split_distance = field & 0x7F
    inner = min(1.0, ((field >> 7) & 0x7F) * 0.01)
    outer = min(1.0, 0.3 + ((field >> 14) & 0x7F) * 0.01)
    ratio = min(1.0, ((field >> 21) & 0x7F) * 0.01)
    scope_color = (field >> 28) & 1
    scope_scale = min(2.0, (raw[22] + 10) / 100)
    return [
        ("cl_crosshairstyle", str(style)),
        ("cl_crosshair_recoil", str((flags >> 5) & 1)),
        ("cl_crosshairdot", str((flags >> 6) & 1)),
        ("cl_crosshair_t", str((flags >> 7) & 1)),
        ("cl_crosshaircolor_r", str(raw[5])),
        ("cl_crosshaircolor_g", str(raw[6])),
        ("cl_crosshaircolor_b", str(raw[7])),
        ("cl_crosshaircolor_a", str(raw[8])),
        ("cl_crosshairoutline_r", str(raw[9])),
        ("cl_crosshairoutline_g", str(raw[10])),
        ("cl_crosshairoutline_b", str(raw[11])),
        ("cl_crosshairoutline_a", str(raw[12])),
        ("cl_crosshair_thickness", str(thickness)),
        ("cl_crosshair_drawoutline", str(outline)),
        ("cl_crosshair_gap", str(gap)),
        ("cl_crosshair_length", str(raw[16])),
        ("cl_crosshair_dynamic_spread_limit", str(raw[17])),
        ("cl_crosshair_dynamic_splitdist", str(split_distance)),
        ("cl_crosshair_dynamic_splitalpha_innermod", _num(inner)),
        ("cl_crosshair_dynamic_splitalpha_outermod", _num(outer)),
        ("cl_crosshair_dynamic_maxdist_splitratio", _num(ratio)),
        ("cl_crosshair_screen_height", str(height)),
        ("cl_ironsight_dot_scale", _num(scope_scale)),
        ("cl_ironsight_usecrosshaircolor", str(scope_color)),
    ]


def _chars_to_bytes(chars: str, length: int) -> bytes:
    value = 0
    for char in reversed(chars):
        value = value * 57 + _INDEX[char]
    return value.to_bytes(length, "big")


def _num(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
