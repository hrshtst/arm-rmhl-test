# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The feedback_without_constant configurations follow its protocol (see its README.md)."""

import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import CONFIG

from arm_rmhl_test.storage import REPO_ROOT
from arm_rmhl_test.sweeps import expand

EXPERIMENT = REPO_ROOT / "experiments/feedback_without_constant"
DIRECTIONAL = REPO_ROOT / "experiments/directional_forgetting"
CONFIGS = sorted(path for path in EXPERIMENT.glob("*.toml") if not path.stem.startswith("compare_"))  # runs of the arm
SHARED = ("initial", "skeleton", "simulator", "reach", "command")


def load(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.mark.parametrize("path", CONFIGS, ids=lambda path: path.stem)
def test_every_configuration_is_on_the_arm_the_reach_and_the_weak_pd_without_the_feedbacks_constant(path: Path):
    config = load(path)
    expected = tomllib.loads(CONFIG)

    for table in SHARED:
        assert config[table] == expected[table]
    assert config["feedback"]["constant"] is False
    expand(config)  # every swept setting is in the configuration


@pytest.mark.parametrize("scale", ["raw", "inertia"])
def test_a_final_run_is_directional_forgettings_but_for_the_feedbacks_constant(scale: str):
    config = load(EXPERIMENT / f"final_concurrent_{scale}.toml")

    assert config["feedback"].pop("constant") is False
    assert config == load(DIRECTIONAL / f"final_concurrent_{scale}.toml")
