# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 003 from the copies of its runs and of reports 001's and 002's.

    uv run python reports/003-combined-learning/make_tables.py

From the runs under ``results/`` (combined_learning's tuning, final runs, and
wind-up sweep), ``../001-feedback-from-scratch/results/`` (the PD grid and the
decorrelated rule's runs of 10,000 trials), and
``../002-feedback-error-learning/results/`` (feedback-error learning's final run),
it prints, as Markdown:

- the tuning: for each schedule and feedback scale, the setting with the lowest
  error at 1,000 trials over every tuning run that the protocol allows, which must
  be the setting of the variant's final runs (Section 3.1);
- the wind-up: for each forgetting factor and ``delta`` of the feedforward alone,
  the error at 100, 1,000, and 3,000 trials, and the trials from which it stays
  worse than the PD alone, also times one minus the forgetting factor; and the
  singular values of the feedforward's inputs over the reach (Section 3.2);
- the final runs: for every learner, the median error over its seeds at matched
  budgets, how many seeds improved, the error of each seed at 10,000 trials, and
  the trials from which the median stays closer than the PDs (Section 3.3);
- the effort: every controller replayed without noise, with the learners' weights
  at their last evaluation, as medians over the seeds that improved on the PD alone
  (a run-away's torques say nothing of the learned controller): the
  tracking error, the squared torque integrated over the reach, the peak torque, the
  torque's variation from one control period to the next summed over the reach and
  the joints, and the root mean square of each part's torque, the PD's, the
  feedforward's, and the feedback's (Section 3.4);
- the lesions: each combined final controller replayed as learned, without its
  feedback, and without its feedforward, medians over the seeds that improved
  (Section 3.5);
- the feedback's gains: the diagonals of its stiffness and damping matrices and its
  constant torque, medians over the seeds that improved, combined and alone
  (Section 3.5).

The replays check that they reproduce each run's last evaluation and each PD's
tracking error in the grid.
"""

from __future__ import annotations

import argparse
import csv
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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
from arm_rmhl_test.combined import combine
from arm_rmhl_test.feedback import feedback_scale, feedback_torque, make_model, make_rule
from arm_rmhl_test.sweeps import expand

HERE = Path(__file__).resolve().parent
REPORT_001 = HERE.parent / "001-feedback-from-scratch" / "results"
REPORT_002 = HERE.parent / "002-feedback-error-learning" / "results"
MATCHED = (10, 100, 1000, 3000, 10000)
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
EFFORT_PDS = ((5.0, 0.7), (20.0, 0.7), (28.0, 0.7), (40.0, 0.4), (80.0, 0.2))
SCALES = {"none": "raw torque", "inertia": "inertia-scaled"}
COMBINED = {  # label: the run's name ends with this; the latest such run is the current one
    "combined, concurrent, raw torque": "-final_concurrent_raw",
    "combined, staged, raw torque": "-final_staged_raw",
    "combined, concurrent, inertia-scaled": "-final_concurrent_inertia",
    "combined, staged, inertia-scaled": "-final_staged_inertia",
}
ALONE = {
    "feedback alone, raw torque": "-final_feedback_alone_raw",
    "feedback alone, inertia-scaled": "-final_feedback_alone_inertia",
    "feedforward alone, no forgetting, delta 100": "-final_feedforward_alone_raw",
    "feedforward alone, no forgetting, delta 10": "-final_feedforward_alone_inertia",
    "feedforward alone, report 002's setting": "-final_feedforward_alone",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    parser.add_argument("--report-001", type=Path, default=REPORT_001, help="report 001's runs")
    parser.add_argument("--report-002", type=Path, default=REPORT_002, help="report 002's runs")
    args = parser.parse_args()

    finals = {label: latest(args.results, suffix) for label, suffix in (COMBINED | ALONE).items()}
    grid = latest(args.report_001, "-pd_grid")
    references = {
        "RMHL decorrelated alone, raw torque, report 001": latest(args.report_001, "-long_decorrelated_raw"),
        "RMHL decorrelated alone, inertia-scaled, report 001": latest(args.report_001, "-long_decorrelated_inertia"),
        "feedback-error learning alone, report 002": latest(args.report_002, "-final"),
    }
    print("## Tuning\n")
    print_tuning(args.results, finals)
    print("\n## The wind-up\n")
    windup = latest(args.results, "-windup_feedforward_alone")
    print_windup(windup)
    print_inputs(load_config(windup))
    print("\n## The final runs\n")
    print_matched(finals | references, grid)
    print("\n## Effort\n")
    print_effort(finals | references, grid)
    print("\n## Lesions\n")
    print_lesions({label: finals[label] for label in COMBINED})
    print("\n## The feedback's gains\n")
    print_gains({label: run for label, run in (finals | references).items() if "rule" in load_config(run)})


def latest(results: Path, suffix: str) -> Path:
    """The latest finished run under ``results`` whose name ends with ``suffix``: names start with the time."""
    runs = sorted(path for path in results.iterdir() if path.name.endswith(suffix) and _complete(path))
    if not runs:
        msg = f"no run ending with {suffix!r} under {results}"
        raise FileNotFoundError(msg)
    return runs[-1]


def load_config(run: Path) -> dict[str, Any]:
    with (run / "config.toml").open("rb") as f:
        return tomllib.load(f)


def load_rows(run: Path, name: str = "runs.csv") -> list[dict[str, str]]:
    with (run / name).open() as f:
        return list(csv.DictReader(f))


def load_training(run: Path) -> dict[str, Array]:
    with np.load(run / "training.npz") as data:
        return dict(data)


def setting(config: dict[str, Any]) -> tuple[Any, ...]:
    """What tuning chooses: the feedback's learning rate and amplitude, the feedforward's forgetting and delta."""
    return (
        config["rule"]["learning_rate"],
        config["rule"]["exploration"]["amplitude"],
        config["readout"]["forgetting"],
        config["readout"]["delta"],
    )


def print_tuning(results: Path, finals: dict[str, Path]) -> None:
    candidates: dict[tuple[str, str], list[tuple[float, tuple[Any, ...], str]]] = {}
    for run in sorted(path for path in results.iterdir() if "-tune_" in path.name and _complete(path)):
        data = load_training(run)
        at_1000 = data["evaluations"][:, data["evaluated_at"] == 1000][:, 0]
        for (_, config), error in zip(expand(load_config(run)), at_1000, strict=True):
            kind, scale = config["schedule"]["kind"], config["feedback"]["scale"]
            if kind == "concurrent" and config["readout"]["forgetting"] != 1.0:
                continue  # the protocol's step 1.4: below 1, the feedforward winds up
            candidates.setdefault((kind, scale), []).append((float(error), setting(config), run.name))
    print("| Variant | Feedback: learning rate, amplitude | Feedforward: forgetting, delta | Error at 1,000 trials |")
    print("| --- | ---: | ---: | ---: |")
    for (kind, scale), runs in sorted(candidates.items()):
        error, (rate, amplitude, forgetting, delta), _ = min(runs, key=lambda candidate: candidate[0])
        final = finals[f"combined, {kind}, {SCALES[scale]}"]
        if setting(load_config(final)) != (rate, amplitude, forgetting, delta):
            msg = f"{final.name} does not run the tuned setting {(rate, amplitude, forgetting, delta)}"
            raise RuntimeError(msg)
        unit = "N m" if scale == "none" else "rad/s^2"
        print(
            f"| {kind}, {SCALES[scale]} | {rate:,g}, {amplitude:g} {unit} | {forgetting:g}, {delta:g}"
            f" | {_mm(error, 2)} |"
        )


def print_windup(run: Path) -> None:
    data = load_training(run)
    at = data["evaluated_at"]
    pd = float(data["evaluations"][0, 0])
    print(
        "| Forgetting factor | delta | 100 trials | 1,000 trials | 3,000 trials"
        " | Worse than the PD alone from trial | Times (1 - forgetting) |"
    )
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for (_, config), evaluations in zip(expand(load_config(run)), data["evaluations"], strict=True):
        forgetting, delta = config["readout"]["forgetting"], config["readout"]["delta"]
        worse = ~(evaluations < pd)  # a divergence counts as worse
        start = next((int(at[i]) for i in range(1, len(at)) if worse[i:].all()), None)
        product = "" if start is None or forgetting == 1.0 else f"{start * (1 - forgetting):.3g}"
        cells = " | ".join(_mm(evaluations[at == trials][0]) for trials in (100, 1000, 3000))
        print(f"| {forgetting:g} | {delta:g} | {cells} | {'never' if start is None else f'{start:,}'} | {product} |")


def print_inputs(config: dict[str, Any]) -> None:
    arm = make_arm(config)
    reach = make_reach(config, arm)
    inputs = feedforward.reference_inputs(reach)
    inputs = np.hstack([inputs, np.ones((len(inputs), 1))])  # the readout's bias
    values = np.linalg.svd(inputs, compute_uv=False)
    print(
        f"\nThe singular values of the feedforward's inputs, `[q_ref, dq_ref, ddq_ref, 1]` at the start of"
        f" each of the reach's {len(inputs)} control periods: {', '.join(f'{value:.3g}' for value in values)}."
    )


def print_matched(runs: dict[str, Path], grid: Path) -> None:
    print(f"| Learner | Seeds improved | {' | '.join(f'{trials:,} trials' for trials in MATCHED)} |")
    print(f"| --- | ---: | {' | '.join('---:' for _ in MATCHED)} |")
    curves = {}
    for label, run in runs.items():
        data = load_training(run)
        at, evaluations = data["evaluated_at"], data["evaluations"]
        curves[label] = at, np.median(evaluations, axis=0)
        outcomes = [row["outcome"] for row in load_rows(run)]
        cells = " | ".join(_mm(curves[label][1][at == trials][0]) if trials in at else "" for trials in MATCHED)
        print(f"| {label} | {outcomes.count('improved')} of {len(outcomes)} | {cells} |")

    print("\nThe error of each seed at the end of its run, 10,000 trials but for report 002's 1,000:\n")
    print("| Learner | Seed 1 | Seed 2 | Seed 3 | Seed 4 | Seed 5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for label, run in runs.items():
        last = load_training(run)["evaluations"][:, -1]
        if len(last) > 1:
            print(f"| {label} | {' | '.join(_mm(error) for error in last)} |")

    pds = _grid_errors(grid)
    print("\nThe trials from which the median stays closer than a PD:\n")
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


@dataclass(frozen=True)
class Replay:
    """One reach without noise, and each part's torque over it."""

    error: float
    run: ReachRun
    reach: Reach
    feedforward: Array  # (steps, joints), zero without one
    feedback: Array


def replay(config: dict[str, Any], feedforward_weights: Array | None, feedback_weights: Array | None) -> Replay:
    """The reach under the configuration's weak PD and the learners with these weights, frozen and without noise."""
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    parts: dict[str, list[Array]] = {"feedforward": [], "feedback": []}
    ff = fb = None
    if feedforward_weights is not None:
        ff = _recorded(feedforward.frozen_feedforward(feedforward_weights, reach), parts["feedforward"])
    if feedback_weights is not None:
        model = make_model(make_rule(config["rule"]), arm.num_joints)
        model.get_readout().setWeights(feedback_weights)
        fb = _recorded(feedback_torque(model, feedback_scale(config, arm), explore=False), parts["feedback"])
    run = run_reach(arm, reach, kp, kd, combine(ff, fb))
    zeros = np.zeros((reach.steps, arm.num_joints))
    return Replay(
        tracking_error(run, reach),
        run,
        reach,
        np.array(parts["feedforward"]) if parts["feedforward"] else zeros,
        np.array(parts["feedback"]) if parts["feedback"] else zeros,
    )


def learned_weights(run: Path) -> list[tuple[Array | None, Array | None, float]]:
    """Each training's feedforward and feedback weights at its last evaluation, and that evaluation's error."""
    config, data = load_config(run), load_training(run)
    if "feedforward_weights" in data:  # a run of learn_combined.py
        ff = data["feedforward_weights"][:, -1] if "readout" in config else None
        fb = data["weights"][:, -1] if "rule" in config else None
    elif "rule" in config:  # learn_feedback.py
        ff, fb = None, data["weights"][:, -1]
    else:  # learn_feedforward.py
        ff, fb = data["weights"][:, -1], None
    last = data["evaluations"][:, -1]
    return [(None if ff is None else ff[i], None if fb is None else fb[i], float(last[i])) for i in range(len(last))]


def improved(run: Path) -> list[bool]:
    """Whether each training of the run ended closer than the PD alone."""
    return [row["outcome"] == "improved" for row in load_rows(run)]


def replays(run: Path) -> list[Replay]:
    """The run's improved trainings replayed with their last weights, each checked against its last evaluation."""
    config = load_config(run)
    done = []
    for seed, ((ff, fb, expected), kept) in enumerate(zip(learned_weights(run), improved(run), strict=True)):
        if not kept:
            continue  # a run-away's torques say nothing of the learned controller
        result = replay(config, ff, fb)
        _check(result.error, expected, f"{run.name}, training {seed + 1}")
        done.append(result)
    return done


def print_effort(runs: dict[str, Path], grid: Path) -> None:
    columns = (
        "Tracking error",
        "Effort (N^2 m^2 s)",
        "Peak torque (N m)",
        "Torque variation (N m)",
        "PD's torque, RMS (N m)",
        "Feedforward's, RMS (N m)",
        "Feedback's, RMS (N m)",
    )
    print(f"| Controller | {' | '.join(columns)} |")
    print(f"| --- | {' | '.join('---:' for _ in columns)} |")
    grid_config = load_config(grid)
    pds = _grid_errors(grid)
    for omega, ratio in EFFORT_PDS:
        arm = make_arm(grid_config)
        reach = make_reach(grid_config, arm)
        reached = run_reach(arm, reach, *pd_gains(arm, omega, ratio))
        error = tracking_error(reached, reach)
        _check(error, pds[omega, ratio], f"the PD of {omega:g} rad/s and {ratio:g}")
        zeros = np.zeros_like(reached.tau)
        _print_controller(f"PD, {omega:g} rad/s, {ratio:g}", [Replay(error, reached, reach, zeros, zeros)])
    for label, run in runs.items():
        if done := replays(run):
            _print_controller(f"{label} ({len(done)} of {len(improved(run))})", done)


def print_lesions(runs: dict[str, Path]) -> None:
    print("| Combined controller | As learned | Without its feedback | Without its feedforward |")
    print("| --- | ---: | ---: | ---: |")
    for label, run in runs.items():
        config = load_config(run)
        errors: list[list[float]] = [[], [], []]
        for (ff, fb, expected), kept in zip(learned_weights(run), improved(run), strict=True):
            if not kept:
                continue
            for column, (kept_ff, kept_fb) in zip(errors, ((ff, fb), (ff, None), (None, fb)), strict=True):
                column.append(replay(config, kept_ff, kept_fb).error)
            _check(errors[0][-1], expected, run.name)
        if errors[0]:
            cells = " | ".join(_mm(float(np.median(column))) for column in errors)
            print(f"| {label} ({len(errors[0])} of {len(improved(run))}) | {cells} |")


def print_gains(runs: dict[str, Path]) -> None:
    gains = ("stiffness_11", "stiffness_22", "damping_11", "damping_22", "constant_1", "constant_2")
    print(
        "| Feedback | Stiffness (N m/rad): joint 1 | joint 2 | Damping (N m s/rad): joint 1 | joint 2"
        " | Constant (N m): joint 1 | joint 2 |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for label, run in runs.items():
        rows = [  # learn_combined.py names the feedback's constant apart from the feedforward's
            {key.removeprefix("feedback_"): value for key, value in row.items()}
            for row in load_rows(run)
            if row["outcome"] == "improved"
        ]
        if rows:
            cells = " | ".join(f"{np.median([float(row[gain]) for row in rows]):.3g}" for gain in gains)
            print(f"| {label} ({len(rows)} of {len(load_rows(run))}) | {cells} |")


def _complete(run: Path) -> bool:
    """Whether the run finished: a run directory gets its outputs at the end."""
    return (run / "config.toml").exists() and ((run / "training.npz").exists() or (run / "grid.csv").exists())


def _recorded(torque: Callable[[Array], Array], record: list[Array]) -> Callable[[Array], Array]:
    def recording(error: Array) -> Array:
        value = torque(error)
        record.append(np.array(value, dtype=float))
        return value

    return recording


def _grid_errors(grid: Path) -> dict[tuple[float, float], float]:
    return {
        (float(row["command.omega"]), float(row["command.damping_ratio"])): float(row["tracking_error_m"])
        for row in load_rows(grid, "grid.csv")
    }


def _print_controller(label: str, done: list[Replay]) -> None:
    """The medians over the replays of a controller."""

    def rms(torque: Array) -> float:
        return float(np.sqrt(np.mean(torque**2)))

    columns = [
        [replay.error for replay in done],
        [effort(replay.run, replay.reach) for replay in done],
        [float(np.abs(replay.run.tau).max()) for replay in done],
        [float(np.abs(np.diff(replay.run.tau, axis=0)).sum()) for replay in done],
        [rms(replay.run.tau - replay.run.feedback) for replay in done],
        [rms(replay.feedforward) for replay in done],
        [rms(replay.feedback) for replay in done],
    ]
    error, work, peak, variation, pd, ff, fb = (float(np.median(column)) for column in columns)
    print(f"| {label} | {_mm(error)} | {work:.2f} | {peak:.2f} | {variation:.1f} | {pd:.3f} | {ff:.3f} | {fb:.3f} |")


def _check(error: float, expected: float, what: str) -> None:
    if error != expected:
        msg = f"the replay of {what} gives {error}, not {expected}"
        raise RuntimeError(msg)


def _mm(error: float, digits: int = 1) -> str:
    return "not finite" if not np.isfinite(error) else f"{1000 * error:.{digits}f} mm"


if __name__ == "__main__":
    main()
