# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the runner that learns feedforward and feedback together for every combination of a sweep."""

from typing import Any

import numpy as np
import pytest
from conftest import Runner
from learn_combined import main
from test_learn_feedback import read_run

from arm_rmhl_test.combined import learn


@pytest.fixture
def sweep(config: dict[str, Any]) -> dict[str, Any]:
    """Both schedules of a short training of both learners on a short reach."""
    config["reach"]["duration"] = 0.3
    config["readout"] = {"forgetting": 0.999, "delta": 10.0}
    config["rule"] = {
        "preset": "burms2015",
        "learning_rate": 1.0,
        "exploration": {"distribution": "gaussian", "amplitude": 0.1, "seed": 0},
    }
    config["schedule"] = {"kind": "concurrent", "handover": 2}
    config["training"] = {"trials": 4, "dead_zone": 0.0, "evaluate_every": 2, "evaluate_all_until": 1}
    config["sweep"] = {"schedule.kind": ["concurrent", "staged"]}
    return config


def test_every_combination_is_trained_and_recorded(sweep: dict[str, Any], run_runner: Runner):
    run_dir = run_runner(main, sweep)

    rows, data = read_run(run_dir)
    assert [row["schedule.kind"] for row in rows] == ["concurrent", "staged"]
    assert {"stiffness_11", "acceleration_22", "feedforward_constant_2"} <= set(rows[0])
    np.testing.assert_array_equal(data["evaluated_at"], [0, 1, 2, 4])
    assert data["errors"].shape == (2, 4)
    assert data["weights"].shape == (2, 4, 5, 2)
    assert data["feedforward_weights"].shape == (2, 4, 7, 2)
    sweep["schedule"]["kind"] = "staged"
    del sweep["sweep"]
    expected = learn(sweep)
    np.testing.assert_array_equal(data["evaluations"][1], expected.evaluations)
    np.testing.assert_array_equal(data["feedforward_weights"][1], expected.feedforward_weights)
    assert float(rows[1]["final_error_m"]) == data["evaluations"][1, -1]
    assert (run_dir / "learning.png").stat().st_size > 0


def test_a_learner_left_out_is_recorded_as_zero(sweep: dict[str, Any], run_runner: Runner):
    del sweep["readout"]

    _, data = read_run(run_runner(main, sweep))

    np.testing.assert_array_equal(data["feedforward_weights"], 0.0)


def test_workers_give_the_results_of_one_process(sweep: dict[str, Any], run_runner: Runner):
    _, alone = read_run(run_runner(main, sweep))
    _, spread = read_run(run_runner(main, sweep, "--workers", "2"))

    for name, array in alone.items():
        np.testing.assert_array_equal(spread[name], array)
