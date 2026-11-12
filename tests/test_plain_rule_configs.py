# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The plain_rule configurations follow its protocol (see its README.md)."""

import itertools
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENTS = REPO_ROOT / "experiments"
EXPERIMENT = EXPERIMENTS / "plain_rule"
ANALYSES = ("compare_", "decorrelation_")  # configurations of analyses of runs, not of the arms' runs
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith(ANALYSES))
SHARED = ("initial", "skeleton", "simulator", "reach", "command")
SCALES = ("raw", "inertia")
PLAIN = False  # the rule's decorrelation: none, the plain node-perturbation rule
DECORRELATED = 1.0  # burms2015's
TUNED = {"raw": (32.0, 0.1), "inertia": (0.8, 5.7)}  # the closest at 1,000 trials on seed 0, over all rounds


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def without_tuned(config: dict[str, Any]) -> dict[str, Any]:
    """The configuration without what tuning may change: the feedback's setting, the seeds and the evaluations."""
    config["rule"].pop("learning_rate")
    config["rule"]["exploration"].pop("amplitude")
    config["rule"]["exploration"].pop("seed")
    config.pop("training")
    config.pop("sweep")
    return config


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_is_on_the_arm_the_reach_and_the_weak_pd_with_the_plain_rule(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    assert config["rule"]["decorrelation"] is PLAIN
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize(
    ("scale", "path"),
    [(scale, path) for scale in SCALES for path in sorted(EXPERIMENT.glob(f"tune_combined_{scale}*.toml"))],
    ids=lambda value: getattr(value, "stem", value),
)
def test_tuning_the_combined_controller_changes_only_the_rule_and_the_feedbacks_setting(scale: str, path: Path):
    config = load(path)
    base = load(EXPERIMENTS / "feedback_without_constant" / f"final_concurrent_{scale}.toml")

    assert config["training"] == {"trials": 1000, "dead_zone": 0.0, "evaluate_every": 20, "evaluate_all_until": 100}
    assert config["rule"]["exploration"]["seed"] == 0
    assert set(config["sweep"]) == {"rule.learning_rate", "rule.exploration.amplitude"}
    config["rule"]["decorrelation"] = DECORRELATED
    assert without_tuned(config) == without_tuned(base)


@pytest.mark.parametrize("path", sorted(EXPERIMENT.glob("tune_staged_inertia*.toml")), ids=lambda path: path.stem)
def test_tuning_the_staged_schedule_is_report_006s_staged_controller_with_the_plain_rule(path: Path):
    config = load(path)
    staged = load(EXPERIMENTS / "learning_speed" / "tune_staged_inertia.toml")
    concurrent = load(EXPERIMENT / "tune_combined_inertia.toml")

    assert config["schedule"] == {"kind": "staged", "handover": 100}
    assert config["training"] == concurrent["training"]
    assert config["rule"]["exploration"]["seed"] == 0
    assert set(config["sweep"]) == {"rule.learning_rate", "rule.exploration.amplitude"}
    assert without_tuned(load(path)) == without_tuned(concurrent) | {"schedule": config["schedule"]}
    config["rule"]["decorrelation"] = DECORRELATED
    assert without_tuned(config) == without_tuned(staged)


def tuned_settings(scale: str) -> set[tuple[float, float]]:
    """Every learning rate and amplitude that a round of tuning the scale ran."""
    settings: set[tuple[float, float]] = set()
    for path in EXPERIMENT.glob(f"tune_combined_{scale}*.toml"):
        sweep = load(path)["sweep"]
        settings |= set(itertools.product(sweep["rule.learning_rate"], sweep["rule.exploration.amplitude"]))
    return settings


@pytest.mark.parametrize("scale", SCALES)
def test_arm_a_is_the_tuned_combined_controller_on_the_final_seeds(scale: str):
    config = load(EXPERIMENT / f"final_combined_{scale}.toml")
    tuning = load(EXPERIMENT / f"tune_combined_{scale}.toml")
    setting = (config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"])

    assert setting == TUNED[scale]
    assert setting in tuned_settings(scale)
    assert final_seeds(config) == [1, 2, 3, 4, 5]
    assert config["training"] == tuning["training"] | {"trials": 10000}
    assert without_tuned(config) == without_tuned(tuning)


@pytest.mark.parametrize("scale", SCALES)
def test_arm_b_is_arm_a_without_its_feedforward(scale: str):
    alone = load(EXPERIMENT / f"final_feedback_no_constant_{scale}.toml")
    combined = load(EXPERIMENT / f"final_combined_{scale}.toml")

    del combined["readout"], combined["schedule"]
    assert alone == combined


@pytest.mark.parametrize("scale", SCALES)
def test_arm_c_continues_report_001s_final_runs_of_the_plain_rule(scale: str):
    config = load(EXPERIMENT / f"long_plain_{scale}.toml")
    base = load(EXPERIMENTS / "feedback_from_scratch" / f"final_plain_{scale}.toml")

    assert base["training"]["trials"] == 3000
    assert config.pop("training") == base.pop("training") | {"trials": 10000, "evaluate_all_until": 100}
    assert config == base  # the constant included, at report 001's tuned setting and seeds


def test_the_mechanism_check_records_the_decorrelated_arms_of_reports_005_and_006_inertia_scaled():
    config = load(EXPERIMENT / "decorrelation_inertia.toml")
    reports = REPO_ROOT / "reports"
    copies = [
        reports / "005-feedback-without-constant" / "results" / "20261108-074908-final_concurrent_inertia",
        reports / "006-learning-speed" / "results" / "20261111-020819-final_feedback_no_constant_inertia",
    ]

    assert [Path(arm["run"]).name for arm in config["arm"]] == [copy.name for copy in copies]
    for copy in copies:  # the reports' copies of the runs, as the storage root holds them
        stored = load(copy / "config.toml")
        assert stored["feedback"] == {"scale": "inertia", "constant": False}
        assert stored["rule"]["decorrelation"] == DECORRELATED
        assert final_seeds(stored) == [1, 2, 3, 4, 5]
    assert config["training"] == {"trials": 1000}


def final_seeds(config: dict[str, Any]) -> list[int]:
    return config["sweep"]["rule.exploration.seed"]
