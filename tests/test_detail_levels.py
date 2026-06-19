"""Tests for the detail-level targets and their sampling behaviour.

The "Full" level is special: its target is infinite so pick_sample_step()
always returns step 1, meaning every commit is analysed regardless of how
large the history is.
"""

import math

import repo_growth
from repo_growth import DETAIL_TARGETS, pick_sample_step


def test_full_target_is_infinite():
    assert DETAIL_TARGETS["Full"] == math.inf


def test_named_levels_present_and_ordered():
    # Full comes last so the dropdown reads least-to-most detail.
    assert list(DETAIL_TARGETS.keys()) == ["Rough", "Standard", "Detailed", "Full"]


def test_full_processes_every_commit():
    # Step 1 means list[::step] yields every commit — no sampling — for any
    # history size, including ones far larger than the Detailed target.
    for n in (1, 50, 900, 901, 20_000, 1_000_000):
        assert pick_sample_step(n, target=DETAIL_TARGETS["Full"]) == 1


def test_finite_levels_still_sample_large_histories():
    # Sanity check the non-Full levels still down-sample as before.
    assert pick_sample_step(100_000, target=DETAIL_TARGETS["Standard"]) > 1
