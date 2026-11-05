# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The combined_learning configurations follow its protocol (see its README.md)."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENT = REPO_ROOT / "experiments/combined_learning"
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arm
SHARED = ("initial", "skeleton", "simulator", "reach", "command")
SCALES = {"raw": "none", "inertia": "inertia"}


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def report_001_long(variant: str) -> dict[str, Any]:
    return load(REPO_ROOT / f"experiments/feedback_from_scratch/long_decorrelated_{variant}.toml")


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_has_the_arm_the_reach_and_the_weak_pd_of_feedback_from_scratch(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    assert "readout" in config or "rule" in config
    assert config["training"]["dead_zone"] == 0.0
    assert (config["training"]["evaluate_every"], config["training"]["evaluate_all_until"]) == (20, 100)
    assert config["schedule"]["handover"] == 100
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_the_feedback_is_report_001s_decorrelated_rule(path: Path):
    config = load(path)
    if "rule" not in config:
        return
    variant = next(name for name in SCALES if path.stem.endswith(name))
    reference = report_001_long(variant)

    assert config["feedback"] == reference["feedback"] == {"scale": SCALES[variant]}
    assert {key: config["rule"][key] for key in ("preset", "decorrelation")} == {
        "preset": "burms2015",
        "decorrelation": 1.0,
    }
    assert config["rule"]["exploration"]["distribution"] == "gaussian"
    assert set(config["rule"]) == set(reference["rule"])


@pytest.mark.parametrize("variant", SCALES)
def test_tuning_round_1_sweeps_the_feedback_for_both_schedules_with_report_002s_feedforward(variant: str):
    config = load(EXPERIMENT / f"tune_{variant}.toml")
    reference = report_001_long(variant)

    assert config["readout"] == load(REPO_ROOT / "experiments/feedback_error_learning/final.toml")["readout"]
    assert config["rule"]["exploration"]["seed"] == 0
    assert config["training"]["trials"] == 1000
    sweep = config["sweep"]
    assert list(sweep) == ["schedule.kind", "rule.learning_rate", "rule.exploration.amplitude"]
    assert sweep["schedule.kind"] == ["concurrent", "staged"]
    assert reference["rule"]["learning_rate"] in sweep["rule.learning_rate"]  # report 001's tuned setting
    assert reference["rule"]["exploration"]["amplitude"] in sweep["rule.exploration.amplitude"]
    assert max(sweep["rule.learning_rate"]) > reference["rule"]["learning_rate"]
    assert min(sweep["rule.exploration.amplitude"]) < reference["rule"]["exploration"]["amplitude"]
