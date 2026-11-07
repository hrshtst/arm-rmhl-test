# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The directional_forgetting configurations follow its protocol (see its README.md)."""

import copy
import itertools
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


def in_readout_grid(config: dict[str, Any]) -> bool:
    grid = load(REPO_ROOT / "experiments/feedback_error_learning/tune.toml")["sweep"]
    return (
        config["readout"]["forgetting"] in grid["readout.forgetting"]
        and config["readout"]["delta"] in grid["readout.delta"]
    )


def without_tuned(config: dict[str, Any]) -> dict[str, Any]:
    """The configuration without what the tuning rounds choose: the sweep and the settings of either learner."""
    config = copy.deepcopy(config)
    del config["sweep"]
    for key in ("forgetting", "delta"):
        del config["readout"][key]
    del config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"]
    return config


def feedback_settings(config: dict[str, Any]) -> set[tuple[float, float]]:
    """The learning rates by amplitudes a round runs: its sweep's grid, or the feedforward's round's one setting."""
    sweep = config["sweep"]
    if "rule.learning_rate" not in sweep:
        return {(config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"])}
    return set(itertools.product(sweep["rule.learning_rate"], sweep["rule.exploration.amplitude"]))


ROUNDS = sorted(EXPERIMENT.glob("tune_concurrent_*_round*.toml"))


@pytest.mark.parametrize("path", ROUNDS, ids=lambda path: path.stem)
def test_a_feedback_round_sweeps_past_the_round_before_and_repeats_some_of_it(path: Path):
    config = load(path)
    scale, n = path.stem.removeprefix("tune_concurrent_").split("_round")  # tune_concurrent_<scale>_round<n>
    before = load(
        EXPERIMENT
        / (f"tune_readout_concurrent_{scale}.toml" if n == "2" else f"tune_concurrent_{scale}_round{int(n) - 1}.toml")
    )

    assert without_tuned(config) == without_tuned(before)
    assert in_readout_grid(config)
    assert config["readout"] == before["readout"] or n == "2"  # only the feedforward's round moves it
    assert list(config["sweep"]) == ["rule.learning_rate", "rule.exploration.amplitude"]
    assert feedback_settings(config) & feedback_settings(before)  # which must come out the same
    assert feedback_settings(config) - feedback_settings(before)


def tuned_settings(scale: str) -> set[tuple[float, float]]:
    """Every feedback setting that a tuning round of one scale ran."""
    rounds = [
        EXPERIMENT / f"tune_readout_concurrent_{scale}.toml",
        *EXPERIMENT.glob(f"tune_concurrent_{scale}_round*.toml"),
    ]
    return set().union(*(feedback_settings(load(path)) for path in rounds))


FINALS = sorted(EXPERIMENT.glob("final_concurrent_*.toml"))


@pytest.mark.parametrize("path", FINALS, ids=lambda path: path.stem)
def test_a_final_run_is_a_tuned_setting_on_seeds_1_to_5_for_10000_trials(path: Path):
    config = load(path)
    scale = path.stem.removeprefix("final_concurrent_")
    final, tuning = without_tuned(config), without_tuned(load(EXPERIMENT / f"tune_readout_concurrent_{scale}.toml"))
    for fixed in (final, tuning):  # the seed and the budget are the final runs' own
        del fixed["rule"]["exploration"]["seed"], fixed["training"]["trials"]

    assert final == tuning
    assert config["training"]["trials"] == 10000
    assert config["sweep"] == {"rule.exploration.seed": [1, 2, 3, 4, 5]}
    assert (config["rule"]["learning_rate"], config["rule"]["exploration"]["amplitude"]) in tuned_settings(scale)
    assert in_readout_grid(config)


@pytest.mark.parametrize("path", FINALS, ids=lambda path: path.stem)
def test_a_final_run_is_combined_learnings_but_for_the_tuned_settings_and_the_forgetting_method(path: Path):
    config, counterpart = exponential(load(path)), load(COMBINED / path.name)

    assert without_tuned(config) == without_tuned(counterpart)


def test_the_feedforward_alone_is_a_concurrent_final_without_its_feedback():
    paths = list(EXPERIMENT.glob("final_feedforward_alone_*.toml"))
    assert paths
    for path in paths:
        combined = load(EXPERIMENT / f"final_concurrent_{path.stem.removeprefix('final_feedforward_alone_')}.toml")
        for table in ("feedback", "rule", "sweep"):  # without noise, the seeds change nothing
            del combined[table]
        assert load(path) == combined
