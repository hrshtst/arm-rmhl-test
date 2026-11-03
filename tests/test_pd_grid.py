# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the runner that tracks the reach with the joint PD alone over a sweep of its gains."""

import csv
from typing import Any

import numpy as np
import pytest
from conftest import Runner
from pd_grid import main, track

from arm_rmhl_test.arm import command_gains, effort, make_arm, make_reach, run_reach, tracking_error


@pytest.fixture
def short(config: dict[str, Any]) -> dict[str, Any]:
    """A short reach, to keep the tests fast."""
    config["reach"]["duration"] = 0.5
    return config


def test_a_combination_reports_the_gains_and_how_the_reach_went(short: dict[str, Any]):
    arm = make_arm(short)
    reach = make_reach(short, arm)
    kp, kd = command_gains(short, arm)
    run = run_reach(arm, reach, kp, kd)

    row = track(short)

    assert row["kp_1"] == kp[0]
    assert row["kd_2"] == kd[1]
    assert row["tracking_error_m"] == tracking_error(run, reach)
    assert row["effort"] == effort(run, reach)
    assert row["peak_torque_nm"] == np.abs(run.tau).max()


def test_a_diverging_reach_has_an_infinite_error_and_no_effort(short: dict[str, Any]):
    short["command"]["omega"] = 1e100

    row = track(short)

    assert row["tracking_error_m"] == np.inf
    assert np.isnan(row["effort"])
    assert np.isnan(row["peak_torque_nm"])


def test_the_runner_writes_a_row_per_combination_and_the_heatmap(short: dict[str, Any], run_runner: Runner):
    short["sweep"] = {"command.omega": [5.0, 20.0], "command.damping_ratio": [0.4, 0.7, 1.0]}

    run_dir = run_runner(main, short)

    with (run_dir / "grid.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [(float(r["command.omega"]), float(r["command.damping_ratio"])) for r in rows] == [
        (omega, ratio) for omega in (5.0, 20.0) for ratio in (0.4, 0.7, 1.0)
    ]
    short["command"] |= {"omega": 20.0, "damping_ratio": 0.4}
    assert float(rows[3]["tracking_error_m"]) == track(short)["tracking_error_m"]
    assert (run_dir / "grid.png").stat().st_size > 0
