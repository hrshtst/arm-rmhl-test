# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Shared fixtures: the two-link arm and the reach of the first experiment, and running a runner."""

import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tomli_w

from arm_rmhl_test.storage import ENV_VAR, REPO_ROOT

# The runners are scripts in experiments/; the tests import them as modules of that directory.
sys.path.insert(0, str(REPO_ROOT / "experiments"))

# arm-esn-ctrl's v2 arm and reach: from (30, 30) deg to the hand target (-0.6, 0.4) m.
CONFIG = """
[initial]
q = [30.0, 30.0]

[skeleton]
base_length = 0.0

[[skeleton.link]]
length = 0.5
mass = 0.5
inertia = 0.0125
com = [0.25, 0.0]
limits = [-180.0, 180.0]

[[skeleton.link]]
length = 0.4
mass = 0.4
inertia = 0.0064
com = [0.2, 0.0]
limits = [-180.0, 180.0]

[simulator]
dt = 0.002
stops = "locked"

[reach]
target = [-0.6, 0.4]
move = 1.0
duration = 2.0
control_period = 0.01

[command]
omega = 5.0
damping_ratio = 0.7
"""


@pytest.fixture
def config() -> dict[str, Any]:
    """A fresh copy of the configuration, safe to change in a test."""
    return tomllib.loads(CONFIG)


Runner = Callable[..., Path]


@pytest.fixture
def run_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Runner:
    """Run a runner's ``main`` on a configuration, with options, in an empty storage root; return its run directory."""
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "store"))
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    runs = tmp_path / "store" / "results" / experiment.name

    def run(main: Callable[[], None], config: dict[str, Any], *options: str) -> Path:
        path = experiment / "test.toml"
        path.write_text(tomli_w.dumps(config))
        before = set(runs.iterdir()) if runs.exists() else set()
        monkeypatch.setattr(sys, "argv", ["runner", str(path), *options])
        main()
        (run_dir,) = set(runs.iterdir()) - before
        return run_dir

    return run
