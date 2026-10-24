"""Steam, CS2, and clippr data directories."""

from __future__ import annotations

import os
import re
from pathlib import Path


def app_dir() -> Path:
    override = os.environ.get("CLIPPR_HOME")
    root = Path(override) if override else Path.home() / ".clippr"
    root.mkdir(parents=True, exist_ok=True)
    return root


def tools_dir() -> Path:
    path = app_dir() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sandbox_dir() -> Path:
    path = app_dir() / "sandbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def work_dir() -> Path:
    path = app_dir() / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_job_path() -> Path:
    return app_dir() / "active.json"


def cancel_path() -> Path:
    return app_dir() / "cancel"


def parse_library_paths(vdf_text: str) -> list[str]:
    """Pull library roots out of Steam's libraryfolders.vdf."""
    paths: list[str] = []
    for match in re.finditer(r'"path"\s+"([^"]+)"', vdf_text, flags=re.IGNORECASE):
        raw = match.group(1).replace("\\\\", "\\")
        if raw and raw not in paths:
            paths.append(raw)
    return paths


def steam_install_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None
    for hive, key_path in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "SteamPath")
        except OSError:
            continue
        path = Path(str(value))
        if path.is_dir():
            return path
    default = Path(r"C:\Program Files (x86)\Steam")
    return default if default.is_dir() else None


def steam_libraries() -> list[Path]:
    steam = steam_install_path()
    libraries: list[Path] = []
    if steam is not None:
        libraries.append(steam)
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for raw in parse_library_paths(text):
                path = Path(raw)
                if path not in libraries:
                    libraries.append(path)
    return libraries


def find_cs2_exe() -> Path | None:
    relative = Path("steamapps") / "common" / "Counter-Strike Global Offensive" / "game" / "bin" / "win64" / "cs2.exe"
    for library in steam_libraries():
        candidate = library / relative
        if candidate.is_file():
            return candidate
    return None


def unix_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def assert_console_safe(path: Path) -> None:
    text = str(path)
    if any(char in text for char in '"\r\n'):
        raise RuntimeError(f"Choose a folder without quotes or line breaks: {path}")
