# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for training runs of the decorrelated rule again, recording the matrix its update divides by."""

import csv
from pathlib import Path
from typing import Any

import learn_combined
import learn_feedback
import numpy as np
import pytest
import record_decorrelation
from conftest import Runner
from record_decorrelation import residual_from_rule

SEEDS = [1, 2]


def decorrelated(config: dict[str, Any], *, feedforward: bool) -> dict[str, Any]:
    """A short sweep over two seeds of the decorrelated feedback without the constant, with or without a feedforward."""
    config["reach"]["duration"] = 0.3
    config["feedback"] = {"scale": "inertia", "constant": False}
    config["rule"] = {
        "preset": "burms2015",
        "learning_rate": 50.0,
        "decorrelation": 1.0,
        "exploration": {"distribution": "gaussian", "amplitude": 8.0, "seed": 1},
    }
    config["training"] = {"trials": 4, "dead_zone": 0.0, "evaluate_every": 2, "evaluate_all_until": 1}
    config["sweep"] = {"rule.exploration.seed": SEEDS}
    if feedforward:
        config["readout"] = {"forgetting": 0.999, "delta": 10.0, "forgetting_method": "directional"}
        config["schedule"] = {"kind": "concurrent", "handover": 100}
    return config


def recorded(run_runner: Runner, runs: list[Path], trials: int) -> Path:
    arms = [{"run": f"results/{run.name}", "label": run.name} for run in runs]
    return run_runner(record_decorrelation.main, {"arm": arms, "training": {"trials": trials}})


def test_both_runners_trainings_are_reproduced_and_their_c_recorded(config: dict[str, Any], run_runner: Runner):
    both = run_runner(learn_combined.main, decorrelated(config, feedforward=True))
    alone = run_runner(learn_feedback.main, decorrelated(config, feedforward=False))

    run_dir = recorded(run_runner, [both, alone], trials=3)

    with np.load(run_dir / "decorrelation.npz") as result:
        eigenvalues, errors, residual = result["eigenvalues"], result["errors"], result["residual"]
        assert list(result["ridge"]) == [1.0, 1.0]
    assert eigenvalues.shape == (2, len(SEEDS), 3, 4)  # arms, trainings, reaches, the error's four inputs
    assert np.all(eigenvalues >= 0) and np.all(np.diff(eigenvalues, axis=3) <= 0)  # largest first
    for arm, run in enumerate([both, alone]):
        with np.load(run / "training.npz") as stored:
            np.testing.assert_array_equal(errors[arm], stored["errors"][:, :3])
    assert residual.shape == (2, len(SEEDS), 2) and residual.max() < 1e-9
    with (run_dir / "arms.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [(row["run"], row["trainings"]) for row in rows] == [(both.name, "2"), (alone.name, "2")]
    assert "above_after_1" in rows[0] and "above_after_10" not in rows[0]  # only the reaches recorded
    assert (run_dir / "decorrelation.png").stat().st_size > 0


def test_a_stored_error_that_is_not_reproduced_stops_the_recording(config: dict[str, Any], run_runner: Runner):
    run = run_runner(learn_feedback.main, decorrelated(config, feedforward=False))
    with np.load(run / "training.npz") as stored:
        arrays = dict(stored)
    arrays["errors"][1, 1] += 1e-12
    np.savez_compressed(run / "training.npz", **arrays)

    with pytest.raises(RuntimeError, match="combination 1: reach 2 gives"):
        recorded(run_runner, [run], trials=3)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"rule.decorrelation": False}, "not decorrelated"),
        ({"feedback.constant": True}, "has the constant"),
    ],
)
def test_a_run_without_the_check_is_refused(
    config: dict[str, Any], run_runner: Runner, change: dict[str, Any], message: str
):
    config = decorrelated(config, feedforward=False)
    for path, value in change.items():
        table, key = path.split(".")
        config[table][key] = value
    run = run_runner(learn_feedback.main, config)

    with pytest.raises(ValueError, match=message):
        recorded(run_runner, [run], trials=2)


def test_the_residual_is_zero_along_the_rules_direction_and_not_off_it():
    rng = np.random.default_rng(0)
    inputs = rng.normal(size=(30, 4))
    c, e = inputs.T @ inputs, rng.normal(size=(4, 2))
    now = {"weights": rng.normal(size=(4, 2)), "C": c, "E": e}
    direction = np.linalg.solve(c + 2.0 * np.eye(4), e)

    along = {"weights": now["weights"] - 0.3 * direction}
    plain = {"weights": now["weights"] - 0.3 * e}  # the plain rule's change

    assert residual_from_rule(now, along, ridge=2.0) < 1e-12
    assert residual_from_rule(now, plain, ridge=2.0) > 0.01
    assert residual_from_rule(now, {"weights": now["weights"]}, ridge=2.0) == 0.0  # no change at all
