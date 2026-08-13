"""Check GitHub Releases for a newer build, and install it in place.

How the update is applied depends on how the app is running:

  installer   an installed Windows build (there's an uninstaller beside it) —
              download RepoGrowth-Setup.exe and run it silently; it replaces
              the files and relaunches once we exit
  portable    a single-file Windows or Linux build — rename the running
              program aside, move the new one into its place, relaunch
  manual      a macOS .app, where the bundle lives somewhere we shouldn't
              guess at — report the new version and open the releases page
  source      running from a checkout — nothing to replace; `git pull`

Only the checking and downloading happen here; every Tk call stays in gui.py.
Nothing in this module touches the network unless it's asked to.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse

from version import __version__

GITHUB_REPO = "jossdude/repo-growth"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
PROJECT_PAGE = f"https://github.com/{GITHUB_REPO}"

USER_AGENT = f"RepoGrowth/{__version__} (+{PROJECT_PAGE})"

# Release downloads redirect to GitHub's asset host, so both are allowed and
# nothing else is. A redirect anywhere else aborts the download rather than
# quietly fetching an executable from a stranger.
ALLOWED_HOSTS = ("github.com", "githubusercontent.com")

# A sanity ceiling, not a real limit — the builds are ~15 MB. It stops a
# malformed or hostile response from filling the disk.
MAX_ASSET_BYTES = 250 * 1024 * 1024

ASSET_INSTALLER = "RepoGrowth-Setup.exe"
ASSET_WINDOWS = "RepoGrowth-windows.exe"
ASSET_LINUX = "RepoGrowth-linux"


class UpdateError(RuntimeError):
    """Anything that stops an update from being checked or applied."""


# ---------------------------------------------------------------- versions

def parse_version(text):
    """``'v1.2.3'`` -> ``(1, 2, 3)``.

    Pre-release and build suffixes are dropped, and any part that isn't a
    number becomes 0 — a malformed tag should never read as newer than a
    real one.
    """
    core = (text or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in core.split(".")[:4]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate, current=None):
    """True when `candidate` is a later version than `current`."""
    return parse_version(candidate) > parse_version(
        __version__ if current is None else current
    )


# ------------------------------------------------------------- environment

def is_frozen():
    """True in a PyInstaller build, false when running from source."""
    return bool(getattr(sys, "frozen", False))


def app_path():
    """The program the user launched — the thing an update has to replace."""
    return os.path.abspath(sys.executable)


def update_mode():
    """Which of the four update strategies applies to this build."""
    if not is_frozen():
        return "source"
    if sys.platform == "win32":
        beside = os.path.dirname(app_path())
        if os.path.exists(os.path.join(beside, "unins000.exe")):
            return "installer"
        return "portable"
    if sys.platform.startswith("linux"):
        return "portable"
    return "manual"


def asset_name(mode=None):
    """The release asset that updates this build, or None if we can't self-update."""
    mode = update_mode() if mode is None else mode
    if mode == "installer":
        return ASSET_INSTALLER
    if mode == "portable":
        return ASSET_WINDOWS if sys.platform == "win32" else ASSET_LINUX
    return None


def can_self_update():
    return asset_name() is not None


# ------------------------------------------------------------------ network

def _host_allowed(url):
    parts = urlparse(url or "")
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _request(url):
    return urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )


def fetch_latest(timeout=15):
    """Ask GitHub about the newest release.

    Returns ``{"tag", "version", "notes", "page", "assets"}``. Raises
    UpdateError on anything that isn't a usable answer — callers decide
    whether that's worth showing the user (it isn't, for a silent check).
    """
    try:
        with urllib.request.urlopen(_request(API_LATEST), timeout=timeout) as resp:
            data = json.load(resp)
    except Exception as e:
        raise UpdateError(f"Couldn't reach GitHub to check for updates: {e}") from e

    tag = (data.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("GitHub returned a release with no version tag.")
    assets = {a["name"]: a for a in data.get("assets") or [] if a.get("name")}
    return {
        "tag": tag,
        "version": tag.lstrip("vV"),
        "notes": (data.get("body") or "").strip(),
        "page": data.get("html_url") or RELEASES_PAGE,
        "assets": assets,
    }


def download_asset(asset, progress=None, cancel_event=None, timeout=60):
    """Download one release asset to a temp file and return its path.

    `progress` is called with a 0..1 fraction. `cancel_event` is polled
    between chunks so the user can back out of a slow download.
    """
    url = asset.get("browser_download_url") or ""
    if not _host_allowed(url):
        raise UpdateError(f"Refusing to download from an unexpected address: {url}")

    expected = int(asset.get("size") or 0)
    if expected > MAX_ASSET_BYTES:
        raise UpdateError("The release asset is implausibly large; not downloading it.")

    suffix = os.path.splitext(asset.get("name") or "")[1]
    fd, tmp_path = tempfile.mkstemp(prefix="RepoGrowth-update-", suffix=suffix)
    read = 0
    try:
        with urllib.request.urlopen(_request(url), timeout=timeout) as resp:
            if not _host_allowed(resp.geturl()):
                raise UpdateError("The download redirected off GitHub; stopping.")
            total = int(resp.headers.get("Content-Length") or expected or 0)
            with os.fdopen(fd, "wb") as out:
                fd = None  # now owned by the file object
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise UpdateError("Download cancelled.")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    read += len(chunk)
                    if read > MAX_ASSET_BYTES:
                        raise UpdateError("The download exceeded its expected size.")
                    out.write(chunk)
                    if progress and total:
                        progress(min(read / total, 1.0))
        if expected and read != expected:
            raise UpdateError("The download was incomplete; not installing it.")
    except Exception:
        if fd is not None:
            os.close(fd)
        _quiet_remove(tmp_path)
        raise
    return tmp_path


# ------------------------------------------------------------------- apply

def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def apply_update(downloaded, mode=None):
    """Install `downloaded` over this build and start the new one.

    The caller must exit immediately afterwards: in installer mode the setup
    program is waiting for us to release our own files, and in portable mode
    the replacement is already running.
    """
    mode = update_mode() if mode is None else mode

    if mode == "installer":
        # /SILENT keeps the progress window but asks nothing; the installer's
        # [Run] entry relaunches the app when it finishes.
        subprocess.Popen(
            [downloaded, "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"],
            close_fds=True,
        )
        return mode

    if mode != "portable":
        raise UpdateError("This build can't replace itself; download it manually.")

    exe = app_path()
    old = exe + ".old"
    _quiet_remove(old)
    try:
        # A running program can't be overwritten, but it can be renamed out
        # of the way — on Windows and on Linux alike.
        os.replace(exe, old)
    except OSError as e:
        raise UpdateError(
            "Couldn't replace the running program — it may be in a folder that "
            f"needs administrator rights. Download the update manually. ({e})"
        ) from e
    try:
        shutil.move(downloaded, exe)
        if sys.platform != "win32":
            os.chmod(exe, 0o755)
    except Exception as e:
        os.replace(old, exe)  # put the working build back
        raise UpdateError(f"Couldn't install the update: {e}") from e

    subprocess.Popen([exe], close_fds=True)
    return mode


def cleanup_old_build():
    """Delete the build left behind by the last portable self-update."""
    if not is_frozen():
        return
    _quiet_remove(app_path() + ".old")
