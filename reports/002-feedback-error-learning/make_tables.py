# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 002 from the copies of its runs and of report 001's.

    uv run python reports/002-feedback-error-learning/make_tables.py

From the runs under ``results/`` (feedback-error learning's tuning and final run)
and under ``../001-feedback-from-scratch/results/`` (the PD grid and the
decorrelated rule's runs of 10,000 trials), it prints, as Markdown:

- the tuning: for each forgetting factor and ``delta``, the tracking error at 10 and
  100 trials, the best and when, and the outcome (Section 3.1);
- the final run: its tracking error at 1 to 1,000 trials (Section 3.2);
- the matched budgets: feedback-error learning against the median of the
  decorrelated rule's five seeds at the trials both evaluated, and the trials from
  which each stays closer than the PDs (Section 3.3);
- the effort: every controller replayed without noise, the PDs, the reward-modulated
  feedback of each seed, the final feedforward, and two reference feedforwards for
  the weak PD: the torque the reference needs, by the arm's inverse dynamics at
  each control period's start, and its least-squares fit by the readout's form.
  For each: the tracking error, the squared torque integrated over the reach, the
  peak torque, the torque's variation from one control period to the next summed
  over the reach and the joints, and the PD's own torque, its root mean square
  (Section 3.4);
- the learned feedforward: its torque per reference acceleration, against the
  arm's mass matrix at the start and at the goal (Section 3.4).

The replays check that they reproduce each run's last evaluation and each PD's
tracking error in the grid.
"""

from __future__ import annotations

import argparse
import csv
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from skelarm import Skeleton
from skelarm.dynamics import compute_inverse_dynamics, compute_mass_matrix

from arm_rmhl_test import feedforward
from arm_rmhl_test.arm import (
    Array,
    Reach,
    ReachRun,
    command_gains,
    effort,
    make_arm,
    make_reach,
    pd_gains,
    run_reach,
    tracking_error,
)
from arm_rmhl_test.feedback import feedback_scale, make_model, make_rule, run_trial

HERE = Path(__file__).resolve().parent
REPORT_001 = HERE.parent / "001-feedback-from-scratch" / "results"
FINAL_CHECKPOINTS = (1, 3, 10, 30, 100, 300, 1000)
MATCHED = (20, 100, 1000, 3000, 10000)  # trials both learners evaluated, or the reward-modulated alone beyond 1,000
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
EFFORT_PDS = ((5.0, 0.7), (20.0, 0.7), (28.0, 0.7), (40.0, 0.4), (80.0, 0.2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    parser.add_argument("--report-001", type=Path, default=REPORT_001, help="report 001's runs")
    args = parser.parse_args()

    tune = only(args.results, "-tune")
    final = only(args.results, "-final")
    grid = only(args.report_001, "-pd_grid")
    rmhl = {
        "raw torque": only(args.report_001, "-long_decorrelated_raw"),
        "inertia-scaled": only(args.report_001, "-long_decorrelated_inertia"),
    }
    print("## Tuning\n")
    print_tuning(tune)
    print("\n## The final run\n")
    print_final(final)
    print("\n## Matched budgets\n")
    print_matched(final, rmhl, grid)
    print("\n## Effort\n")
    print_effort(final, rmhl, grid)
    print("\n## The learned feedforward\n")
    print_feedforward(final)


def only(results: Path, suffix: str) -> Path:
    """The one run under ``results`` whose name ends with ``suffix``."""
    (run,) = [path for path in results.iterdir() if path.name.endswith(suffix) and (path / "config.toml").exists()]
    return run


def load_config(run: Path) -> dict[str, Any]:
    with (run / "config.toml").open("rb") as f:
        return tomllib.load(f)


def load_rows(run: Path, name: str) -> list[dict[str, str]]:
    with (run / name).open() as f:
        return list(csv.DictReader(f))


def load_training(run: Path) -> dict[str, Array]:
    with np.load(run / "training.npz") as data:
        return dict(data)


def print_tuning(run: Path) -> None:
    data = load_training(run)
    at = data["evaluated_at"]
    print("| Forgetting factor | delta | 10 trials | 100 trials | Best (after trials) | Outcome |")
    print("| ---: | ---: | ---: | ---: | ---: | --- |")
    for row, evaluations in zip(load_rows(run, "runs.csv"), data["evaluations"], strict=True):
        print(
            f"| {float(row['readout.forgetting']):g} | {float(row['readout.delta']):g}"
            f" | {_mm(evaluations[at == 10][0])} | {_mm(evaluations[at == 100][0])}"
            f" | {_mm(float(row['best_error_m']))} ({row['best_after']}) | {row['outcome']} |"
        )


def print_final(run: Path) -> None:
    data = load_training(run)
    at, (evaluations,) = data["evaluated_at"], data["evaluations"]
    (row,) = load_rows(run, "runs.csv")
    print(f"| Trials | {' | '.join(f'{checkpoint:,}' for checkpoint in FINAL_CHECKPOINTS)} | Best (after trials) |")
    print(f"| --- | {' | '.join('---:' for _ in FINAL_CHECKPOINTS)} | ---: |")
    cells = " | ".join(_mm(evaluations[at == checkpoint][0]) for checkpoint in FINAL_CHECKPOINTS)
    print(f"| Tracking error | {cells} | {_mm(float(row['best_error_m']))} ({row['best_after']}) |")


def print_matched(final: Path, rmhl: dict[str, Path], grid: Path) -> None:
    curves = {"feedback-error learning, RLS": _curve(final)}
    curves |= {f"RMHL decorrelated, {variant}, median of 5": _curve(run) for variant, run in rmhl.items()}
    print(f"| Learner | {' | '.join(f'{trials:,} trials' for trials in MATCHED)} |")
    print(f"| --- | {' | '.join('---:' for _ in MATCHED)} |")
    for label, (at, errors) in curves.items():
        cells = " | ".join(_mm(errors[at == trials][0]) if trials in at else "" for trials in MATCHED)
        print(f"| {label} | {cells} |")
    pds = _grid_errors(grid)
    print("\nThe trials from which each stays closer than a PD:\n")
    headers = [f"PD, {omega:g} rad/s, {ratio:g} ({_mm(pds[omega, ratio])})" for omega, ratio in MARKED_PDS]
    print(f"| Learner | {' | '.join(headers)} |")
    print(f"| --- | {' | '.join('---:' for _ in MARKED_PDS)} |")
    for label, (at, errors) in curves.items():
        stays_below = []
        for pd in MARKED_PDS:
            below = errors < pds[pd]
            stays = next((int(at[i]) for i in range(len(at)) if below[i:].all()), None)
            stays_below.append("never" if stays is None else f"{stays:,}")
        print(f"| {label} | {' | '.join(stays_below)} |")


def print_effort(final: Path, rmhl: dict[str, Path], grid: Path) -> None:
    columns = (
        "Tracking error",
        "Effort (N^2 m^2 s)",
        "Peak torque (N m)",
        "Torque variation (N m)",
        "PD's torque, RMS (N m)",
    )
    print(f"| Controller | {' | '.join(columns)} |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    grid_config = load_config(grid)
    pds = _grid_errors(grid)
    for omega, ratio in EFFORT_PDS:
        arm = make_arm(grid_config)
        reach = make_reach(grid_config, arm)
        reached = run_reach(arm, reach, *pd_gains(arm, omega, ratio))
        error = tracking_error(reached, reach)
        _check(error, pds[omega, ratio], f"the PD of {omega:g} rad/s and {ratio:g}")
        _print_controller(f"PD, {omega:g} rad/s, {ratio:g}", [(error, reached, reach)])

    for variant, run in rmhl.items():
        config = load_config(run)
        arm = make_arm(config)
        reach = make_reach(config, arm)
        kp, kd = command_gains(config, arm)
        scale = feedback_scale(config, arm)
        data = load_training(run)
        replays = []
        for seed, (weights, expected) in enumerate(
            zip(data["weights"][:, -1], data["evaluations"][:, -1], strict=True)
        ):
            model = make_model(make_rule(config["rule"]), arm.num_joints)
            model.get_readout().setWeights(weights)
            error, reached = run_trial(model, arm, reach, kp, kd, 0.0, scale=scale, explore=False)
            _check(error, expected, f"{run.name}, seed {seed + 1}")
            replays.append((error, reached, reach))
        _print_controller(f"RMHL decorrelated, {variant}, median of 5", replays)

    config = load_config(final)
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    data = load_training(final)
    error, reached = feedforward.run_frozen(data["weights"][0, -1], arm, reach, kp, kd, 0.0)
    _check(error, float(data["evaluations"][0, -1]), final.name)
    _print_controller("feedback-error learning, RLS", [(error, reached, reach)])

    needed = needed_torque(arm, reach)
    inputs = np.hstack((feedforward.reference_inputs(reach), np.ones((reach.steps, 1))))
    fit, *_ = np.linalg.lstsq(inputs, needed, rcond=None)
    for label, torques in (
        ("weak PD + the needed torque", needed),
        ("weak PD + its fit by the readout's form", inputs @ fit),
    ):
        reached = run_reach(arm, reach, kp, kd, _replay(torques))
        _print_controller(label, [(tracking_error(reached, reach), reached, reach)])


def needed_torque(arm: Skeleton, reach: Reach) -> Array:
    """The torque the reference needs at each control period's start, by inverse dynamics: ``(steps, joints)``."""
    torques = np.empty((reach.steps, arm.num_joints))
    for k in range(reach.steps):
        model = arm.clone()
        model.q, model.dq, model.ddq = reach.q_ref[k], reach.dq_ref[k], reach.ddq_ref[k]
        compute_inverse_dynamics(model)
        torques[k] = [link.tau for link in model.links[1:]]
    return torques


def print_feedforward(final: Path) -> None:
    config = load_config(final)
    arm = make_arm(config)
    reach = make_reach(config, arm)
    (row,) = load_rows(final, "runs.csv")
    acceleration = np.array([[float(row[f"acceleration_{i}{k}"]) for k in (1, 2)] for i in (1, 2)])
    goal = arm.clone()
    goal.q = reach.q_ref[-1]
    print("| Matrix (kg m^2) | 11 | 12 | 21 | 22 |")
    print("| --- | ---: | ---: | ---: | ---: |")
    for label, matrix in (
        ("the feedforward's torque per reference acceleration", acceleration),
        ("the mass matrix at the start", compute_mass_matrix(arm)),
        ("the mass matrix at the goal", compute_mass_matrix(goal)),
    ):
        print(f"| {label} | {' | '.join(f'{value:.4f}' for value in np.asarray(matrix).ravel())} |")


def _curve(run: Path) -> tuple[Array, Array]:
    """The trials of each evaluation and the median error over the run's trainings."""
    data = load_training(run)
    return data["evaluated_at"], np.median(data["evaluations"], axis=0)


def _grid_errors(grid: Path) -> dict[tuple[float, float], float]:
    return {
        (float(row["command.omega"]), float(row["command.damping_ratio"])): float(row["tracking_error_m"])
        for row in load_rows(grid, "grid.csv")
    }


def _replay(torques: Array) -> Callable[[Array], Array]:
    steps = iter(torques)
    return lambda _error: next(steps)


def _print_controller(label: str, replays: list[tuple[float, ReachRun, Reach]]) -> None:
    """The medians over the replays of a controller."""
    columns = [
        [error for error, _, _ in replays],
        [effort(reached, reach) for _, reached, reach in replays],
        [float(np.abs(reached.tau).max()) for _, reached, _ in replays],
        [float(np.abs(np.diff(reached.tau, axis=0)).sum()) for _, reached, _ in replays],
        [float(np.sqrt(np.mean((reached.tau - reached.feedback) ** 2))) for _, reached, _ in replays],
    ]
    error, work, peak, variation, pd = (float(np.median(column)) for column in columns)
    print(f"| {label} | {_mm(error)} | {work:.2f} | {peak:.2f} | {variation:.1f} | {pd:.3f} |")


def _check(error: float, expected: float, what: str) -> None:
    if error != expected:
        msg = f"the replay of {what} gives {error}, not {expected}"
        raise RuntimeError(msg)


def _mm(error: float) -> str:
    return "diverged" if not np.isfinite(error) else f"{1000 * error:.1f} mm"


if __name__ == "__main__":
    main()
