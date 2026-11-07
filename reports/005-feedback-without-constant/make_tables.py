# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 005 from the copies of its runs and of reports 001's, 003's and 004's.

    uv run python reports/005-feedback-without-constant/make_tables.py

From the runs under ``results/`` (feedback_without_constant's final runs),
``../004-directional-forgetting/results/`` (directional_forgetting's final runs,
with the feedback's constant, and the feedforward alone),
``../003-combined-learning/results/`` (combined_learning's final runs without
forgetting), and ``../001-feedback-from-scratch/results/`` (the PD grid), it
prints, as Markdown:

- the final runs: for every learner, the median error over its seeds at matched
  budgets, how many seeds improved, the spread of each improved seed's last 50
  evaluations, and the trials from which the median stays closer than the PDs;
  and for each seed of the combined final runs, with the feedback's constant and
  without, the trial from which it stays worse than the PD alone and its error at
  100 and 10,000 trials (Section 3.1);
- the lesions: each combined final controller replayed as learned, without its
  feedback, and without its feedforward; and on each joint, the constant torques,
  the feedback's, the feedforward's bias, and their sum, over the trials; each a
  median over the seeds that improved (Section 3.2);
- the effort: every controller replayed without noise, with the learners' weights
  at their last evaluation, as medians over the seeds that improved on the PD alone
  (a run-away's torques say nothing of the learned controller): the tracking
  error, the squared torque integrated over the reach, the peak torque, the
  torque's variation from one control period to the next summed over the reach and
  the joints, and the root mean square of each part's torque, the PD's, the
  feedforward's, and the feedback's; and the feedback's gains, the diagonals of its
  stiffness and damping matrices and its constant torque (Section 3.3).

It checks that each final run is report 004's but for the feedback's constant, and
that the replays reproduce each run's last evaluation and each PD's tracking error
in the grid.
"""

from __future__ import annotations

import argparse
import copy
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
from arm_rmhl_test.feedback import (
    feedback_constant,
    feedback_scale,
    feedback_torque,
    make_model,
    make_rule,
    set_weights,
)

HERE = Path(__file__).resolve().parent
REPORT_001 = HERE.parent / "001-feedback-from-scratch" / "results"
REPORT_003 = HERE.parent / "003-combined-learning" / "results"
REPORT_004 = HERE.parent / "004-directional-forgetting" / "results"
MATCHED = (10, 100, 1000, 3000, 10000)
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
EFFORT_PDS = ((5.0, 0.7), (20.0, 0.7), (28.0, 0.7), (40.0, 0.4), (80.0, 0.2))
SCALES = {"raw": "raw torque", "inertia": "inertia-scaled"}
# label: (which results, the run's name, or the end of it for the latest such run)
COMBINED = {
    "without the constant, raw torque": ("this", "-final_concurrent_raw"),
    "with the constant, raw torque (report 004)": ("004", "20261107-221827-final_concurrent_raw"),
    "with the constant, no forgetting, raw torque (report 003)": ("003", "20261106-133311-final_concurrent_raw"),
    "without the constant, inertia-scaled": ("this", "-final_concurrent_inertia"),
    "with the constant, inertia-scaled (report 004)": ("004", "20261107-224228-final_concurrent_inertia"),
    "with the constant, no forgetting, inertia-scaled (report 003)": (
        "003",
        "20261106-134705-final_concurrent_inertia",
    ),
}
ALONE = {
    "feedforward alone, delta 100 (report 004)": ("004", "20261107-221827-final_feedforward_alone_raw"),
    "feedforward alone, delta 10 (report 004)": ("004", "20261107-224229-final_feedforward_alone_inertia"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    parser.add_argument("--report-001", type=Path, default=REPORT_001, help="report 001's runs")
    parser.add_argument("--report-003", type=Path, default=REPORT_003, help="report 003's runs")
    parser.add_argument("--report-004", type=Path, default=REPORT_004, help="report 004's runs")
    args = parser.parse_args()
    where = {"this": args.results, "003": args.report_003, "004": args.report_004}

    def find(source: str, name: str) -> Path:
        return latest(where[source], name) if name.startswith("-") else _only(where[source] / name)

    finals = {label: find(*run) for label, run in (COMBINED | ALONE).items()}
    pairs = {
        scale: (finals[f"with the constant, {label} (report 004)"], finals[f"without the constant, {label}"])
        for scale, label in SCALES.items()
    }
    check_matched(pairs)
    grid = latest(args.report_001, "-pd_grid")
    print("## The final runs\n")
    print_matched(finals, grid)
    print("\nEach seed of the final runs, with the feedback's constant (report 004) and without:\n")
    print_seeds(pairs)
    combined = {label: finals[label] for label in COMBINED}
    print("\n## Lesions\n")
    print_lesions(combined)
    for joint in (0, 1):
        print()
        print_constants(combined, joint)
    print("\n## Effort\n")
    print_effort(finals, grid)
    print("\n## The feedback's gains\n")
    print_gains(combined)


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


def check_matched(pairs: dict[str, tuple[Path, Path]]) -> None:
    """Check that each final run without the constant is report 004's but for it, on the same evaluations."""
    for with_constant, without in pairs.values():
        config = copy.deepcopy(load_config(without))
        if config["feedback"].pop("constant") is not False or config != load_config(with_constant):
            msg = f"{without.name} is not {with_constant.name} without the feedback's constant"
            raise RuntimeError(msg)
        if not np.array_equal(load_training(without)["evaluated_at"], load_training(with_constant)["evaluated_at"]):
            msg = f"{without.name} and {with_constant.name} evaluate at different trials"
            raise RuntimeError(msg)


def stays_worse_from(at: Array, evaluations: Array, pd: float) -> int | None:
    """The first evaluation from which every later one is worse than the PD alone; a divergence counts as worse."""
    worse = ~(evaluations < pd)
    return next((int(at[i]) for i in range(1, len(at)) if worse[i:].all()), None)


def print_matched(runs: dict[str, Path], grid: Path) -> None:
    print("Medians over the seeds; a run-away's error counts as it is.\n")
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

    print(
        "\nOver the last 1,000 trials, the 50 evaluations after trials 9,020 to 10,000, of each seed that improved:"
        " their median, 10th, and 90th percentile, and their largest; each a median over those seeds:\n"
    )
    print("| Learner | Seeds | Median | 10th percentile | 90th percentile | Largest |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for label, run in runs.items():
        data = load_training(run)
        late = data["evaluations"][:, data["evaluated_at"] > 9000][np.array(improved(run))]
        if len(late):
            cells = [np.median(late, axis=1), *np.percentile(late, (10, 90), axis=1), late.max(axis=1)]
            print(f"| {label} | {len(late)} | {' | '.join(_mm(float(np.median(cell)), 2) for cell in cells)} |")

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


def print_seeds(pairs: dict[str, tuple[Path, Path]]) -> None:
    print(
        "| Feedback scale | Seed | With the constant: worse than the PD alone from trial | 100 trials"
        " | 10,000 trials | Without: worse from trial | 100 trials | 10,000 trials |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for scale, runs in pairs.items():
        cells: list[list[str]] = []
        for run in runs:
            data = load_training(run)
            at, evaluations = data["evaluated_at"], data["evaluations"]
            pd = float(evaluations[0, 0])
            cells.append(
                [
                    f"{'never' if (start := stays_worse_from(at, errors, pd)) is None else f'{start:,}'}"
                    f" | {_mm(errors[at == 100][0])} | {_mm(errors[-1])}"
                    for errors in evaluations
                ]
            )
        for seed, (with_constant, without) in enumerate(zip(*cells, strict=True)):
            print(f"| {SCALES[scale]} | {seed + 1} | {with_constant} | {without} |")


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
        model = make_model(make_rule(config["rule"]), arm.num_joints, constant=feedback_constant(config))
        set_weights(model, feedback_weights)
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
    ff = data["feedforward_weights"][:, -1] if "readout" in config else None  # every run is of learn_combined.py
    fb = data["weights"][:, -1] if "rule" in config else None
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


def print_constants(runs: dict[str, Path], joint: int) -> None:
    """The constant torques on one joint, the feedback's and the feedforward's bias, medians over the improved seeds."""
    trials = (100, 1000, 3000, 10000)
    print(f"The constant torque on joint {joint + 1} (N m), the feedback's / the feedforward's bias / their sum:\n")
    print(f"| Combined controller | {' | '.join(f'{n:,} trials' for n in trials)} |")
    print(f"| --- | {' | '.join('---:' for _ in trials)} |")
    for label, run in runs.items():
        data = load_training(run)
        kept = np.array(improved(run))
        if not kept.any():
            continue
        at = data["evaluated_at"]
        feedback = data["weights"][kept, :, -1, joint] * data["scale"][kept, None, joint]  # the readout's bias, in N m
        bias = data["feedforward_weights"][kept, :, -1, joint]
        cells = []
        for n in trials:
            i = int(np.flatnonzero(at == n)[0])
            fb, ff = float(np.median(feedback[:, i])), float(np.median(bias[:, i]))
            total = float(np.median(feedback[:, i] + bias[:, i]))
            cells.append(f"{fb:+.2f} / {ff:+.2f} / {total:+.2f}")
        print(f"| {label} ({int(kept.sum())} of {len(kept)}) | {' | '.join(cells)} |")


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


def _only(run: Path) -> Path:
    if not _complete(run):
        msg = f"no finished run at {run}"
        raise FileNotFoundError(msg)
    return run


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
