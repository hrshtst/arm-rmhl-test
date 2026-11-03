# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The feedback_from_scratch configurations follow its protocol (see its README.md)."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENT = REPO_ROOT / "experiments/feedback_from_scratch"
CONFIGS = sorted(EXPERIMENT.glob("*.toml"))
TUNING = [path for path in CONFIGS if path.stem.startswith("tune_")]
SHARED = ("initial", "skeleton", "simulator", "reach", "command")


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_has_the_arm_the_reach_and_the_weak_pd_of_the_tests(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize("path", TUNING, ids=lambda path: path.stem)
def test_tuning_sees_only_seed_0(path: Path):
    config = load(path)

    assert config["rule"]["exploration"]["seed"] == 0
    assert "rule.exploration.seed" not in config["sweep"]


def test_both_rules_are_tuned_with_the_same_budget():
    rules = {load(path)["rule"].get("decorrelation") for path in TUNING}
    budgets = {tuple(load(path)["training"].items()) for path in TUNING}

    assert rules == {False, 1.0}
    assert len(budgets) == 1


FINAL = [path for path in CONFIGS if path.stem.startswith("final_")]


def without_seed(config: dict[str, Any]) -> dict[str, Any]:
    """The configuration's feedback and rule, without the exploration's seed."""
    rule = config["rule"] | {"exploration": config["rule"]["exploration"] | {"seed": None}}
    return {"feedback": config.get("feedback"), "rule": rule}


@pytest.mark.parametrize("path", FINAL, ids=lambda path: path.stem)
def test_the_final_runs_take_a_tuned_setting_to_the_unseen_seeds(path: Path):
    config = load(path)
    tuned = [without_seed(variant) for tuning in TUNING for _, variant in expand(load(tuning))]

    assert config["sweep"] == {"rule.exploration.seed": [1, 2, 3, 4, 5]}
    assert without_seed(config) in tuned


def test_the_final_runs_share_one_budget_beyond_the_tunings():
    budgets = {tuple(load(path)["training"].items()) for path in FINAL}
    tuning_trials = {load(path)["training"]["trials"] for path in TUNING}

    assert len(FINAL) == 4
    assert len(budgets) == 1
    assert dict(budgets.pop())["trials"] >= max(tuning_trials)
