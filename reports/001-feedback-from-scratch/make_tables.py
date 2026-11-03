# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 001 from the copies of its runs.

    uv run python reports/001-feedback-from-scratch/make_tables.py

From the runs under ``results/`` (configurations, ``runs.csv``, ``training.npz``,
and ``grid.csv``), it prints, as Markdown:

- the tuning: per rule and variant, round by round, the settings tried, the
  outcomes, and the closest setting with its noise-free error at 1,000 trials
  (Section 3.2);
- the final runs: per rule and variant, each seed's noise-free error at 1,000 and
  3,000 trials, and their median (Section 3.3);
- the learned feedback read as joint PD gains: per rule and variant, the median
  over the seeds of each joint's natural frequency and damping ratio, the PD's and
  the feedback's together, and the size of the cross-joint gains (Section 3.4);
- the effort: the final feedback of each seed that improved, replayed without
  noise, against the PDs: the squared torque integrated over the reach and the
  peak torque (Section 3.4);
- the PDs that the results are compared with (Section 3.1).

The replay checks that it reproduces each final run's last noise-free error.
"""

from __future__ import annotations

import argparse
import csv
import tomllib
from pathlib import Path
from typing import Any

import numpy as np

from arm_rmhl_test.arm import command_gains, effort, make_arm, make_reach
from arm_rmhl_test.feedback import feedback_scale, make_model, make_rule, run_trial, split_weights

HERE = Path(__file__).resolve().parent
CHECKPOINTS = (1000, 3000)  # trials learned from, in the final runs
MARKED_PDS = ((10.0, 0.7), (20.0, 0.7), (28.0, 0.7))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="the runs' directory")
    args = parser.parse_args()

    runs = sorted(path for path in args.results.iterdir() if (path / "config.toml").exists())
    print("## The PDs\n")
    print_pds(next(run for run in runs if run.name.endswith("-pd_grid")))
    print("\n## Tuning\n")
    print_tuning([run for run in runs if "-tune_" in run.name])
    finals = [run for run in runs if "-final_" in run.name]
    print("\n## Final runs\n")
    print_finals(finals)
    print("\n## Learned gains\n")
    print_gains(finals)
    print("\n## Effort\n")
    print_effort(finals, next(run for run in runs if run.name.endswith("-pd_grid")))


def load_config(run: Path) -> dict[str, Any]:
    with (run / "config.toml").open("rb") as f:
        return tomllib.load(f)


def load_rows(run: Path, name: str) -> list[dict[str, str]]:
    with (run / name).open() as f:
        return list(csv.DictReader(f))


def arm_name(config: dict[str, Any]) -> str:
    """The rule and the variant of a configuration, such as ``"decorrelated, inertia-scaled"``."""
    rule = "plain" if config["rule"].get("decorrelation") is False else "decorrelated"
    variant = "inertia-scaled" if config.get("feedback", {}).get("scale") == "inertia" else "raw torque"
    return f"{rule}, {variant}"


def print_pds(run: Path) -> None:
    grid = {
        (float(row["command.omega"]), float(row["command.damping_ratio"])): float(row["tracking_error_m"])
        for row in load_rows(run, "grid.csv")
    }
    (omega, ratio), closest = min(grid.items(), key=lambda item: item[1])
    weak = grid[5.0, 0.7]
    print("| PD | Tracking error |\n| --- | ---: |")
    print(f"| the weak PD, 5 rad/s, 0.7 | {1000 * weak:.1f} mm |")
    for marked in MARKED_PDS:
        print(f"| {marked[0]:g} rad/s, {marked[1]:g} | {1000 * grid[marked]:.1f} mm |")
    print(f"| the closest, {omega:g} rad/s, {ratio:g} | {1000 * closest:.1f} mm |")


def print_tuning(runs: list[Path]) -> None:
    print("| Run | Rule, feedback | Amplitudes | Learning rates | Improved / worse / diverged | Closest | Error |")
    print("| --- | --- | --- | --- | --- | --- | ---: |")
    # By rule and variant, then in the order the rounds ran.
    for run in sorted(runs, key=lambda run: (arm_name(load_config(run)), run.name)):
        config = load_config(run)
        rows = load_rows(run, "runs.csv")
        unit = "rad/s^2" if config.get("feedback", {}).get("scale") == "inertia" else "N m"
        outcomes = [row["outcome"] for row in rows]
        counts = " / ".join(str(outcomes.count(outcome)) for outcome in ("improved", "worse", "diverged"))
        improved = [row for row in rows if row["outcome"] == "improved"]
        best = min(improved, key=lambda row: float(row["final_error_m"]))
        sweep = config["sweep"]
        print(
            f"| `{run.name}` | {arm_name(config)}"
            f" | {_values(sweep['rule.exploration.amplitude'])} {unit} | {_values(sweep['rule.learning_rate'])}"
            f" | {counts} | {float(best['rule.exploration.amplitude']):g} {unit},"
            f" {float(best['rule.learning_rate']):g} | {1000 * float(best['final_error_m']):.1f} mm |"
        )


def print_finals(runs: list[Path]) -> None:
    seeds = [int(row["rule.exploration.seed"]) for row in load_rows(runs[0], "runs.csv")]
    columns = " | ".join(f"seed {seed}" for seed in seeds)
    print(f"| Rule, feedback | Trials | {columns} | Median |")
    print(f"| --- | ---: | {' | '.join('---:' for _ in seeds)} | ---: |")
    for run in runs:
        config = load_config(run)
        with np.load(run / "training.npz") as data:
            evaluated_at, evaluations = data["evaluated_at"], data["evaluations"]
        for checkpoint in CHECKPOINTS:
            column = int(np.flatnonzero(evaluated_at == checkpoint)[0])
            errors = evaluations[:, column]
            # A training that diverged before the checkpoint is infinitely far from the reference.
            errors = np.where(np.isnan(errors), np.inf, errors)
            cells = " | ".join(_millimeters(error) for error in errors)
            print(f"| {arm_name(config)} | {checkpoint:,} | {cells} | {_millimeters(float(np.median(errors)))} |")


def print_gains(runs: list[Path]) -> None:
    """Each joint's natural frequency and damping ratio of the PD's and the feedback's diagonal gains together."""
    print("| Rule, feedback | omega 1 (rad/s) | zeta 1 | omega 2 (rad/s) | zeta 2 | cross gains |")
    print("| --- | ---: | ---: | ---: | ---: | --- |")
    for run in runs:
        config = load_config(run)
        arm = make_arm(config)
        kp, kd = command_gains(config, arm)
        inertia = kp / float(config["command"]["omega"]) ** 2
        with np.load(run / "training.npz") as data:
            final = data["scale"][:, None, :] * data["weights"][:, -1]  # the torque's weights, per seed
        omegas, ratios, cross = [], [], []
        for weights in final:
            stiffness, damping, _ = split_weights(weights)
            k = np.diag(stiffness) + kp
            d = np.diag(damping) + kd
            omega = np.sqrt(np.maximum(k, 0.0) / inertia)
            omegas.append(omega)
            ratios.append(d / (2.0 * inertia * np.where(omega > 0, omega, np.nan)))
            # How large the cross-joint gains are against the diagonal ones, in the stiffness and the damping.
            cross.append(
                (
                    np.abs(stiffness - np.diag(np.diag(stiffness))).max() / np.abs(k).max(),
                    np.abs(damping - np.diag(np.diag(damping))).max() / np.abs(d).max(),
                )
            )
        omega, ratio = np.nanmedian(omegas, axis=0), np.nanmedian(ratios, axis=0)
        k_cross, d_cross = np.nanmedian(cross, axis=0)
        print(
            f"| {arm_name(config)} | {omega[0]:.1f} | {ratio[0]:.2f} | {omega[1]:.1f} | {ratio[1]:.2f}"
            f" | stiffness {k_cross:.0%}, damping {d_cross:.0%} of the largest diagonal gain |"
        )


