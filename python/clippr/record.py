"""Launch CS2 through HLAE and record one highlight.

The game runs with -insecure and a sandboxed USRLOCALCSGO folder, so the
player's normal config is left alone and nothing is written into the CS2
install. HLAE's mirv_streams pipes frames straight into FFmpeg.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

from clippr.crosshair import crosshair_commands
from clippr.detect import clip_window
from clippr.emit import progress
from clippr.names import clip_stems
from clippr.pace import between_kill_cuts
from clippr.paths import (
    active_job_path,
    assert_console_safe,
    cancel_path,
    find_cs2_exe,
    sandbox_dir,
    unix_path,
    work_dir,
)
from clippr.process import kill_tree, pids_named, steam_running, write_active
from clippr.script import build_script
from clippr.tools import find_ffmpeg, find_hlae, find_hook_dll, write_ffmpeg_ini
from clippr.video import encode_pair, newest

NO_WINDOW = 0x08000000
HLAE_HINT = (
    "CS2 closed before a video was written. A CS2 update often breaks HLAE until "
    "advancedfx ships a new build. Download HLAE again from clippr, then retry. "
    "Releases: https://github.com/advancedfx/advancedfx/releases"
)


class RecordingCancelled(RuntimeError):
    pass


def _cancelled() -> bool:
    return cancel_path().exists()


def _guard() -> None:
    if _cancelled():
        raise RecordingCancelled("Cancelled.")


def _tail(path: Path, lines: int = 30) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


def _allocate(folder: Path, wide_name: str, tall_name: str) -> tuple[Path, Path]:
    wide = folder / wide_name
    tall = folder / tall_name
    index = 2
    while wide.exists() or tall.exists():
        wide = folder / wide_name.replace("_16x9.mp4", f"_{index}_16x9.mp4")
        tall = folder / tall_name.replace("_9x16.mp4", f"_{index}_9x16.mp4")
        index += 1
    return wide, tall


def _free_port(start: int = 2121) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return start


def _nudge_script(port: int, script: Path) -> None:
    """Best-effort load if the launch command did not run the script yet."""
    command = f'mirv_script_load "{unix_path(script)}"\n'.encode("utf-8")
    deadline = time.time() + 20
    while time.time() < deadline:
        _guard()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as sock:
                sock.sendall(command)
                return
        except OSError:
            time.sleep(0.4)


def _new_dumps(cs2_exe: Path, since: float) -> list[Path]:
    found = []
    for dump in cs2_exe.parent.glob("*.mdmp"):
        try:
            if dump.stat().st_mtime >= since - 1:
                found.append(dump)
        except OSError:
            continue
    return found


def generate_clip(job: dict) -> dict:
    if pids_named("cs2.exe"):
        raise RuntimeError(
            "Counter-Strike 2 is already running. Close it, then generate the clip. "
            "clippr starts its own -insecure HLAE session and will not attach to a game that is already open."
        )
    if not steam_running():
        raise RuntimeError("Steam is not running. Start Steam, then try again.")

    cs2_exe = find_cs2_exe()
    if cs2_exe is None:
        raise RuntimeError("Counter-Strike 2 was not found in a Steam library.")
    hlae_exe = find_hlae()
    ffmpeg_exe = find_ffmpeg()
    if hlae_exe is None or ffmpeg_exe is None:
        raise RuntimeError("HLAE or FFmpeg is missing. Download them from the clippr header, then try again.")
    hook = find_hook_dll(hlae_exe)
    if hook is None:
        raise RuntimeError(f"AfxHookSource2.dll is missing next to {hlae_exe}. Download HLAE again.")
    write_ffmpeg_ini(hlae_exe, ffmpeg_exe)

    from clippr.parse_demo import ensure_dem_file

    source = Path(job["demo_path"])
    playable = ensure_dem_file(source)
    assert_console_safe(playable)
    highlight = job["highlight"]
    tickrate = float(job.get("tickrate") or 64)
    lead_in = float(job.get("lead_in") if job.get("lead_in") is not None else 5)
    lead_out = float(job.get("lead_out") if job.get("lead_out") is not None else 3)
    fps = int(job.get("fps") or 60)
    width = int(job.get("width") or 1920)
    height = int(job.get("height") or 1080)
    output_dir = Path(job.get("output_dir") or source.parent / "clippr")
    output_dir.mkdir(parents=True, exist_ok=True)
    assert_console_safe(output_dir)

    seek, spec, start, end = clip_window(highlight, tickrate, lead_in, lead_out)
    cuts = between_kill_cuts(list(highlight.get("kill_ticks") or []), tickrate, start, end)
    wide_name, tall_name = clip_stems(str(highlight.get("player") or "player"), int(highlight["round"]), str(highlight["type"]))
    wide_path, tall_path = _allocate(output_dir, wide_name, tall_name)

    job_id = time.strftime("%Y%m%d-%H%M%S")
    folder = work_dir() / job_id
    folder.mkdir(parents=True, exist_ok=True)
    raw_video = folder / "video.mp4"
    script_path = folder / "clippr_record.js"
    slot = highlight.get("spec_slot")
    build_script(
        script_path,
        seek=seek,
        spec=spec,
        start=start,
        end=end,
        fps=fps,
        slot=int(slot) if slot else None,
        player=str(highlight.get("player") or ""),
        record_dir=folder,
        video_path=raw_video,
        crosshair=crosshair_commands(str(highlight.get("crosshair_code") or "")),
        cuts=cuts,
    )
    assert_console_safe(script_path)

    port = _free_port()
    game_args = (
        f"-steam -insecure -novid -console -sw -w {width} -h {height} "
        f"-afxDisableSteamStorage -afxFixNetCon -netconport {port} "
        f'+demo_ui_mode 0 +playdemo "{unix_path(playable)}" +mirv_script_load "{unix_path(script_path)}"'
    )
    launch = [
        str(hlae_exe),
        "-noGui",
        "-autoStart",
        "-noConfig",
        "-afxDisableSteamStorage",
        "-customLoader",
        "-hookDllPath",
        str(hook),
        "-programPath",
        str(cs2_exe),
        "-cmdLine",
        game_args,
    ]
    env = os.environ.copy()
    env["USRLOCALCSGO"] = str(sandbox_dir())
    log_path = folder / "hlae.log"
    progress("launch", "Starting CS2 through HLAE", 8)
    before = pids_named("cs2.exe")
    started = time.time()
    log_handle = log_path.open("w", encoding="utf-8")
    hlae_proc = subprocess.Popen(
        launch,
        cwd=str(hlae_exe.parent),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    cs2_pid = None
    try:
        write_active(active_job_path(), {"python": os.getpid(), "hlae": hlae_proc.pid})
        deadline = time.time() + 90
        while time.time() < deadline:
            _guard()
            fresh = pids_named("cs2.exe") - before
            if fresh:
                cs2_pid = sorted(fresh)[-1]
                break
            code = hlae_proc.poll()
            if code not in (None, 0):
                raise RuntimeError(f"HLAE exited with code {code}.\n{_tail(log_path)}\n{HLAE_HINT}")
            time.sleep(0.5)
        if cs2_pid is None:
            raise RuntimeError(f"CS2 did not start.\n{_tail(log_path)}\n{HLAE_HINT}")
        write_active(active_job_path(), {"python": os.getpid(), "hlae": hlae_proc.pid, "cs2": cs2_pid})
        progress("launch", "CS2 is up. Loading the demo and the record script.", 18)
        try:
            _nudge_script(port, script_path)
        except RecordingCancelled:
            raise
        except Exception:
            pass

        clip_seconds = max(1.0, (end - start) / max(tickrate, 1))
        timeout = 240 + clip_seconds * 8
        record_deadline = time.time() + timeout
        next_note = 0.0
        while time.time() < record_deadline:
            _guard()
            if cs2_pid not in pids_named("cs2.exe"):
                break
            now = time.time()
            if now >= next_note:
                progress("recording", "Recording the highlight in CS2", None)
                next_note = now + 3
            time.sleep(1)
        else:
            raise RuntimeError(
                f"Recording did not finish within {int(timeout)} seconds. CS2 was closed."
            )
        _guard()
        dumps = _new_dumps(cs2_exe, started)
        video = newest(list(folder.rglob("*.mp4")))
        if video is None:
            extra = f"\nCrash dump: {dumps[-1]}" if dumps else ""
            raise RuntimeError(f"No video was captured.\n{_tail(log_path)}{extra}\n{HLAE_HINT}")

        progress("encoding", "Encoding the 16:9 and 9:16 clips", 70)
        audio = newest(list(folder.rglob("*.wav")))
        encode_pair(ffmpeg_exe, video, audio, wide_path, tall_path)
        progress("encoding", "Clips ready", 100)
        try:
            os.startfile(output_dir)  # type: ignore[attr-defined]
        except OSError:
            pass
        return {
            "output_dir": str(output_dir),
            "wide": str(wide_path),
            "vertical": str(tall_path),
            "wide_name": wide_path.name,
            "vertical_name": tall_path.name,
            "audio": audio is not None,
        }
    except RecordingCancelled:
        raise RuntimeError("Cancelled.")
    finally:
        log_handle.close()
        if cs2_pid and cs2_pid in pids_named("cs2.exe"):
            kill_tree(cs2_pid)
        if hlae_proc.poll() is None:
            kill_tree(hlae_proc.pid)
        active_job_path().unlink(missing_ok=True)
