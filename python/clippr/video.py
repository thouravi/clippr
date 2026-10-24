"""Turn the HLAE capture into 16:9 and center-framed 9:16 files."""

from __future__ import annotations

import subprocess
from pathlib import Path

NO_WINDOW = 0x08000000

# First-person view keeps the crosshair in the middle of the frame, so the
# vertical cut is the center 9:16 of the widescreen capture.
VERTICAL_FILTER = "crop=trunc(ih*9/16/2)*2:trunc(ih/2)*2,scale=1080:1920:flags=lanczos"


def run_ffmpeg(ffmpeg: Path, args: list[str]) -> None:
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args]
    kwargs = {"creationflags": NO_WINDOW} if __import__("os").name == "nt" else {}
    completed = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise RuntimeError(detail[-2000:])


def encode_pair(
    ffmpeg: Path,
    source_video: Path,
    source_audio: Path | None,
    wide_path: Path,
    vertical_path: Path,
) -> None:
    wide_path.parent.mkdir(parents=True, exist_ok=True)
    if source_audio is not None and source_audio.is_file():
        run_ffmpeg(
            ffmpeg,
            [
                "-i",
                str(source_video),
                "-i",
                str(source_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(wide_path),
            ],
        )
    else:
        run_ffmpeg(
            ffmpeg,
            ["-i", str(source_video), "-c", "copy", "-movflags", "+faststart", str(wide_path)],
        )

    vertical_args = [
        "-i",
        str(wide_path),
        "-vf",
        VERTICAL_FILTER,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-movflags",
        "+faststart",
    ]
    try:
        run_ffmpeg(ffmpeg, [*vertical_args, "-c:a", "aac", "-b:a", "192k", str(vertical_path)])
    except RuntimeError:
        run_ffmpeg(ffmpeg, [*vertical_args, "-an", str(vertical_path)])


def newest(paths: list[Path]) -> Path | None:
    files = [path for path in paths if path.is_file() and path.stat().st_size > 0]
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)
