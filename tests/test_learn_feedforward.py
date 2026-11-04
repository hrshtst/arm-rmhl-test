# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the runner that learns feedforward for every combination of a sweep."""

from typing import Any

import numpy as np
import pytest
from conftest import Runner
from learn_feedforward import main
from test_learn_feedback import read_run

from arm_rmhl_test.feedforward import learn


@pytest.fixture
def sweep(config: dict[str, Any]) -> dict[str, Any]:
    """Two forgetting factors of a short training on a short reach."""
    config["reach"]["duration"] = 0.3
    config["readout"] = {"forgetting": 1.0, "delta": 10.0}
    config["training"] = {"trials": 3, "dead_zone": 0.0, "evaluate_every": 1}
    config["sweep"] = {"readout.forgetting": [1.0, 0.999]}
    return config


def test_every_combination_is_trained_and_recorded(sweep: dict[str, Any], run_runner: Runner):
    run_dir = run_runner(main, sweep)

    rows, data = read_run(run_dir)
    assert [row["readout.forgetting"] for row in rows] == ["1.0", "0.999"]
    assert [row["outcome"] for row in rows] == ["improved", "improved"]
    assert "acceleration_11" in rows[0]
    np.testing.assert_array_equal(data["evaluated_at"], [0, 1, 2, 3])
    assert data["errors"].shape == (2, 3)
    assert data["weights"].shape == (2, 4, 7, 2)
    np.testing.assert_array_equal(data["scale"], 1.0)
    sweep["readout"]["forgetting"] = 0.999
    del sweep["sweep"]
    np.testing.assert_array_equal(data["evaluations"][1], learn(sweep).evaluations)
    assert float(rows[1]["final_error_m"]) == data["evaluations"][1, -1]
    assert (run_dir / "learning.png").stat().st_size > 0


def test_workers_give_the_results_of_one_process(sweep: dict[str, Any], run_runner: Runner):
    _, alone = read_run(run_runner(main, sweep))
    _, spread = read_run(run_runner(main, sweep, "--workers", "2"))

    for name, array in alone.items():
        np.testing.assert_array_equal(spread[name], array)
