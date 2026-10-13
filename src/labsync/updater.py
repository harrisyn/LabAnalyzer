"""Update check against GitHub releases, with SHA-256 verification of downloaded installers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

log = logging.getLogger("labsync.updater")

RELEASES_API = "https://api.github.com/repos/harrisyn/LabAnalyzer/releases/latest"


@dataclass
class UpdateInfo:
    version: str
    page_url: str
    asset_name: str
    asset_url: str
    checksum_url: str
    notes: str


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"LabSync/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
        return resp.read()


def _asset_suffix() -> str:
    if sys.platform == "win32":
        return ".exe"
    if sys.platform == "darwin":
        return ".dmg"
    return ".tar.gz"


def check(current: str = __version__) -> UpdateInfo | None:
    data = json.loads(_get(RELEASES_API))
    tag = str(data.get("tag_name", ""))
    if not tag or data.get("draft") or data.get("prerelease") or not is_newer(tag, current):
        return None
    assets = data.get("assets", [])
    suffix = _asset_suffix()
    asset = next((a for a in assets if a.get("name", "").lower().endswith(suffix)), None)
    sums = next((a for a in assets if a.get("name", "").upper().startswith("SHA256SUMS")), None)
    return UpdateInfo(
        version=tag.lstrip("v"),
        page_url=data.get("html_url", ""),
        asset_name=asset["name"] if asset else "",
        asset_url=asset["browser_download_url"] if asset else "",
        checksum_url=sums["browser_download_url"] if sums else "",
        notes=str(data.get("body", ""))[:2000],
    )


def download(info: UpdateInfo, folder: Path, progress: Callable[[int, int], None] | None = None) -> Path:
    if not info.asset_url:
        raise RuntimeError("this release has no installer for this platform")
    expected = ""
    if info.checksum_url:
        for line in _get(info.checksum_url).decode().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == info.asset_name:
                expected = parts[0].lower()
    if not expected:
        raise RuntimeError("the release does not publish a SHA-256 checksum for the installer; download it manually")
    target = folder / info.asset_name
    tmp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(info.asset_url, headers={"User-Agent": f"LabSync/{__version__}"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:  # noqa: S310
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(256 * 1024):
            fh.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if digest.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("downloaded installer failed checksum verification and was deleted")
    os.replace(tmp, target)
    return target


def launch_installer(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen([str(path)], close_fds=True)  # noqa: S603 - verified installer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])  # noqa: S603,S607
