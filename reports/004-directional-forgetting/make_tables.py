# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 004 from the copies of its runs and of reports 001's to 003's.

    uv run python reports/004-directional-forgetting/make_tables.py

From the runs under ``results/`` (directional_forgetting's wind-up sweep, continued
run, tuning, final runs, and early check), ``../003-combined-learning/results/``
(combined_learning's wind-up sweep, tuning, and final runs, forgetting
exponentially or not at all), and ``../001-feedback-from-scratch/results/`` (the
PD grid), it prints, as Markdown:

- the wind-up: for each forgetting factor and ``delta`` of the feedforward alone,
  forgetting directionally, the error at 100, 1,000, and 3,000 trials, and the
  trials from which it stays worse than the PD alone, forgetting either way; and
  for report 002's setting continued to 10,000 trials, the same either way. It
  checks that the rows without forgetting are combined_learning's bit for bit
  (Section 3.1);
- the tuning: for each feedback scale, each round's closest setting and the
  closest over all rounds, which must be the setting of the scale's final runs,
  and the closest setting at 1,000 trials of combined_learning's concurrent
  tuning, forgetting exponentially and not at all. It checks that every setting
  run in more than one round comes out the same in each (Section 3.2);
- the final runs: for every learner, the median error over its seeds at matched
  budgets, how many seeds improved, the error of each seed at 10,000 trials, the
  spread of each improved seed's last 50 evaluations, and the trials from which
  the median stays closer than the PDs; and for each seed of the combined final
  runs, over their first 100 trials, the trial from which it stays worse than the
  PD alone and its error at trial 100, forgetting directionally and in the early
  check without forgetting (Section 3.3);
