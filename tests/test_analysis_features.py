"""Tests for analysis robustness features on a small synthetic repository:
batched churn, cancellation, survival rate bounds, branch listing, commit
counting, cloud-placeholder detection, and the headless CLI.
"""

import os
import threading

import pytest

git = pytest.importorskip("git")

import main as main_module
import repo_growth
from repo_growth import (
    AnalysisCancelled,
    analyse_repo,
    cloud_placeholder_count,
    count_commits,
    get_churn,
    list_branches,
)


def _commit_file(repo, path, content, message):
    full = os.path.join(repo.working_tree_dir, path)
    os.makedirs(os.path.dirname(full) or repo.working_tree_dir, exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    repo.index.add([path])
    return repo.index.commit(message)


@pytest.fixture(scope="module")
def sample_repo(tmp_path_factory):
    """A tiny repo: growth, a removal, a binary file, and a second branch."""
    root = tmp_path_factory.mktemp("sample_repo")
    repo = git.Repo.init(root, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")

    _commit_file(repo, "a.py", "line\n" * 10, "add a.py")
    _commit_file(repo, "b.py", "line\n" * 20, "add b.py")
    _commit_file(repo, "a.py", "line\n" * 3, "shrink a.py")  # removal
    bin_path = os.path.join(root, "blob.bin")
    with open(bin_path, "wb") as f:
        f.write(b"\x00\x01\x02" * 100)
    repo.index.add(["blob.bin"])
    repo.index.commit("add binary")
    # A rename: porcelain `git diff` detects it (tiny churn), so the batched
    # diff-tree path must too — without -M it counts a full delete + add.
    repo.git.mv("b.py", "renamed.py")
    repo.index.commit("rename b.py")
    repo.create_head("feature")
    yield repo
    repo.close()


def _repo_path(repo):
    return repo.working_tree_dir


def test_churn_batched_matches_per_pair(sample_repo):
    """The single-process diff-tree churn must equal the per-pair fallback."""
    commits = list(sample_repo.iter_commits("main"))
    commits.reverse()
    fast = get_churn(sample_repo, commits, progress=lambda m: None)
    slow = repo_growth._churn_per_pair(sample_repo, commits,
                                       lambda m: None, None, None)
    assert fast == slow
    assert len(fast) == len(commits) - 1
    # The shrink commit must register removals.
    assert any(c["removed"] > 0 for c in fast)
    assert any(c["added"] > 0 for c in fast)


def test_churn_reports_pairs_in_order(sample_repo):
    commits = list(sample_repo.iter_commits("main"))
    commits.reverse()
    seen = []
    get_churn(sample_repo, commits, progress=lambda m: None,
              on_pair=lambda i, n: seen.append((i, n)))
    total = len(commits) - 1
    assert seen == [(i, total) for i in range(1, total + 1)]


def test_analyse_repo_end_to_end(sample_repo):
    analysis = analyse_repo(_repo_path(sample_repo), progress=lambda m: None)
    stats = analysis["stats"]
    assert analysis["total_commits"] == 5
    assert len(analysis["data"]) == 5  # below target -> every commit
    # Binary file counts as a file but contributes no lines.
    assert analysis["data"][-1]["files"] == 3
    assert 0 < stats["survival_rate"] <= 100
    assert stats["lines_now"] == 23


def test_survival_rate_bounded_when_repo_only_grows(sample_repo):
    # A history that keeps its initial code used to report survival > 100%
    # because the first commit's lines were missing from the denominator.
    analysis = analyse_repo(_repo_path(sample_repo), branch="feature",
                            progress=lambda m: None)
    assert analysis["stats"]["survival_rate"] <= 100


def test_cancel_raises(sample_repo):
    event = threading.Event()
    event.set()
    with pytest.raises(AnalysisCancelled):
        analyse_repo(_repo_path(sample_repo), progress=lambda m: None,
                     cancel_event=event)


def test_count_commits(sample_repo):
    assert count_commits(_repo_path(sample_repo)) == 5
    assert count_commits("nonexistent-path") is None


def test_list_branches_current_first(sample_repo):
    branches = list_branches(_repo_path(sample_repo))
    assert set(branches) == {"main", "feature"}
    assert branches[0] == sample_repo.active_branch.name
    assert list_branches("nonexistent-path") == []


def test_cloud_placeholder_count_zero_on_local_repo(sample_repo):
    # Freshly created files are fully hydrated, so the count must be 0 —
    # and the scan must not blow up on missing paths either.
    assert cloud_placeholder_count(_repo_path(sample_repo)) == 0
    assert cloud_placeholder_count("nonexistent-path") == 0


def test_cli_generates_output(sample_repo, tmp_path):
    out = tmp_path / "chart.html"
    rc = main_module.run_cli([
        _repo_path(sample_repo), "--detail", "Rough",
        "--output", str(out), "--no-animated",
    ])
    assert rc == 0
    assert out.exists()
    assert "{{DATA_JSON}}" not in out.read_text(encoding="utf-8")


def test_cli_rejects_no_outputs(sample_repo):
    with pytest.raises(SystemExit):
        main_module.run_cli([_repo_path(sample_repo),
                             "--no-static", "--no-animated"])
