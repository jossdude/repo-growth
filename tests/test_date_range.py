"""Tests for the optional date range: parsing, presets, filtering the
history down to a window, and the CLI flags that expose it.
"""

import os
from datetime import date, datetime, timedelta

import pytest

git = pytest.importorskip("git")

import main as main_module
from repo_growth import (
    DATE_PRESETS,
    NoCommitsInRange,
    analyse_repo,
    default_output_path,
    in_date_range,
    parse_date,
    preset_range,
    range_label,
    range_slug,
    resolve_range,
)


# ------------------------------------------------------------------ parsing


def test_parse_date_accepts_iso_and_blanks():
    assert parse_date("2026-03-04") == date(2026, 3, 4)
    assert parse_date("  2026-03-04  ") == date(2026, 3, 4)
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date(date(2026, 3, 4)) == date(2026, 3, 4)


@pytest.mark.parametrize("bad", ["04/03/2026", "March 4", "2026-13-01", "yesterday"])
def test_parse_date_rejects_other_formats(bad):
    with pytest.raises(ValueError):
        parse_date(bad)


def test_preset_ranges_end_today_and_step_back():
    today = date(2026, 6, 15)
    for name, days in DATE_PRESETS.items():
        since, until = preset_range(name, today)
        assert until == today
        assert since == today - timedelta(days=days)


def test_preset_name_is_case_insensitive():
    assert preset_range("WEEK", date(2026, 6, 15)) == preset_range("week", date(2026, 6, 15))


def test_unknown_preset_rejected():
    with pytest.raises(ValueError):
        preset_range("fortnight")


def test_resolve_range_prefers_the_preset():
    # A preset overrides explicit dates, so the GUI/CLI can offer both without
    # having to clear one first.
    since, until = resolve_range("2000-01-01", "2000-12-31", "day", today=date(2026, 6, 15))
    assert (since, until) == (date(2026, 6, 14), date(2026, 6, 15))


def test_resolve_range_rejects_backwards_dates():
    with pytest.raises(ValueError):
        resolve_range("2026-06-15", "2026-01-01")


def test_resolve_range_allows_open_ends():
    assert resolve_range("2026-01-01", None) == (date(2026, 1, 1), None)
    assert resolve_range(None, "2026-01-01") == (None, date(2026, 1, 1))
    assert resolve_range(None, None) == (None, None)


def test_bounds_are_inclusive_whole_days():
    day = date(2026, 6, 15)
    noon = datetime(2026, 6, 15, 12).timestamp()
    late = datetime(2026, 6, 15, 23, 59).timestamp()
    early = datetime(2026, 6, 15, 0, 1).timestamp()
    for ts in (early, noon, late):
        assert in_date_range(ts, day, day)
    assert not in_date_range(datetime(2026, 6, 14, 23, 59).timestamp(), day, day)
    assert not in_date_range(datetime(2026, 6, 16, 0, 1).timestamp(), day, day)


def test_unbounded_range_accepts_everything():
    assert in_date_range(datetime(1999, 1, 1).timestamp(), None, None)


def test_labels_and_slugs_describe_the_window():
    a, b = date(2026, 1, 2), date(2026, 3, 4)
    assert range_label(a, b) == "2026-01-02 → 2026-03-04"
    assert range_label(a, None) == "since 2026-01-02"
    assert range_label(None, b) == "up to 2026-03-04"
    assert range_label(None, None) == ""
    assert range_slug(None, None) == ""
    assert range_slug(a, b) == "20260102_to_20260304"


def test_ascii_label_for_consoles_that_cannot_encode_the_arrow():
    # Progress lines and error text can land on a cp1252 Windows console;
    # anything outside that codepage raises instead of printing.
    label = range_label(date(2026, 1, 2), date(2026, 3, 4), arrow="->")
    assert label == "2026-01-02 -> 2026-03-04"
    label.encode("cp1252")


def test_output_path_keeps_ranges_apart():
    plain = default_output_path("some/repo")
    ranged = default_output_path("some/repo", range_slug(date(2026, 1, 2), date(2026, 3, 4)))
    assert plain != ranged
    assert ranged.endswith("_20260102_to_20260304.html")


# ------------------------------------------------------------------ analysis


def _commit_on(repo, path, content, message, when):
    """Commit with both author and committer dates pinned to `when`."""
    full = os.path.join(repo.working_tree_dir, path)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    repo.index.add([path])
    stamp = when.strftime("%Y-%m-%dT12:00:00")
    return repo.index.commit(message, author_date=stamp, commit_date=stamp)


