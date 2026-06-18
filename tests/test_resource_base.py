"""Tests for frozen-aware resource resolution in repo_growth.

The standalone PyInstaller builds unpack bundled data (templates/ and its
fonts/) into a temp dir exposed as sys._MEIPASS. _resource_base() must point
there when frozen, and the derived data dirs must hang off it so both the
templates and the embedded fonts are found.
"""

import importlib
import os
import sys

import repo_growth


def test_resource_base_falls_back_to_script_dir_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = os.path.dirname(os.path.abspath(repo_growth.__file__))
    assert repo_growth._resource_base() == expected


def test_resource_base_uses_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert repo_growth._resource_base() == str(tmp_path)


def test_data_dirs_rooted_at_meipass_when_frozen(monkeypatch, tmp_path):
    # Reload the module with sys._MEIPASS set so the module-level BASE_DIR /
    # TEMPLATES_DIR / FONTS_DIR are recomputed as they would be in a frozen
    # build, then restore the unfrozen module for other tests.
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    importlib.reload(repo_growth)
    try:
        assert repo_growth.BASE_DIR == str(tmp_path)
        assert repo_growth.TEMPLATES_DIR == os.path.join(str(tmp_path), "templates")
        assert repo_growth.FONTS_DIR == os.path.join(str(tmp_path), "templates", "fonts")
    finally:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        importlib.reload(repo_growth)
