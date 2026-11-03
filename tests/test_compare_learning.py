# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for comparing the learning of several runs with joint PDs."""

import csv
from typing import Any

import compare_learning
import learn_feedback
import numpy as np
import pd_grid
import pytest
from compare_learning import Arm, summarize_arm
from conftest import Runner


def arm(outcomes: list[str], finals: list[float], bests: list[float]) -> Arm:
    rows = [
        {"outcome": outcome, "final_error_m": str(final), "best_error_m": str(best)}
        for outcome, final, best in zip(outcomes, finals, bests, strict=True)
    ]
    return Arm("plain", rows, np.array([0, 10]), np.full((len(rows), 2), 0.1))


def test_an_arm_is_summarized_over_its_trainings_a_diverged_one_infinitely_far():
    row = summarize_arm(arm(["improved", "worse", "diverged"], [0.05, 0.7, np.nan], [0.04, 0.17, 0.12]))

    assert (row["trainings"], row["improved"], row["worse"], row["diverged"]) == (3, 1, 1, 1)
    assert row["median_final_error_m"] == 0.7
    assert (row["min_final_error_m"], row["max_final_error_m"]) == (0.05, np.inf)
    assert row["median_best_error_m"] == pytest.approx(0.12)


def test_the_comparison_draws_the_arms_against_the_pds(config: dict[str, Any], run_runner: Runner):
    config["reach"]["duration"] = 0.3
    grid = run_runner(pd_grid.main, config | {"sweep": {"command.omega": [5.0, 20.0], "command.damping_ratio": [0.7]}})
    config["rule"] = {
        "preset": "burms2015",
        "learning_rate": 1.0,
        "decorrelation": False,
        "exploration": {"distribution": "gaussian", "amplitude": 0.1, "seed": 1},
    }
    config["training"] = {"trials": 2, "dead_zone": 0.0, "evaluate_every": 1}
    learned = run_runner(learn_feedback.main, config | {"sweep": {"rule.exploration.seed": [1, 2]}})
    comparison = {
        "arm": [{"run": f"results/{learned.name}", "label": "plain"}],
        "pd": {"run": f"results/{grid.parent.name}/{grid.name}", "marks": [[5.0, 0.7]]},
    }

    run_dir = run_runner(compare_learning.main, comparison)

    with (run_dir / "arms.csv").open() as f:
        (row,) = list(csv.DictReader(f))
    assert (row["arm"], row["trainings"]) == ("plain", "2")
    assert (run_dir / "learning.png").stat().st_size > 0


def test_a_marked_pd_must_be_in_the_grid(config: dict[str, Any], run_runner: Runner):
    config["reach"]["duration"] = 0.3
    grid = run_runner(pd_grid.main, config | {"sweep": {"command.omega": [5.0], "command.damping_ratio": [0.7]}})

    with pytest.raises(KeyError, match="not in the grid"):
        compare_learning.pd_references(grid, [[20.0, 0.7]])