@pytest.fixture(scope="module")
def dated_repo(tmp_path_factory):
    """Three commits a month apart: January, February and March 2026."""
    root = tmp_path_factory.mktemp("dated_repo")
    repo = git.Repo.init(root, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")

    _commit_on(repo, "a.py", "line\n" * 10, "january",  date(2026, 1, 10))
    _commit_on(repo, "a.py", "line\n" * 20, "february", date(2026, 2, 10))
    _commit_on(repo, "a.py", "line\n" * 30, "march",    date(2026, 3, 10))
    yield repo
    repo.close()


def _analyse(repo, **kwargs):
    return analyse_repo(repo.working_tree_dir, progress=lambda _m: None, **kwargs)


def test_no_range_charts_the_whole_history(dated_repo):
    analysis = _analyse(dated_repo)
    assert analysis["total_commits"] == 3
    assert analysis["date_range"] == ""
    assert analysis["stats"]["first_date"] == "2026-01-10"


def test_range_narrows_the_history(dated_repo):
    analysis = _analyse(dated_repo, since="2026-02-01", until="2026-03-31")
    assert analysis["total_commits"] == 2
    assert [d["date"] for d in analysis["data"]] == ["2026-02-10", "2026-03-10"]
    assert analysis["date_range"] == "2026-02-01 → 2026-03-31"


def test_stats_describe_the_window_only(dated_repo):
    # Growth inside the window, not since the repo began: 20 lines → 30.
    analysis = _analyse(dated_repo, since="2026-02-01")
    stats = analysis["stats"]
    assert stats["lines_start"] == 20
    assert stats["lines_now"] == 30
    assert stats["net_change"] == 10
    assert stats["first_date"] == "2026-02-10"


def test_open_ended_bounds(dated_repo):
    assert _analyse(dated_repo, until="2026-01-31")["total_commits"] == 1
    assert _analyse(dated_repo, since="2026-02-01")["total_commits"] == 2


def test_empty_range_is_reported_not_silently_empty(dated_repo):
    with pytest.raises(NoCommitsInRange) as excinfo:
        _analyse(dated_repo, since="2030-01-01", until="2030-12-31")
    str(excinfo.value).encode("cp1252")  # printable on a legacy console


def test_range_progress_survives_a_legacy_console(dated_repo):
    lines = []
    analyse_repo(dated_repo.working_tree_dir, progress=lines.append,
                 since="2026-02-01", until="2026-03-31")
    for line in lines:
        line.encode("cp1252")
    assert any("2026-02-01 -> 2026-03-31" in line for line in lines)


def test_backwards_range_rejected_before_any_work(dated_repo):
    with pytest.raises(ValueError):
        _analyse(dated_repo, since="2026-03-01", until="2026-01-01")


def test_range_reaches_the_rendered_report(dated_repo, tmp_path):
    out = tmp_path / "chart.html"
    rc = main_module.run_cli([
        dated_repo.working_tree_dir, "--detail", "Rough", "--no-animated",
        "--since", "2026-02-01", "--until", "2026-03-31", "--output", str(out),
    ])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "2 commits &nbsp;·&nbsp; 2026-02-01 → 2026-03-31</p>" in html
    assert "{{DATE_RANGE}}" not in html


def test_report_omits_the_clause_when_unbounded(dated_repo, tmp_path):
    out = tmp_path / "all.html"
    assert main_module.run_cli([
        dated_repo.working_tree_dir, "--detail", "Rough", "--no-animated",
        "--output", str(out),
    ]) == 0
    html = out.read_text(encoding="utf-8")
    assert "3 commits</p>" in html   # header ends at the commit count
    assert "{{DATE_RANGE}}" not in html


def test_cli_last_flag(dated_repo, tmp_path):
    # --last week ends today, so a repo whose newest commit is 2026-03-10 has
    # nothing in the window — the point is that the flag resolves and filters.
    out = tmp_path / "recent.html"
    with pytest.raises(NoCommitsInRange):
        main_module.run_cli([
            dated_repo.working_tree_dir, "--detail", "Rough", "--no-animated",
            "--last", "week", "--output", str(out),
        ])


def test_cli_rejects_bad_dates(dated_repo):
    with pytest.raises(SystemExit):
        main_module.run_cli([dated_repo.working_tree_dir, "--since", "last tuesday"])
    with pytest.raises(SystemExit):
        main_module.run_cli([dated_repo.working_tree_dir, "--last", "fortnight"])
