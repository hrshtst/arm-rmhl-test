# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The feedback_error_learning configurations follow its protocol (see its README.md)."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENT = REPO_ROOT / "experiments/feedback_error_learning"
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arm
# The tables of feedback_from_scratch, whose configurations the tests' CONFIG matches too.
SHARED = ("initial", "skeleton", "simulator", "reach", "command")


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_has_the_arm_the_reach_and_the_weak_pd_of_feedback_from_scratch(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    assert "rule" not in config
    assert "feedback" not in config
    assert (config["training"]["dead_zone"], config["training"]["evaluate_every"]) == (0.0, 1)
    expand(config)  # every swept setting is in the configuration


def test_the_tuning_sweeps_the_forgetting_factor_by_delta_for_100_trials():
    config = load(EXPERIMENT / "tune.toml")

    assert config["training"]["trials"] == 100
    assert config["sweep"] == {
        "readout.forgetting": [1.0, 0.9999, 0.999, 0.99],
        "readout.delta": [0.1, 1.0, 10.0, 100.0],
    }
