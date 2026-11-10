# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 006 from the copies of its runs and of reports 001's, 004's and 005's.

    uv run python reports/006-learning-speed/make_tables.py

From the runs under ``results/`` (learning_speed's), and the final runs of the
reports it reuses, it prints, as Markdown:

- the tuning: for each tuning run, the error at its last trial for each setting;
- the final runs: for every arm, the seeds improved and the median error over its
  seeds at matched budgets;
- the reaches to each level: the first reach from which the median over the seeds
  stays closer than a PD, and the range of the same reach over the seeds;
- the speed-up: how many times fewer reaches each schedule of the combined
  controller needs than the fastest arm of the feedback alone, what that would
  mean at 2 s per reach, and whether the seeds' ranges are apart: the question's
  criterion;
- while learning: the error of the reaches learned from, with the exploration
  noise, over windows of reaches;
- the exploration: its standard deviation in torque on each joint.
"""

from __future__ import annotations

import argparse
import csv
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

Array = np.ndarray

HERE = Path(__file__).resolve().parent
REPORT_001 = HERE.parent / "001-feedback-from-scratch" / "results"
REPORT_004 = HERE.parent / "004-directional-forgetting" / "results"
REPORT_005 = HERE.parent / "005-feedback-without-constant" / "results"
MATCHED = (10, 30, 100, 300, 1000, 3000, 10000)
WINDOWS = ((1, 10), (11, 100), (101, 1000), (1001, 3000), (3001, 10000))  # reaches, inclusive
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
SECONDS_PER_REACH = 2.0
SCALES = {"inertia": "inertia-scaled", "raw": "raw torque"}
COMBINED_ARMS = ("combined, concurrent (report 005)", "combined, staged")
FEEDBACK_ARMS = (
    "feedback alone, tuned for 1,000 reaches (report 001)",
    "feedback alone, without the constant",
    "feedback alone, tuned for 300 reaches",
)


def arms(scale: str) -> dict[str, tuple[str, str]]:
    """The arms of a scale: their label, and which results hold their latest run, by the end of its name."""
    return {
        COMBINED_ARMS[0]: ("005", f"-final_concurrent_{scale}"),
        COMBINED_ARMS[1]: ("this", f"-final_staged_{scale}"),
        "feedforward alone (report 004)": ("004", f"-final_feedforward_alone_{scale}"),
        FEEDBACK_ARMS[0]: ("001", f"-long_decorrelated_{scale}"),
        FEEDBACK_ARMS[1]: ("this", f"-final_feedback_no_constant_{scale}"),
        FEEDBACK_ARMS[2]: ("this", f"-final_feedback_short_{scale}"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    args = parser.parse_args()
    where = {"this": args.results, "001": REPORT_001, "004": REPORT_004, "005": REPORT_005}
    pds = grid_errors(latest(REPORT_001, "-pd_grid"))

    print("## Tuning\n")
    print_tuning(args.results)
    for scale, title in SCALES.items():
        runs = {label: latest(where[source], name) for label, (source, name) in arms(scale).items()}
        print(f"\n## The final runs, {title}\n")
        print_matched(runs)
        print(f"\n## The reaches to each level, {title}\n")
        levels = print_levels(runs, pds)
        print(f"\n## The speed-up, {title}\n")
        print_speed_up(levels, pds)
        print(f"\n## While learning, {title}\n")
        print_while_learning(runs)
    print("\n## The exploration\n")
    print_exploration(
        {
            scale: {label: latest(where[source], name) for label, (source, name) in arms(scale).items()}
            for scale in SCALES
        }
    )


def latest(results: Path, suffix: str) -> Path:
    """The latest finished run under ``results`` whose name ends with ``suffix``: names start with the time."""
    runs = sorted(path for path in results.iterdir() if path.name.endswith(suffix) and complete(path))
    if not runs:
        msg = f"no run ending with {suffix!r} under {results}"
        raise FileNotFoundError(msg)
    return runs[-1]


def complete(run: Path) -> bool:
    """Whether the run finished: a run directory gets its outputs at the end."""
    return (run / "config.toml").exists() and ((run / "training.npz").exists() or (run / "grid.csv").exists())


def load_config(run: Path) -> dict[str, Any]:
    with (run / "config.toml").open("rb") as f:
        return tomllib.load(f)


def load_rows(run: Path, name: str = "runs.csv") -> list[dict[str, str]]:
    with (run / name).open() as f:
        return list(csv.DictReader(f))


def load_course(run: Path) -> tuple[Array, Array]:
    """The trials of the evaluations and their errors, ``(trainings, evaluations)``; a skipped one is infinite."""
    with np.load(run / "training.npz") as data:
        return data["evaluated_at"], np.nan_to_num(data["evaluations"], nan=np.inf)


def grid_errors(grid: Path) -> dict[tuple[float, float], float]:
    return {
        (float(row["command.omega"]), float(row["command.damping_ratio"])): float(row["tracking_error_m"])
        for row in load_rows(grid, "grid.csv")
    }


def stays_below(at: Array, errors: Array, level: float) -> int | None:
    """The first trial from which this evaluation and every later one are closer than ``level``."""
    below = errors < level
    return next((int(at[i]) for i in range(len(at)) if below[i:].all()), None)


def print_tuning(results: Path) -> None:
    for run in sorted(path for path in results.iterdir() if "-tune_" in path.name and complete(path)):
        rows = load_rows(run)
        columns = sorted({float(row["rule.learning_rate"]) for row in rows})
        amplitudes = sorted({float(row["rule.exploration.amplitude"]) for row in rows})
        cell = {(float(row["rule.exploration.amplitude"]), float(row["rule.learning_rate"])): row for row in rows}
        print(f"`{run.name}`: the error at the last trial, by amplitude (rows) and learning rate (columns)\n")
        print(f"| Amplitude | {' | '.join(f'{rate:g}' for rate in columns)} |")
        print(f"| ---: | {' | '.join('---:' for _ in columns)} |")
        for amplitude in amplitudes:
            cells = [_tuning_cell(cell[amplitude, rate]) for rate in columns]
            print(f"| {amplitude:g} | {' | '.join(cells)} |")
        print()


def _tuning_cell(row: dict[str, str]) -> str:
    if row["outcome"] != "improved":
        return row["outcome"]
    return f"{1000 * float(row['final_error_m']):.2f}"


def print_matched(runs: dict[str, Path]) -> None:
    print("Medians over the seeds; a run-away's error counts as it is.\n")
    print(f"| Learner | Seeds improved | {' | '.join(f'{trials:,} trials' for trials in MATCHED)} |")
    print(f"| --- | ---: | {' | '.join('---:' for _ in MATCHED)} |")
    for label, run in runs.items():
        at, evaluations = load_course(run)
        median = np.median(evaluations, axis=0)
        cells = " | ".join(_mm(median[at == trials][0]) if trials in at else "" for trials in MATCHED)
        outcomes = [row["outcome"] for row in load_rows(run)]
        print(f"| {label} | {outcomes.count('improved')} of {len(outcomes)} | {cells} |")


Reach = int | None  # the first reach from which the error stays below a level; None for never


@dataclass(frozen=True)
class Level:
    """When an arm passes a level: the median over its seeds, and each seed."""

    median: Reach
    seeds: list[Reach]
    budget: int  # the reaches run


def print_levels(runs: dict[str, Path], pds: dict[tuple[float, float], float]) -> dict[str, dict[float, Level]]:
    """The table of the reaches to each level; returns each arm's reaches by level."""
    headers = [f"PD, {omega:g} rad/s, {ratio:g} ({_mm(pds[omega, ratio])})" for omega, ratio in MARKED_PDS]
    print(
        "The first reach from which the median over the seeds stays closer than the PD, and that reach of each seed.\n"
    )
    print(f"| Learner | Reaches run | {' | '.join(headers)} |")
    print(f"| --- | ---: | {' | '.join('---:' for _ in MARKED_PDS)} |")
    levels: dict[str, dict[float, Level]] = {}
    for label, run in runs.items():
        at, evaluations = load_course(run)
        median = np.median(evaluations, axis=0)
        cells = []
        levels[label] = {}
        for pd in MARKED_PDS:
            level = pds[pd]
            reach = stays_below(at, median, level)
            seeds = [stays_below(at, errors, level) for errors in evaluations]
            levels[label][level] = Level(reach, seeds, int(at[-1]))
            reached = [seed for seed in seeds if seed is not None]
            spread = ""
            if len(seeds) > 1 and reached:
                spread = f" ({_span(min(reached), max(reached))}"
                spread += f"; {len(seeds) - len(reached)} never)" if len(reached) < len(seeds) else ")"
            elif len(seeds) > 1:
                spread = " (no seed)"
            cells.append(f"{'never' if reach is None else f'{reach:,}'}{spread}")
        print(f"| {label} | {int(at[-1]):,} | {' | '.join(cells)} |")
    return levels


def print_speed_up(levels: dict[str, dict[float, Level]], pds: dict[tuple[float, float], float]) -> None:
    print(
        "Against the fastest arm of the feedback alone at each level, by the medians: how many times fewer "
        "reaches the combined controller needs, and whether the seeds' ranges are apart, every seed of the "
        "combined controller passing before any seed of the feedback alone. "
        f"Times at {SECONDS_PER_REACH:g} s per reach.\n"
    )
    headers = [f"{_mm(pds[pd])}" for pd in MARKED_PDS]
    print(f"| Learner | {' | '.join(headers)} |")
    print(f"| --- | {' | '.join('---' for _ in MARKED_PDS)} |")
    fastest = {pds[pd]: _fastest([levels[label][pds[pd]] for label in FEEDBACK_ARMS]) for pd in MARKED_PDS}
    cells = [_feedback_cell(fastest[pds[pd]]) for pd in MARKED_PDS]
    print(f"| the fastest feedback alone | {' | '.join(cells)} |")
    for label in COMBINED_ARMS:
        cells = []
        for pd in MARKED_PDS:
            level = pds[pd]
            feedback = [levels[other][level] for other in FEEDBACK_ARMS]
            cells.append(_speed_up_cell(levels[label][level], fastest[level], feedback))
        print(f"| {label} | {' | '.join(cells)} |")


def _fastest(feedback: list[Level]) -> Level:
    """The arm passing first by its median; if none does, the one that ran the most reaches."""
    passing = [level for level in feedback if level.median is not None]
    if passing:
        return min(passing, key=lambda level: level.median or 0)
    return max(feedback, key=lambda level: level.budget)


def _feedback_cell(fastest: Level) -> str:
    if fastest.median is None:
        return f"not in {fastest.budget:,}"
    return _time(fastest.median)


def _speed_up_cell(combined: Level, fastest: Level, feedback: list[Level]) -> str:
    if combined.median is None:
        return "never"
    if fastest.median is None and fastest.budget >= 2 * combined.median:
        ratio = f"more than {fastest.budget / combined.median:,.0f} times fewer"
    elif fastest.median is None:
        ratio = f"the feedback alone not in {fastest.budget:,}"
    elif combined.median <= fastest.median:
        ratio = f"{fastest.median / combined.median:,.0f} times fewer"
    else:
        ratio = f"{combined.median / fastest.median:,.1f} times more"
    first_feedback = min((seed for level in feedback for seed in level.seeds if seed is not None), default=None)
    slowest = None if None in combined.seeds else max(seed for seed in combined.seeds if seed is not None)
    apart = slowest is not None and (first_feedback is None or slowest < first_feedback)
    return f"{_time(combined.median)}; {ratio}; seeds {'apart' if apart else 'overlap'}"


def print_while_learning(runs: dict[str, Path]) -> None:
    print(
        "The tracking error of the reaches learned from, with the exploration noise: the median over each "
        "window of each seed, then the median over the seeds.\n"
    )
    headers = [f"{first:,} to {last:,}" for first, last in WINDOWS]
    print(f"| Learner | {' | '.join(headers)} |")
    print(f"| --- | {' | '.join('---:' for _ in WINDOWS)} |")
    for label, run in runs.items():
        with np.load(run / "training.npz") as data:
            errors = data["errors"]  # (trainings, trials), m
        cells = [
            _mm(float(np.median(np.median(errors[:, first - 1 : last], axis=1)))) if last <= errors.shape[1] else ""
            for first, last in WINDOWS
        ]
        print(f"| {label} | {' | '.join(cells)} |")


def print_exploration(runs: dict[str, dict[str, Path]]) -> None:
    print("The exploration noise's standard deviation in torque, joint 1 / joint 2.\n")
    print(f"| Learner | {' | '.join(SCALES.values())} |")
    print(f"| --- | {' | '.join('---:' for _ in SCALES)} |")
    for label in runs[next(iter(SCALES))]:
        cells = []
        for scale in SCALES:
            run = runs[scale][label]
            rule = load_config(run).get("rule")
            if rule is None:
                cells.append("no noise")
                continue
            with np.load(run / "training.npz") as data:
                torque = rule["exploration"]["amplitude"] * data["scale"][0]  # N m per joint
            cells.append(" / ".join(f"{value:.2f}" for value in torque) + " N m")
        print(f"| {label} | {' | '.join(cells)} |")


def _span(first: int, last: int) -> str:
    return f"{first:,}" if first == last else f"{first:,} to {last:,}"


def _time(reaches: int | None) -> str:
    if reaches is None:
        return "never"
    seconds = reaches * SECONDS_PER_REACH
    when = f"{seconds / 3600:.1f} h" if seconds >= 3600 else f"{seconds / 60:.1f} min"
    return f"{reaches:,} reaches, {when}"


def _mm(error: float, digits: int = 1) -> str:
    return "not finite" if not np.isfinite(error) else f"{1000 * error:.{digits}f} mm"


if __name__ == "__main__":
    main()
