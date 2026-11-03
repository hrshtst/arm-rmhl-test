# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the runner that learns feedback for every combination of a sweep."""

import csv
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import Runner
from learn_feedback import main

from arm_rmhl_test.feedback import learn


@pytest.fixture
def sweep(config: dict[str, Any]) -> dict[str, Any]:
    """Two seeds of a short training on a short reach."""
    config["reach"]["duration"] = 0.3
    config["rule"] = {
        "preset": "burms2015",
        "learning_rate": 1.0,
        "decorrelation": False,
        "exploration": {"distribution": "gaussian", "amplitude": 0.1, "seed": 0},
    }
    config["training"] = {"trials": 4, "dead_zone": 0.0, "evaluate_every": 2}
    config["sweep"] = {"rule.learning_rate": [1.0], "rule.exploration.seed": [0, 1]}
    return config


def read_run(run_dir: Path) -> tuple[list[dict[str, str]], dict[str, np.ndarray]]:
    with (run_dir / "runs.csv").open() as f:
        rows = list(csv.DictReader(f))
    with np.load(run_dir / "training.npz") as data:
        return rows, dict(data)


def test_every_combination_is_trained_and_recorded(sweep: dict[str, Any], run_runner: Runner):
    run_dir = run_runner(main, sweep)

    rows, data = read_run(run_dir)
    assert [row["rule.exploration.seed"] for row in rows] == ["0", "1"]
    assert {row["outcome"] for row in rows} <= {"improved", "worse"}
    np.testing.assert_array_equal(data["evaluated_at"], [0, 2, 4])
    assert data["errors"].shape == (2, 4)
    assert data["weights"].shape == (2, 3, 5, 2)
    np.testing.assert_array_equal(data["scale"], 1.0)
    sweep["rule"]["exploration"]["seed"] = 1
    del sweep["sweep"]
    np.testing.assert_array_equal(data["evaluations"][1], learn(sweep).evaluations)
    assert float(rows[1]["final_error_m"]) == data["evaluations"][1, -1]
    assert (run_dir / "learning.png").stat().st_size > 0


def test_workers_give_the_results_of_one_process(sweep: dict[str, Any], run_runner: Runner):
    _, alone = read_run(run_runner(main, sweep))
    _, spread = read_run(run_runner(main, sweep, "--workers", "2"))

    for name, array in alone.items():
        np.testing.assert_array_equal(spread[name], array)
