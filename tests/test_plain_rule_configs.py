# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The plain_rule configurations follow its protocol (see its README.md)."""

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
