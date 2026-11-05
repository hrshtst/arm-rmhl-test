# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The combined_learning configurations follow its protocol (see its README.md)."""

import copy
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
    fixed = {name: copy.deepcopy(table) for name, table in config.items() if name not in ("sweep", "readout")}
    fixed["schedule"] = {key: value for key, value in config["schedule"].items() if key != "kind"}
    fixed["rule"] = {key: value for key, value in config["rule"].items() if key != "learning_rate"}
    fixed["rule"]["exploration"] = {
        key: value for key, value in config["rule"]["exploration"].items() if key != "amplitude"
    }
    return fixed


FEEDBACK_ROUNDS = sorted(EXPERIMENT.glob("tune_*_round*.toml"))
READOUT_ROUNDS = sorted(EXPERIMENT.glob("tune_readout_*.toml"))


def in_readout_grid(config: dict[str, Any]) -> bool:
    grid = load(REPO_ROOT / "experiments/feedback_error_learning/tune.toml")["sweep"]
    return (
        config["readout"]["forgetting"] in grid["readout.forgetting"]
        and config["readout"]["delta"] in grid["readout.delta"]
    )


def variant_of(config: dict[str, Any]) -> str:
    return next(name for name, scale in SCALES.items() if scale == config["feedback"]["scale"])


def feedback_grid(variant: str) -> tuple[set[float], set[float]]:
    """Every learning rate and amplitude that the feedback's rounds ran for a scale."""
    rates: set[float] = set()
    amplitudes: set[float] = set()
    for path in [EXPERIMENT / f"tune_{variant}.toml", *EXPERIMENT.glob(f"tune_*_{variant}_round*.toml")]:
        config = load(path)
        sweep = config.get("sweep", {})
        rates |= set(sweep.get("rule.learning_rate", [config["rule"]["learning_rate"]]))
        amplitudes |= set(sweep.get("rule.exploration.amplitude", [config["rule"]["exploration"]["amplitude"]]))
    return rates, amplitudes


@pytest.mark.parametrize("path", FEEDBACK_ROUNDS, ids=lambda path: path.stem)
def test_a_later_feedback_round_changes_only_the_feedbacks_settings_for_one_schedule(path: Path):
    config = load(path)
    round_1 = load(EXPERIMENT / f"tune_{variant_of(config)}.toml")

    assert fixed_part(config) == fixed_part(round_1)
    assert in_readout_grid(config)  # report 002's setting, or the feedforward's round's best after it
    assert config["schedule"]["kind"] == path.stem.split("_")[1]  # tune_<schedule>_<scale>_round<n>
    assert set(config.get("sweep", {})) <= {"rule.learning_rate", "rule.exploration.amplitude"}


@pytest.mark.parametrize("path", READOUT_ROUNDS, ids=lambda path: path.stem)
def test_the_feedforwards_round_sweeps_report_002s_grid_with_a_feedback_setting_already_run(path: Path):
    config = load(path)
    variant = variant_of(config)
    rates, amplitudes = feedback_grid(variant)

    assert fixed_part(config) == fixed_part(load(EXPERIMENT / f"tune_{variant}.toml"))
    assert config["schedule"]["kind"] == path.stem.split("_")[2]  # tune_readout_<schedule>_<scale>
    assert config["sweep"] == load(REPO_ROOT / "experiments/feedback_error_learning/tune.toml")["sweep"]
    assert config["rule"]["learning_rate"] in rates
    assert config["rule"]["exploration"]["amplitude"] in amplitudes


FINALS = sorted(path for path in EXPERIMENT.glob("final_*.toml") if "_alone" not in path.stem)


@pytest.mark.parametrize("path", FINALS, ids=lambda path: path.stem)
def test_a_final_run_is_a_tuned_setting_on_seeds_1_to_5_for_10000_trials(path: Path):
    config = load(path)
    rates, amplitudes = feedback_grid(variant_of(config))
    final, tuning = fixed_part(config), fixed_part(load(EXPERIMENT / f"tune_{variant_of(config)}.toml"))
    for fixed in (final, tuning):  # the seed and the budget are the final runs' own
        del fixed["rule"]["exploration"]["seed"], fixed["training"]["trials"]

    assert final == tuning
    assert config["schedule"]["kind"] == path.stem.split("_")[1]  # final_<schedule>_<scale>
    assert config["training"]["trials"] == 10000
    assert config["sweep"] == {"rule.exploration.seed": [1, 2, 3, 4, 5]}
    assert config["rule"]["learning_rate"] in rates
    assert config["rule"]["exploration"]["amplitude"] in amplitudes
    assert in_readout_grid(config)


def test_the_feedback_alone_is_a_concurrent_final_without_its_feedforward():
    for path in EXPERIMENT.glob("final_feedback_alone_*.toml"):
        variant = path.stem.removeprefix("final_feedback_alone_")
        combined = load(EXPERIMENT / f"final_concurrent_{variant}.toml")
        del combined["readout"]
        assert load(path) == combined


def test_the_feedforward_alone_is_a_concurrent_final_without_its_feedback():
    alone = load(EXPERIMENT / "final_feedforward_alone.toml")
    combined = load(EXPERIMENT / "final_concurrent_inertia.toml")

    for table in ("feedback", "rule", "sweep"):  # without noise, the seeds change nothing
        del combined[table]
    assert alone == combined
