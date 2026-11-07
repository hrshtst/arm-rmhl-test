# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The directional_forgetting configurations follow its protocol (see its README.md)."""

import copy
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENT = REPO_ROOT / "experiments/directional_forgetting"
COMBINED = REPO_ROOT / "experiments/combined_learning"
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arm
SHARED = ("initial", "skeleton", "simulator", "reach", "command")


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def exponential(config: dict[str, Any]) -> dict[str, Any]:
    """The configuration forgetting as combined_learning's did: without the forgetting method."""
    config = copy.deepcopy(config)
    del config["readout"]["forgetting_method"]
    return config


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_forgets_directionally_on_the_arm_the_reach_and_the_weak_pd(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    assert config["readout"]["forgetting_method"] == "directional"
    assert config["schedule"]["kind"] == "concurrent"
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize(
    ("name", "counterpart"),
    [
        ("windup_feedforward_alone", "windup_feedforward_alone"),
        ("continued_feedforward_alone", "final_feedforward_alone"),
        ("tune_readout_concurrent_inertia", "tune_readout_concurrent_inertia"),
    ],
)
def test_a_rerun_is_its_combined_learning_counterpart_forgetting_directionally(name: str, counterpart: str):
    assert exponential(load(EXPERIMENT / f"{name}.toml")) == load(COMBINED / f"{counterpart}.toml")


def test_the_raw_feedforwards_round_has_the_feedback_at_its_best_before_step_1_4():
    config = exponential(load(EXPERIMENT / "tune_readout_concurrent_raw.toml"))
    round_4 = load(COMBINED / "tune_concurrent_raw_round4.toml")
    counterpart = load(COMBINED / "tune_readout_concurrent_raw.toml")

    # Round 4's best, a learning rate of 250 with 0.32 N m (combined_learning's README).
    assert (config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"]) == (250.0, 0.32)
    assert config["rule"]["learning_rate"] in round_4["sweep"]["rule.learning_rate"]
    assert config["rule"]["exploration"]["amplitude"] in round_4["sweep"]["rule.exploration.amplitude"]
    config["rule"]["learning_rate"] = counterpart["rule"]["learning_rate"]
    assert config == counterpart