- the effort: every controller replayed without noise, with the learners' weights
  at their last evaluation, as medians over the seeds that improved on the PD alone
  (a run-away's torques say nothing of the learned controller): the
  tracking error, the squared torque integrated over the reach, the peak torque, the
  torque's variation from one control period to the next summed over the reach and
  the joints, and the root mean square of each part's torque, the PD's, the
  feedforward's, and the feedback's (Section 3.4);
- the lesions: each combined final controller replayed as learned, without its
  feedback, and without its feedforward; the constant torques on joint 1, the
  feedback's, the feedforward's bias, and their sum, over the trials; and the
  feedback's gains: the diagonals of its stiffness and damping matrices and its
  constant torque; each a median over the seeds that improved (Section 3.5).

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
REPORT_003 = HERE.parent / "003-combined-learning" / "results"
MATCHED = (10, 100, 1000, 3000, 10000)
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
EFFORT_PDS = ((5.0, 0.7), (20.0, 0.7), (28.0, 0.7), (40.0, 0.4), (80.0, 0.2))
SCALES = {"none": "raw torque", "inertia": "inertia-scaled"}
UNITS = {"none": "N m", "inertia": "rad/s^2"}
# label: (which results, the run's name, or the end of it for the latest such run)
COMBINED = {
    "combined, directionally, raw torque": ("this", "-final_concurrent_raw"),
    "combined, no forgetting, raw torque (report 003)": ("003", "20261106-133311-final_concurrent_raw"),
    "combined, directionally, inertia-scaled": ("this", "-final_concurrent_inertia"),
    "combined, no forgetting, inertia-scaled (report 003)": ("003", "20261106-134705-final_concurrent_inertia"),
    "combined, exponentially, inertia-scaled (report 003, superseded)": (
        "003",
        "20261105-215525-final_concurrent_inertia",
    ),
}
ALONE = {
    "feedforward alone, 0.999 directionally, delta 100": ("this", "-final_feedforward_alone_raw"),
    "feedforward alone, no forgetting, delta 100 (report 003)": ("003", "20261106-133311-final_feedforward_alone_raw"),
    "feedforward alone, 0.999 directionally, delta 10": ("this", "-final_feedforward_alone_inertia"),
    "feedforward alone, no forgetting, delta 10 (report 003)": (
        "003",
        "20261106-134705-final_feedforward_alone_inertia",
    ),
    "feedforward alone, 0.9999 directionally, delta 10": ("this", "-continued_feedforward_alone"),
    "feedforward alone, 0.9999 exponentially, delta 10 (report 003)": (
        "003",
        "20261105-215525-final_feedforward_alone",
    ),
}

CONTINUED = (
    "feedforward alone, 0.9999 directionally, delta 10",
    "feedforward alone, 0.9999 exponentially, delta 10 (report 003)",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    parser.add_argument("--report-001", type=Path, default=REPORT_001, help="report 001's runs")
    parser.add_argument("--report-003", type=Path, default=REPORT_003, help="report 003's runs")
    args = parser.parse_args()
    where = {"this": args.results, "003": args.report_003}

    def find(source: str, name: str) -> Path:
        return latest(where[source], name) if name.startswith("-") else _only(where[source] / name)

    finals = {label: find(*run) for label, run in (COMBINED | ALONE).items()}
    grid = latest(args.report_001, "-pd_grid")
    print("## The wind-up\n")
    print_windup(
        latest(args.results, "-windup_feedforward_alone"), latest(args.report_003, "-windup_feedforward_alone")
    )
    print("\nReport 002's setting, 0.9999 with a delta of 10, for 10,000 trials:\n")
    print_continued({label: finals[label] for label in CONTINUED})
    print_inputs(load_config(latest(args.results, "-windup_feedforward_alone")))
    print("\n## Tuning\n")
    print_tuning(args.results, finals)
    print()
    print_exponential_tuning(args.report_003)
    print("\n## The final runs\n")
    print_matched(finals, grid)
    print("\nThe first 100 trials of each final run, forgetting directionally and without forgetting:\n")
    print_early(
        {
            SCALES[scale]: (
                finals[f"combined, directionally, {SCALES[scale]}"],
                latest(args.results, f"-early_without_forgetting_{'raw' if scale == 'none' else scale}"),
            )
            for scale in SCALES
        }
    )
    print("\n## Effort\n")
    print_effort(finals, grid)
    print("\n## Lesions\n")
    print_lesions({label: finals[label] for label in COMBINED})
    print()
    print_constants({label: finals[label] for label in COMBINED})
    print("\n## The feedback's gains\n")
    print_gains({label: run for label, run in finals.items() if "rule" in load_config(run)})


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


def stays_worse_from(at: Array, evaluations: Array, pd: float) -> int | None:
    """The first evaluation from which every later one is worse than the PD alone; a divergence counts as worse."""
    worse = ~(evaluations < pd)
    return next((int(at[i]) for i in range(1, len(at)) if worse[i:].all()), None)


def print_windup(run: Path, exponential: Path) -> None:
    data, before = load_training(run), load_training(exponential)
    at = data["evaluated_at"]
    pd = float(data["evaluations"][0, 0])
    if not np.array_equal(at, before["evaluated_at"]):
        msg = f"{run.name} and {exponential.name} evaluate at different trials"
        raise RuntimeError(msg)
    print(
        "| Forgetting factor | delta | 100 trials | 1,000 trials | 3,000 trials"
        " | Worse than the PD alone from trial | The same, forgetting exponentially (report 003) |"
    )
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    sweeps = zip(expand(load_config(run)), expand(load_config(exponential)), strict=True)
    for ((_, config), (_, config_before)), evaluations, evaluations_before in zip(
        sweeps, data["evaluations"], before["evaluations"], strict=True
    ):
        forgetting, delta = config["readout"]["forgetting"], config["readout"]["delta"]
        if (forgetting, delta) != (config_before["readout"]["forgetting"], config_before["readout"]["delta"]):
            msg = f"{run.name} and {exponential.name} sweep different settings"
            raise RuntimeError(msg)
        if forgetting == 1.0 and not np.array_equal(evaluations, evaluations_before):
            msg = f"without forgetting, {run.name} differs from {exponential.name} at delta {delta:g}"
            raise RuntimeError(msg)
        cells = " | ".join(_mm(evaluations[at == trials][0]) for trials in (100, 1000, 3000))
        starts = [stays_worse_from(at, errors, pd) for errors in (evaluations, evaluations_before)]
        worse = " | ".join("never" if start is None else f"{start:,}" for start in starts)
        print(f"| {forgetting:g} | {delta:g} | {cells} | {worse} |")


def print_continued(runs: dict[str, Path]) -> None:
    trials = (100, 1000, 1500, 3000, 10000)
    print(f"| Feedforward alone | {' | '.join(f'{n:,} trials' for n in trials)} | Worse than the PD alone from trial |")
    print(f"| --- | {' | '.join('---:' for _ in trials)} | ---: |")
    for label, run in runs.items():
        data = load_training(run)
        at, errors = data["evaluated_at"], data["evaluations"][0]
        start = stays_worse_from(at, errors, float(errors[0]))
        cells = " | ".join(_mm(errors[at == n][0]) for n in trials)
        short = label.removeprefix("feedforward alone, ").replace(", delta 10", "")  # the table is of one setting
        print(f"| {short} | {cells} | {'never' if start is None else f'{start:,}'} |")


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


def tuning_rows(results: Path) -> list[tuple[str, dict[str, Any], Array]]:
    """Every training of the concurrent schedule's tuning runs: the run's name, the configuration, its evaluations."""
    rows = []
    for run in sorted(path for path in results.iterdir() if "-tune_" in path.name and _complete(path)):
        data = load_training(run)
        for (_, config), evaluations in zip(expand(load_config(run)), data["evaluations"], strict=True):
            if config["schedule"]["kind"] == "concurrent":
                rows.append((run.name, config, evaluations))
    return rows


def print_tuning(results: Path, finals: dict[str, Path]) -> None:
    rows = tuning_rows(results)
    repeated: dict[tuple[Any, ...], Array] = {}
    for name, config, evaluations in rows:
        key = (config["feedback"]["scale"], *setting(config))
        if key in repeated and not np.array_equal(repeated[key], evaluations):
            msg = f"{name} does not repeat the earlier training of {key}"
            raise RuntimeError(msg)
        repeated.setdefault(key, evaluations)
    at = load_training(latest(results, "-tune_readout_concurrent_raw"))["evaluated_at"]

    print(
        "| Feedback scale | Round | Feedback: learning rate, amplitude | Feedforward: forgetting, delta"
        " | Error at 1,000 trials |"
    )
    print("| --- | --- | ---: | ---: | ---: |")
    for scale, scale_label in SCALES.items():
        best: tuple[float, tuple[Any, ...]] | None = None
        for name in sorted({name for name, config, _ in rows if config["feedback"]["scale"] == scale}):
            candidates = [
                (float(evaluations[at == 1000][0]), setting(config)) for run, config, evaluations in rows if run == name
            ]
            error, chosen = min(candidates, key=_closest)
            print(f"| {scale_label} | `{name.split('-', 2)[2]}` | {_setting_cells(chosen, scale)} | {_mm(error, 2)} |")
            if best is None or _closest((error, chosen)) < _closest(best):
                best = error, chosen
        assert best is not None
        final = finals[f"combined, directionally, {scale_label}"]
        if setting(load_config(final)) != best[1]:
            msg = f"{final.name} does not run the tuned setting {best[1]}"
            raise RuntimeError(msg)
        print(f"| {scale_label} | **over all** | {_setting_cells(best[1], scale)} | {_mm(best[0], 2)} |")


def print_exponential_tuning(report_003: Path) -> None:
    """combined_learning's closest concurrent settings at 1,000 trials, forgetting exponentially and not at all."""
    rows = tuning_rows(report_003)
    at = load_training(latest(report_003, "-tune_readout_concurrent_raw"))["evaluated_at"]
    print("combined_learning's concurrent tuning, report 003:\n")
    print(
        "| Feedback scale | Forgetting | Feedback: learning rate, amplitude | Feedforward: forgetting, delta"
        " | Error at 1,000 trials |"
    )
    print("| --- | --- | ---: | ---: | ---: |")
    for scale, scale_label in SCALES.items():
        for forgets, label in ((True, "exponentially"), (False, "none")):
            candidates = [
                (float(evaluations[at == 1000][0]), setting(config))
                for _, config, evaluations in rows
                if config["feedback"]["scale"] == scale and (config["readout"]["forgetting"] < 1.0) == forgets
            ]
            error, chosen = min(candidates, key=_closest)
            print(f"| {scale_label} | {label} | {_setting_cells(chosen, scale)} | {_mm(error, 2)} |")


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

    print("\nThe error of each seed at 10,000 trials:\n")
    print("| Learner | Seed 1 | Seed 2 | Seed 3 | Seed 4 | Seed 5 |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for label, run in runs.items():
        last = load_training(run)["evaluations"][:, -1]
        if len(last) > 1:
            print(f"| {label} | {' | '.join(_mm(error) for error in last)} |")

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


def print_early(pairs: dict[str, tuple[Path, Path]]) -> None:
    print(
        "| Feedback scale | Seed | Directionally: worse than the PD alone from trial | Error at 100 trials"
        " | Without forgetting: worse from trial | Error at 100 trials |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for label, (final, check) in pairs.items():
        cells: list[list[str]] = []
        for run in (final, check):
            data = load_training(run)
            early = data["evaluated_at"] <= 100
            at, evaluations = data["evaluated_at"][early], data["evaluations"][:, early]
            pd = float(evaluations[0, 0])
            starts = [stays_worse_from(at, errors, pd) for errors in evaluations]
            cells.append(
                [
                    f"{'never' if start is None else f'{start:,}'} | {_mm(errors[-1])}"
                    for start, errors in zip(starts, evaluations, strict=True)
                ]
            )
        for seed, (directional, without) in enumerate(zip(*cells, strict=True)):
            print(f"| {label} | {seed + 1} | {directional} | {without} |")


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


def print_constants(runs: dict[str, Path]) -> None:
    """The constant torques on joint 1, the feedback's and the feedforward's bias, medians over the improved seeds."""
    trials = (100, 1000, 3000, 10000)
    print("The constant torque on joint 1 (N m), the feedback's / the feedforward's bias / their sum:\n")
    print(f"| Combined controller | {' | '.join(f'{n:,} trials' for n in trials)} |")
    print(f"| --- | {' | '.join('---:' for _ in trials)} |")
    for label, run in runs.items():
        data = load_training(run)
        kept = np.array(improved(run))
        if not kept.any():
            continue
        at = data["evaluated_at"]
        feedback = data["weights"][kept, :, -1, 0] * data["scale"][kept, None, 0]  # the readout's bias, in N m
        bias = data["feedforward_weights"][kept, :, -1, 0]
        cells = []
        for n in trials:
            i = int(np.flatnonzero(at == n)[0])
            fb, ff = float(np.median(feedback[:, i])), float(np.median(bias[:, i]))
            total = float(np.median(feedback[:, i] + bias[:, i]))
            cells.append(f"{fb:+.2f} / {ff:+.2f} / {total:+.2f}")
        print(f"| {label} ({int(kept.sum())} of {len(kept)}) | {' | '.join(cells)} |")


def _only(run: Path) -> Path:
    if not _complete(run):
        msg = f"no finished run at {run}"
        raise FileNotFoundError(msg)
    return run


def _complete(run: Path) -> bool:
    """Whether the run finished: a run directory gets its outputs at the end."""
    return (run / "config.toml").exists() and ((run / "training.npz").exists() or (run / "grid.csv").exists())


def _closest(candidate: tuple[float, tuple[Any, ...]]) -> float:
    """The error that ranks a candidate setting: a divergence, not finite, ranks last."""
    return candidate[0] if np.isfinite(candidate[0]) else np.inf


def _setting_cells(chosen: tuple[Any, ...], scale: str) -> str:
    rate, amplitude, forgetting, delta = chosen
    return f"{rate:,g}, {amplitude:g} {UNITS[scale]} | {forgetting:g}, {delta:g}"


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
