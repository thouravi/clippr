"""Small Windows process helpers. clippr only kills processes it started."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

NO_WINDOW = 0x08000000


def _run(args: list[str]) -> str:
    kwargs = {}
    if __import__("os").name == "nt":
        kwargs["creationflags"] = NO_WINDOW
    completed = subprocess.run(args, capture_output=True, text=True, **kwargs)
    return (completed.stdout or "") + (completed.stderr or "")


def pids_named(image: str) -> set[int]:
    text = _run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"])
    found: set[int] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("INFO:"):
            continue
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            found.add(int(parts[1]))
    return found


def steam_running() -> bool:
    return bool(pids_named("steam.exe"))


def cs2_running() -> bool:
    return bool(pids_named("cs2.exe"))


def pid_alive(pid: int, image: str = "cs2.exe") -> bool:
    return pid in pids_named(image)


def kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        creationflags=NO_WINDOW if __import__("os").name == "nt" else 0,
    )


def write_active(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def wait_for_new_pid(image: str, before: set[int], timeout: float) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = pids_named(image)
        fresh = current - before
        if fresh:
            return sorted(fresh)[-1]
        time.sleep(0.5)
    return None


def wait_until_dead(pid: int, image: str, timeout: float, cancelled) -> bool:
    """Return True when the process exits. False on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancelled():
            return False
        if pid not in pids_named(image):
            return True
        time.sleep(1)
    return False
