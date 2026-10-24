"""Locate HLAE and FFmpeg, and download them into ~/.clippr/tools."""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from clippr.paths import tools_dir

HLAE_RELEASES = "https://api.github.com/repos/advancedfx/advancedfx/releases"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
USER_AGENT = "clippr"


def hlae_version_key(tag: str) -> tuple[int, ...]:
    """Numeric pieces of a tag, so v2.192.8 sorts above the older v2.185.4 re-release."""
    return tuple(int(part) for part in re.findall(r"\d+", tag or ""))


def choose_hlae_asset(releases: list) -> tuple[str, dict]:
    """Pick the highest stable HLAE zip.

    GitHub lists releases by publish date. An old build re-released later
    (v2.185.4, for CS2 1.40.8.8) would otherwise beat the current hook.
    """
    best_key: tuple[int, ...] | None = None
    best: tuple[str, dict] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        if re.search(r"old re-release", str(release.get("body") or ""), re.IGNORECASE):
            continue
        asset = _hlae_zip(release)
        if asset is None:
            continue
        tag = str(release.get("tag_name") or "")
        key = hlae_version_key(tag)
        if best_key is not None and key <= best_key:
            continue
        best_key = key
        best = (
            str(asset["browser_download_url"]),
            {
                "tag": tag,
                "published_at": release.get("published_at") or "",
                "name": str(asset.get("name") or ""),
            },
        )
    if best is None:
        raise RuntimeError("Could not find an HLAE release zip on GitHub.")
    return best


def find_hlae() -> Path | None:
    override = _env_path("CLIPPR_HLAE")
    if override is not None:
        return override if override.name.lower() == "hlae.exe" else _first(override, "HLAE.exe")
    root = tools_dir() / "hlae"
    return _first(root, "HLAE.exe")


def find_ffmpeg() -> Path | None:
    override = _env_path("CLIPPR_FFMPEG")
    if override is not None:
        return override if override.name.lower() == "ffmpeg.exe" else _first(override, "ffmpeg.exe")
    bundled = tools_dir() / "ffmpeg" / "bin" / "ffmpeg.exe"
    if bundled.is_file():
        return bundled
    on_path = shutil.which("ffmpeg")
    return Path(on_path) if on_path else None


def find_hook_dll(hlae_exe: Path) -> Path | None:
    candidate = hlae_exe.parent / "x64" / "AfxHookSource2.dll"
    if candidate.is_file():
        return candidate
    found = list(hlae_exe.parent.glob("**/AfxHookSource2.dll"))
    return found[0] if found else None


def write_ffmpeg_ini(hlae_exe: Path, ffmpeg_exe: Path) -> None:
    """HLAE reads <HLAE>/ffmpeg/ffmpeg.ini for the encoder binary."""
    folder = hlae_exe.parent / "ffmpeg"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ffmpeg.ini").write_text(f"[Ffmpeg]\nPath={ffmpeg_exe}\n", encoding="utf-8")


def install_hlae(progress=None) -> Path:
    current = find_hlae()
    if current is not None and not _is_managed_hlae(current):
        if progress:
            progress("HLAE already installed", 40)
        return current
    if progress:
        progress("Asking GitHub for the latest HLAE release", 5)
    releases = _get_json(f"{HLAE_RELEASES}?per_page=100")
    if not isinstance(releases, list):
        raise RuntimeError("Unexpected response from the HLAE releases API.")
    url, info = choose_hlae_asset(releases)
    if current is not None:
        installed = _installed_tag(current)
        chosen = str(info.get("tag") or "")
        if hlae_version_key(installed) >= hlae_version_key(chosen):
            if progress:
                progress(f"HLAE {installed or chosen} already installed", 40)
            return current
        if progress:
            progress(f"Replacing HLAE {installed or 'install'} with {chosen}", 8)
    archive = tools_dir() / "hlae.zip"
    _download(url, archive, progress, "Downloading HLAE")
    dest = tools_dir() / "hlae"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)
    archive.unlink(missing_ok=True)
    exe = _first(dest, "HLAE.exe")
    if exe is None:
        raise RuntimeError(f"HLAE.exe was not in the downloaded archive ({dest}).")
    (exe.parent / "install-info.json").write_text(json.dumps(info), encoding="utf-8")
    if progress:
        progress(f"HLAE {info.get('tag') or ''} ready", 100)
    return exe


def install_ffmpeg(progress=None) -> Path:
    archive = tools_dir() / "ffmpeg.zip"
    _download(FFMPEG_URL, archive, progress, "Downloading FFmpeg")
    dest = tools_dir() / "ffmpeg"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)
    archive.unlink(missing_ok=True)
    found = list(dest.glob("**/bin/ffmpeg.exe"))
    if not found:
        raise RuntimeError(f"ffmpeg.exe was not in the downloaded archive ({dest}).")
    exe = found[0]
    normalized = dest / "bin" / "ffmpeg.exe"
    if exe != normalized:
        normalized.parent.mkdir(parents=True, exist_ok=True)
        for sibling in exe.parent.iterdir():
            target = normalized.parent / sibling.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(sibling), str(target))
        release_root = exe.parent.parent
        if release_root != dest:
            shutil.rmtree(release_root, ignore_errors=True)
    if progress:
        progress("FFmpeg ready", 100)
    return normalized


def _env_path(name: str) -> Path | None:
    import os

    raw = os.environ.get(name)
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def _hlae_zip(release: dict) -> dict | None:
    zips = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        lowered = name.lower()
        if not lowered.endswith(".zip") or not asset.get("browser_download_url"):
            continue
        if "source" in lowered or lowered.endswith(".pdb.zip"):
            continue
        zips.append(asset)
    preferred = [asset for asset in zips if str(asset.get("name") or "").lower().startswith("hlae")]
    return (preferred or zips)[0] if zips else None


def _is_managed_hlae(exe: Path) -> bool:
    root = (tools_dir() / "hlae").resolve()
    try:
        exe.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _installed_tag(exe: Path) -> str:
    path = exe.parent / "install-info.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("tag") or "")


def _first(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    direct = root / name
    if direct.is_file():
        return direct
    matches = [item for item in root.glob(f"**/{name}") if item.is_file()]
    return matches[0] if matches else None


def _get_json(url: str):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, dest: Path, progress, label: str) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=120) as response:
        total = int(response.headers.get("Content-Length") or 0)
        dest.parent.mkdir(parents=True, exist_ok=True)
        received = 0
        with dest.open("wb") as handle:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if progress and total:
                    progress(label, min(99, received * 100 / total))
                elif progress and received % (8 << 20) < (1 << 20):
                    progress(f"{label} ({received // (1 << 20)} MB)", None)
