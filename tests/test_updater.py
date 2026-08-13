"""Tests for the in-app updater.

Nothing here touches the network. What's covered is the logic that decides
*whether* to update and *what to fetch*: version comparison (a bad tag must
never look newer than a real one), the host allow-list that guards the
download, and the per-platform choice of update strategy and asset.
"""

import os
import sys

import pytest

import updater


# ----------------------------------------------------------- version parsing

@pytest.mark.parametrize("text,expected", [
    ("v1.2.3",       (1, 2, 3)),
    ("1.2.3",        (1, 2, 3)),
    ("V0.1.5",       (0, 1, 5)),
    ("0.2",          (0, 2, 0)),
    ("3",            (3, 0, 0)),
    ("v1.2.3-beta1", (1, 2, 3)),
    ("v1.2.3+build", (1, 2, 3)),
    ("  v1.2.3  ",   (1, 2, 3)),
    ("v1.2.3.4",     (1, 2, 3, 4)),
])
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", None, "latest", "vNext", "not-a-version"])
def test_unparseable_versions_are_zero(text):
    """A junk tag must sort below every real release, not above it."""
    assert updater.parse_version(text) == (0, 0, 0)
    assert not updater.is_newer(text, "0.0.1")


def test_ordering_is_numeric_not_lexical():
    assert updater.parse_version("v0.10.0") > updater.parse_version("v0.9.0")
    assert updater.is_newer("0.10.0", "0.9.0")


@pytest.mark.parametrize("candidate,current,expected", [
    ("0.2.0", "0.1.9", True),
    ("1.0.0", "0.9.9", True),
    ("0.1.0", "0.2.0", False),
    ("0.2.0", "0.2.0", False),   # same version is not an update
    ("v0.2.0", "0.2.0", False),  # the v prefix is cosmetic
])
def test_is_newer(candidate, current, expected):
    assert updater.is_newer(candidate, current) is expected


def test_is_newer_defaults_to_the_running_version():
    assert updater.is_newer(updater.__version__) is False


# -------------------------------------------------------------- download host

@pytest.mark.parametrize("url", [
    "https://github.com/jossdude/repo-growth/releases/download/v1/RepoGrowth-windows.exe",
    "https://objects.githubusercontent.com/some/blob",
    "https://api.github.com/repos/x/y/releases/latest",
])
def test_github_urls_are_allowed(url):
    assert updater._host_allowed(url)


@pytest.mark.parametrize("url", [
    "http://github.com/jossdude/repo-growth/x.exe",   # not https
    "https://github.com.evil.test/x.exe",             # suffix, not the domain
    "https://notgithub.com/x.exe",
    "https://evil.test/x.exe",
    "file:///C:/x.exe",
    "",
    None,
])
def test_non_github_urls_are_refused(url):
    assert not updater._host_allowed(url)


def test_download_refuses_a_disallowed_host(tmp_path):
    asset = {"name": "RepoGrowth-windows.exe", "size": 10,
             "browser_download_url": "https://evil.test/RepoGrowth-windows.exe"}
    with pytest.raises(updater.UpdateError):
        updater.download_asset(asset)


def test_download_refuses_an_implausibly_large_asset():
    asset = {"name": "RepoGrowth-windows.exe",
             "size": updater.MAX_ASSET_BYTES + 1,
             "browser_download_url": "https://github.com/x/y/releases/download/v1/z.exe"}
    with pytest.raises(updater.UpdateError):
        updater.download_asset(asset)


# ---------------------------------------------------------------- update mode

def test_source_checkout_has_no_update_strategy(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    assert updater.update_mode() == "source"
    assert updater.asset_name() is None
    assert not updater.can_self_update()


def test_windows_build_beside_an_uninstaller_uses_the_installer(monkeypatch, tmp_path):
    exe = tmp_path / "RepoGrowth.exe"
    exe.write_text("stub")
    (tmp_path / "unins000.exe").write_text("stub")
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "app_path", lambda: str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.update_mode() == "installer"
    assert updater.asset_name() == updater.ASSET_INSTALLER


def test_windows_build_without_an_uninstaller_is_portable(monkeypatch, tmp_path):
    exe = tmp_path / "RepoGrowth.exe"
    exe.write_text("stub")
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "app_path", lambda: str(exe))
    monkeypatch.setattr(sys, "platform", "win32")
    assert updater.update_mode() == "portable"
    assert updater.asset_name() == updater.ASSET_WINDOWS


def test_linux_build_is_portable(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "app_path", lambda: str(tmp_path / "RepoGrowth"))
    monkeypatch.setattr(sys, "platform", "linux")
    assert updater.update_mode() == "portable"
    assert updater.asset_name() == updater.ASSET_LINUX


def test_macos_bundle_updates_manually(monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert updater.update_mode() == "manual"
    assert updater.asset_name() is None


# --------------------------------------------------------------- applying it

def test_portable_update_swaps_the_program_and_relaunches(monkeypatch, tmp_path):
    exe = tmp_path / "RepoGrowth.exe"
    exe.write_text("old build")
    new = tmp_path / "downloaded.exe"
    new.write_text("new build")

    launched = []
    monkeypatch.setattr(updater, "app_path", lambda: str(exe))
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))

    assert updater.apply_update(str(new), "portable") == "portable"
    assert exe.read_text() == "new build"
    assert os.path.exists(str(exe) + ".old")          # previous build kept aside
    assert launched == [[str(exe)]]                   # and the new one started


def test_a_failed_swap_puts_the_working_build_back(monkeypatch, tmp_path):
    exe = tmp_path / "RepoGrowth.exe"
    exe.write_text("old build")

    monkeypatch.setattr(updater, "app_path", lambda: str(exe))
    monkeypatch.setattr(updater.shutil, "move",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(updater.UpdateError):
        updater.apply_update(str(tmp_path / "downloaded.exe"), "portable")
    assert exe.read_text() == "old build"


def test_installer_update_runs_setup_silently(monkeypatch, tmp_path):
    setup = tmp_path / "RepoGrowth-Setup.exe"
    setup.write_text("stub")
    launched = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))

    assert updater.apply_update(str(setup), "installer") == "installer"
    assert launched[0][0] == str(setup)
    assert "/SILENT" in launched[0]


def test_manual_mode_cannot_apply_an_update(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.apply_update(str(tmp_path / "x"), "manual")


def test_cleanup_removes_the_previous_build(monkeypatch, tmp_path):
    exe = tmp_path / "RepoGrowth.exe"
    old = tmp_path / "RepoGrowth.exe.old"
    old.write_text("previous")
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "app_path", lambda: str(exe))

    updater.cleanup_old_build()
    assert not old.exists()


def test_cleanup_is_a_no_op_from_source(monkeypatch, tmp_path):
    old = tmp_path / "RepoGrowth.exe.old"
    old.write_text("previous")
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    monkeypatch.setattr(updater, "app_path", lambda: str(tmp_path / "RepoGrowth.exe"))

    updater.cleanup_old_build()
    assert old.exists()
