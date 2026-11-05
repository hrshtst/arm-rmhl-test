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
    variant = next(name for name, scale in SCALES.items() if scale == config["feedback"]["scale"])
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


def fixed_part(config: dict[str, Any]) -> dict[str, Any]:
    """The configuration without what tuning rounds choose: the sweep, the schedule's kind, the tuned settings."""
    fixed = {name: table for name, table in config.items() if name not in ("sweep", "readout")}
    fixed["schedule"] = {key: value for key, value in config["schedule"].items() if key != "kind"}
    fixed["rule"] = {key: value for key, value in config["rule"].items() if key != "learning_rate"}
    fixed["rule"]["exploration"] = {
        key: value for key, value in config["rule"]["exploration"].items() if key != "amplitude"
    }
    return fixed


@pytest.mark.parametrize(
    ("name", "variant", "kind"),
    [("tune_concurrent_raw_round2", "raw", "concurrent"), ("tune_staged_inertia_round2", "inertia", "staged")],
)
def test_round_2_extends_the_feedbacks_grid_past_round_1s_edge_for_one_schedule(name: str, variant: str, kind: str):
    config, round_1 = load(EXPERIMENT / f"{name}.toml"), load(EXPERIMENT / f"tune_{variant}.toml")

    assert fixed_part(config) == fixed_part(round_1)
    assert config["readout"] == round_1["readout"]
    assert config["schedule"]["kind"] == kind
    sweep = config["sweep"]
    assert list(sweep) == ["rule.learning_rate", "rule.exploration.amplitude"]
    assert max(sweep["rule.learning_rate"]) > max(round_1["sweep"]["rule.learning_rate"])


@pytest.mark.parametrize(("variant", "kind"), [("raw", "staged"), ("inertia", "concurrent")])
def test_the_feedforwards_round_sweeps_report_002s_grid_with_a_feedback_setting_of_round_1(variant: str, kind: str):
    config, round_1 = (
        load(EXPERIMENT / f"tune_readout_{kind}_{variant}.toml"),
        load(EXPERIMENT / f"tune_{variant}.toml"),
    )

    assert fixed_part(config) == fixed_part(round_1)
    assert config["schedule"]["kind"] == kind
    assert config["sweep"] == load(REPO_ROOT / "experiments/feedback_error_learning/tune.toml")["sweep"]
    assert config["rule"]["learning_rate"] in round_1["sweep"]["rule.learning_rate"]
    assert config["rule"]["exploration"]["amplitude"] in round_1["sweep"]["rule.exploration.amplitude"]
