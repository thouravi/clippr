"""JSON-line CLI used by the clippr desktop shell."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from clippr.detect import detect_highlights
from clippr.emit import fail, progress, result
from clippr.parse_demo import parse_demo
from clippr.paths import sandbox_dir, tools_dir
from clippr.process import cs2_running, steam_running
from clippr.record import generate_clip
from clippr.tools import find_ffmpeg, find_hlae, install_ffmpeg, install_hlae, write_ffmpeg_ini
from clippr.paths import find_cs2_exe


def _status() -> dict:
    demoparser = True
    try:
        import demoparser2  # noqa: F401
    except ImportError:
        demoparser = False
    hlae = find_hlae()
    ffmpeg = find_ffmpeg()
    cs2 = find_cs2_exe()
    return {
        "steam_running": steam_running(),
        "cs2_running": cs2_running(),
        "cs2_installed": cs2 is not None,
        "cs2_path": str(cs2) if cs2 else None,
        "hlae_installed": hlae is not None,
        "hlae_path": str(hlae) if hlae else None,
        "ffmpeg_installed": ffmpeg is not None,
        "ffmpeg_path": str(ffmpeg) if ffmpeg else None,
        "demoparser": demoparser,
        "python": sys.version.split()[0],
        "sandbox": str(sandbox_dir()),
        "tools_dir": str(tools_dir()),
    }


def _players(highlights) -> list[dict]:
    counts = Counter(item.steamid for item in highlights)
    players = []
    for steamid, count in counts.items():
        match = next(item for item in highlights if item.steamid == steamid)
        players.append(
            {
                "name": match.player,
                "steamid": steamid,
                "side": match.side,
                "highlights": count,
            }
        )
    players.sort(key=lambda item: (-item["highlights"], item["name"].lower()))
    return players


def _parse(path: str) -> None:
    demo = Path(path)
    if not demo.is_file():
        fail(f"Demo not found: {demo}")
    parsed = parse_demo(demo, lambda message, percent: progress("parsing", message, percent))
    highlights = detect_highlights(
        parsed["kills"],
        parsed["deaths"],
        parsed["rounds"],
        parsed["rosters"],
        parsed["slots"],
        parsed["tickrate"],
        parsed.get("crosshairs"),
    )
    result(
        {
            "demo_path": str(demo),
            "map_name": parsed["map_name"],
            "tickrate": parsed["tickrate"],
            "duration_seconds": parsed["duration_seconds"],
            "rounds": len(parsed["rounds"]),
            "highlights": [item.to_dict() for item in highlights],
            "players": _players(highlights),
        }
    )


def _ensure() -> None:
    def note(message: str, percent: float | None) -> None:
        progress("tools", message, percent)

    install_hlae(note)
    if find_ffmpeg() is None:
        install_ffmpeg(note)
    else:
        note("FFmpeg already installed", 85)
    hlae = find_hlae()
    ffmpeg = find_ffmpeg()
    if hlae is not None and ffmpeg is not None:
        write_ffmpeg_ini(hlae, ffmpeg)
    result(_status())


def _generate(job_path: str) -> None:
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    result(generate_clip(job))


def main(argv: list[str] | None = None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        sys.stderr.write("usage: python -m clippr status|ensure-tools|parse <demo>|generate <job.json>\n")
        raise SystemExit(0 if args else 1)
    command = args[0]
    try:
        if command == "status":
            result(_status())
        elif command == "ensure-tools":
            _ensure()
        elif command == "parse":
            if len(args) < 2:
                fail("parse needs a demo path")
            _parse(args[1])
        elif command == "generate":
            if len(args) < 2:
                fail("generate needs a job file")
            _generate(args[1])
        else:
            fail(f"Unknown command: {command}")
    except SystemExit:
        raise
    except Exception as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
