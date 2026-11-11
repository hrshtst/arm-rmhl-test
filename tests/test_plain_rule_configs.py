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
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arms
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