def print_effort(runs: list[Path], grid_run: Path) -> None:
    """The effort and the peak torque of each final feedback that improved, replayed without noise, and of the PDs."""
    print("| Controller | Tracking error | Effort (N^2 m^2 s) | Peak torque (N m) |")
    print("| --- | ---: | ---: | ---: |")
    grid = {
        (float(row["command.omega"]), float(row["command.damping_ratio"])): row
        for row in load_rows(grid_run, "grid.csv")
    }
    for marked in ((5.0, 0.7), *MARKED_PDS):
        row = grid[marked]
        print(
            f"| PD, {marked[0]:g} rad/s, {marked[1]:g} | {1000 * float(row['tracking_error_m']):.1f} mm"
            f" | {float(row['effort']):.2f} | {float(row['peak_torque_nm']):.2f} |"
        )
    for run in runs:
        config = load_config(run)
        arm = make_arm(config)
        reach = make_reach(config, arm)
        kp, kd = command_gains(config, arm)
        scale = feedback_scale(config, arm)
        rows = load_rows(run, "runs.csv")
        with np.load(run / "training.npz") as data:
            weights, evaluations = data["weights"][:, -1], data["evaluations"][:, -1]
        errors, efforts, peaks = [], [], []
        for row, final, expected in zip(rows, weights, evaluations, strict=True):
            if row["outcome"] != "improved":
                continue
            model = make_model(make_rule(config["rule"]), arm.num_joints)
            model.get_readout().setWeights(final)
            error, reached = run_trial(model, arm, reach, kp, kd, 0.0, scale=scale, explore=False)
            if error != expected:
                msg = f"the replay of {run.name}, seed {row['rule.exploration.seed']}, gives {error}, not {expected}"
                raise RuntimeError(msg)
            errors.append(error)
            efforts.append(effort(reached, reach))
            peaks.append(float(np.abs(reached.tau).max()))
        print(
            f"| {arm_name(config)}, median of {len(errors)} improved | {1000 * float(np.median(errors)):.1f} mm"
            f" | {np.median(efforts):.2f} | {np.median(peaks):.2f} |"
        )


def _values(values: list[float]) -> str:
    return ", ".join(f"{value:g}" for value in values)


def _millimeters(error: float) -> str:
    return "diverged" if not np.isfinite(error) else f"{1000 * error:.1f} mm"


if __name__ == "__main__":
    main()
