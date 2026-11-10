# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The learning_speed configurations follow its protocol (see its README.md)."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENTS = REPO_ROOT / "experiments"
EXPERIMENT = EXPERIMENTS / "learning_speed"
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arms
SHARED = ("initial", "skeleton", "simulator", "reach", "command")
SCALES = ("raw", "inertia")


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
def test_every_configuration_is_on_the_arm_the_reach_and_the_weak_pd(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize(
    ("scale", "path"),
    [(scale, path) for scale in SCALES for path in sorted(EXPERIMENT.glob(f"tune_staged_{scale}*.toml"))],
    ids=lambda value: getattr(value, "stem", value),
)
def test_tuning_the_staged_schedule_changes_only_the_schedule_and_the_feedbacks_setting(scale: str, path: Path):
    config = load(path)
    base = load(EXPERIMENTS / "feedback_without_constant" / f"final_concurrent_{scale}.toml")

    assert config["schedule"] == {"kind": "staged", "handover": 100}
    assert config["training"] == {"trials": 1000, "dead_zone": 0.0, "evaluate_every": 20, "evaluate_all_until": 100}
    assert config["rule"]["exploration"]["seed"] == 0
    config["schedule"]["kind"] = "concurrent"
    assert without_tuned(config) == without_tuned(base)


@pytest.mark.parametrize(
    ("scale", "path"),
    [(scale, path) for scale in SCALES for path in sorted(EXPERIMENT.glob(f"tune_feedback_short_{scale}*.toml"))],
    ids=lambda value: getattr(value, "stem", value),
)
def test_tuning_the_feedback_for_speed_changes_only_its_setting_and_the_budget(scale: str, path: Path):
    config = load(path)
    base = load(EXPERIMENTS / "feedback_from_scratch" / f"long_decorrelated_{scale}.toml")

    assert config["training"] == {"trials": 300, "dead_zone": 0.0, "evaluate_every": 20, "evaluate_all_until": 100}
    assert config["rule"]["exploration"]["seed"] == 0
    assert "constant" not in config["feedback"]  # report 001's: with the constant
    assert without_tuned(config) == without_tuned(base)


def final_seeds(config: dict[str, Any]) -> list[int]:
    return config["sweep"]["rule.exploration.seed"]


@pytest.mark.parametrize(("scale", "rate", "amplitude"), [("raw", 16.0, 51.2), ("inertia", 50.0, 32.0)])
def test_a_final_staged_run_is_the_tuned_setting_on_new_seeds(scale: str, rate: float, amplitude: float):
    config = load(EXPERIMENT / f"final_staged_{scale}.toml")
    tuning = load(EXPERIMENT / f"tune_staged_{scale}.toml")

    assert final_seeds(config) == [1, 2, 3, 4, 5]
    assert (config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"]) == (rate, amplitude)
    assert config["training"] == {**tuning["training"], "trials": 10000}
    assert without_tuned(config) == without_tuned(tuning)


@pytest.mark.parametrize("scale", SCALES)
def test_the_feedback_without_the_constant_is_report_001s_but_for_it(scale: str):
    config = load(EXPERIMENT / f"final_feedback_no_constant_{scale}.toml")
    base = load(EXPERIMENTS / "feedback_from_scratch" / f"long_decorrelated_{scale}.toml")

    assert config["feedback"].pop("constant") is False
    assert config["training"].pop("evaluate_all_until") == 100
    assert config == base


@pytest.mark.parametrize(("scale", "rate", "amplitude"), [("raw", 5.0, 6.4), ("inertia", 35.0, 11.0)])
def test_the_feedback_tuned_for_speed_is_report_001s_but_for_its_setting(scale: str, rate: float, amplitude: float):
    config = load(EXPERIMENT / f"final_feedback_short_{scale}.toml")
    base = load(EXPERIMENTS / "feedback_from_scratch" / f"long_decorrelated_{scale}.toml")

    assert final_seeds(config) == [1, 2, 3, 4, 5]
    assert (config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"]) == (rate, amplitude)
    assert config["training"] == {**base["training"], "trials": 3000, "evaluate_all_until": 100}
    assert "constant" not in config["feedback"]
    assert without_tuned(config) == without_tuned(base)
