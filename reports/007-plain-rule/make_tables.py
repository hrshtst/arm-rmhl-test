# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Print the tables of report 007 from the copies of its runs and of reports 001's, 004's, 005's and 006's.

    uv run python reports/007-plain-rule/make_tables.py

From the runs under ``results/`` (plain_rule's), and the final runs of the reports
it reuses, it prints, as Markdown:

- the tuning: for each tuning run, the error at its last trial for each setting, and
  the trainings and trials that each scale's tuning ran;
- the final runs: for every arm, the seeds improved and the median error over its
  seeds at matched budgets;
- the reaches to each level: the first reach from which the median over the seeds
  stays closer than a PD, and the range of the same reach over the seeds;
- Q1, the speed-up: how many times fewer reaches the plain combined controller
  needs than the faster arm of the plain feedback alone, and whether the seeds'
  ranges are apart;
- Q2, the two rules in the combined controller: each seed's reach to each level and
  error at matched budgets, plain against decorrelated, and whether they are apart;
- while learning: the error of the reaches learned from, with the exploration
  noise, over windows of reaches;
- the exploration: its standard deviation in torque on each joint;
- Q3, the mechanism check: the eigenvalues of ``C`` over the reaches, the
  decorrelated rule's step along each of its directions over the plain rule's at
  arm A's learning rate, and the reach from which at most two, and at most one, of
  its four directions stay above the ridge term;
- the addendum, arm D, the staged schedule with the plain rule, inertia-scaled: its
  tuning, and the four combined controllers' final runs, reaches to each level, and
  seeds, rule against rule on each schedule and schedule against schedule with
  each rule.
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
REPORTS = HERE.parent
REPORT_001 = REPORTS / "001-feedback-from-scratch" / "results"
REPORT_004 = REPORTS / "004-directional-forgetting" / "results"
REPORT_005 = REPORTS / "005-feedback-without-constant" / "results"
REPORT_006 = REPORTS / "006-learning-speed" / "results"
MATCHED = (10, 30, 100, 300, 1000, 3000, 10000)
WINDOWS = ((1, 10), (11, 100), (101, 1000), (1001, 3000), (3001, 10000))  # reaches, inclusive
MARKED_PDS = ((20.0, 0.7), (28.0, 0.7), (40.0, 0.4))
SECONDS_PER_REACH = 2.0
SCALES = {"inertia": "inertia-scaled", "raw": "raw torque"}
PLAIN_COMBINED = "combined, plain"
DECORRELATED_COMBINED = "combined, decorrelated (report 005)"
PLAIN_FEEDBACK = ("feedback alone, plain, no constant", "feedback alone, plain (report 001)")
STAGED_PLAIN = "combined, staged, plain"
STAGED_DECORRELATED = "combined, staged, decorrelated (report 006)"
EIGENVALUES_AT = (1, 2, 5, 10, 30, 100, 300, 1000)  # reaches


def arms(scale: str) -> dict[str, tuple[str, str]]:
    """The arms of a scale: their label, and which results hold their latest run, by the end of its name."""
    return {
        PLAIN_COMBINED: ("this", f"-final_combined_{scale}"),
        DECORRELATED_COMBINED: ("005", f"-final_concurrent_{scale}"),
        "feedforward alone (report 004)": ("004", f"-final_feedforward_alone_{scale}"),
        PLAIN_FEEDBACK[0]: ("this", f"-final_feedback_no_constant_{scale}"),
        PLAIN_FEEDBACK[1]: ("this", f"-long_plain_{scale}"),
        "feedback alone, decorrelated, no constant (report 006)": ("006", f"-final_feedback_no_constant_{scale}"),
        "feedback alone, decorrelated (report 001)": ("001", f"-long_decorrelated_{scale}"),
    }


def where(results: Path) -> dict[str, Path]:
    return {"this": results, "001": REPORT_001, "004": REPORT_004, "005": REPORT_005, "006": REPORT_006}


def runs_of(scale: str, results: Path) -> dict[str, Path]:
    return {label: latest(where(results)[source], name) for label, (source, name) in arms(scale).items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=HERE / "results", help="this report's runs")
    args = parser.parse_args()
    pds = grid_errors(latest(REPORT_001, "-pd_grid"))

    print("## Tuning\n")
    print_tuning(args.results)
    print_tuning_cost(args.results)
    for scale, title in SCALES.items():
        runs = runs_of(scale, args.results)
        print(f"\n## The final runs, {title}\n")
        print_matched(runs)
        print(f"\n## The reaches to each level, {title}\n")
        levels = print_levels(runs, pds)
        print(f"\n## Q1, the speed-up of the plain rule, {title}\n")
        print_speed_up(levels, pds)
        print(f"\n## Q2, the two rules in the combined controller, {title}\n")
        print_rules(runs, levels, pds)
        print(f"\n## While learning, {title}\n")
        print_while_learning(runs)
    print("\n## The exploration\n")
    print_exploration({scale: runs_of(scale, args.results) for scale in SCALES})
    print("\n## Q3, the mechanism check\n")
    plain_rate = load_config(latest(args.results, "-final_combined_inertia"))["rule"]["learning_rate"]
    print_mechanism(latest(args.results, "-decorrelation_inertia"), plain_rate)
    if any(run.name.endswith("-final_staged_inertia") and complete(run) for run in args.results.iterdir()):
        print("\n## Addendum: the staged schedule, inertia-scaled\n")
        print_staged(args.results, pds)


def staged_runs(results: Path) -> dict[str, Path]:
    """The four combined controllers, inertia-scaled: the two rules on the two schedules."""
    return {
        PLAIN_COMBINED: latest(results, "-final_combined_inertia"),
        DECORRELATED_COMBINED: latest(REPORT_005, "-final_concurrent_inertia"),
        STAGED_PLAIN: latest(results, "-final_staged_inertia"),
        STAGED_DECORRELATED: latest(REPORT_006, "-final_staged_inertia"),
    }


def print_staged(results: Path, pds: dict[tuple[float, float], float]) -> None:
    print_tuning(results, "staged")
    print_tuning_cost(results, "staged", {"inertia": SCALES["inertia"]})
    runs = staged_runs(results)
    print()
    print_matched(runs)
    print()
    levels = print_levels(runs, pds)
    pairs = (
        (STAGED_PLAIN, STAGED_DECORRELATED, "the staged schedule, plain / decorrelated"),
        (PLAIN_COMBINED, STAGED_PLAIN, "the plain rule, concurrent / staged"),
        (DECORRELATED_COMBINED, STAGED_DECORRELATED, "the decorrelated rule, concurrent / staged"),
    )
    for first, second, title in pairs:
        print(f"\n{title[0].upper()}{title[1:]}:\n")
        print_rules(runs, levels, pds, (first, second), tuple(title.split(", ")[1].split(" / ")))


def latest(results: Path, suffix: str) -> Path:
    """The latest finished run under ``results`` whose name ends with ``suffix``: names start with the time."""
    runs = sorted(path for path in results.iterdir() if path.name.endswith(suffix) and complete(path))
    if not runs:
        msg = f"no run ending with {suffix!r} under {results}"
        raise FileNotFoundError(msg)
    return runs[-1]


def complete(run: Path) -> bool:
    """Whether the run finished: a run directory gets its outputs at the end."""
    outputs = ("training.npz", "grid.csv", "decorrelation.npz")
    return (run / "config.toml").exists() and any((run / output).exists() for output in outputs)


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


def tuning_runs(results: Path, arm: str = "combined") -> list[Path]:
    """The tuning runs of an arm: "combined" for arm A, "staged" for arm D."""
    return sorted(path for path in results.iterdir() if f"-tune_{arm}_" in path.name and complete(path))


def print_tuning(results: Path, arm: str = "combined") -> None:
    for run in tuning_runs(results, arm):
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


def print_tuning_cost(results: Path, arm: str = "combined", scales: dict[str, str] = SCALES) -> None:
    print("The tuning's cost, on seed 0: its rounds, trainings and trials, by scale.\n")
    print("| Scale | Rounds | Trainings | Trials |")
    print("| --- | ---: | ---: | ---: |")
    for scale, title in scales.items():
        runs = [run for run in tuning_runs(results, arm) if f"-tune_{arm}_{scale}" in run.name]
        trainings = [len(load_rows(run)) for run in runs]
        trials = sum(count * load_config(run)["training"]["trials"] for count, run in zip(trainings, runs, strict=True))
        print(f"| {title} | {len(runs)} | {sum(trainings)} | {trials:,} |")


def print_matched(runs: dict[str, Path]) -> None:
    print("Medians over the seeds; a run-away's error counts as it is.\n")
    print(f"| Learner | Seeds improved | {' | '.join(f'{trials:,} reaches' for trials in MATCHED)} |")
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
        "Against the faster arm of the plain feedback alone at each level, by the medians: how many times fewer "
        "reaches the plain combined controller needs, and whether the seeds' ranges are apart, every seed of the "
        "combined controller passing before any seed of the feedback alone. "
        f"Times at {SECONDS_PER_REACH:g} s per reach.\n"
    )
    print(f"| Learner | {' | '.join(_mm(pds[pd]) for pd in MARKED_PDS)} |")
    print(f"| --- | {' | '.join('---' for _ in MARKED_PDS)} |")
    fastest = {pds[pd]: _fastest([levels[label][pds[pd]] for label in PLAIN_FEEDBACK]) for pd in MARKED_PDS}
    print(f"| the faster plain feedback alone | {' | '.join(_feedback_cell(fastest[pds[pd]]) for pd in MARKED_PDS)} |")
    cells = []
    for pd in MARKED_PDS:
        level = pds[pd]
        feedback = [levels[other][level] for other in PLAIN_FEEDBACK]
        cells.append(_speed_up_cell(levels[PLAIN_COMBINED][level], fastest[level], feedback))
    print(f"| {PLAIN_COMBINED} | {' | '.join(cells)} |")


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


def print_rules(
    runs: dict[str, Path],
    levels: dict[str, dict[float, Level]],
    pds: dict[tuple[float, float], float],
    pair: tuple[str, str] = (PLAIN_COMBINED, DECORRELATED_COMBINED),
    names: tuple[str, ...] = ("plain", "decorrelated"),
) -> None:
    first_name, second_name = names
    print(
        f"Seed by seed, 1 to 5, {first_name} / {second_name}: the reach from which each stays closer than each PD, "
        "and the error at matched budgets. Apart: every seed of one before, or closer than, every seed of "
        "the other; a seed that never passes counts as after every reach.\n"
    )
    print(f"| Measure | {first_name.capitalize()} | {second_name.capitalize()} | Apart |")
    print("| --- | --- | --- | --- |")
    for pd in MARKED_PDS:
        level = pds[pd]
        first, second = levels[pair[0]][level].seeds, levels[pair[1]][level].seeds
        late = [np.inf if seed is None else seed for seed in first], [np.inf if s is None else s for s in second]
        print(f"| reach to {_mm(level)} | {_seeds(first)} | {_seeds(second)} | {_apart(*late, names=names)} |")
    courses = {label: load_course(runs[label]) for label in pair}
    for trials in (100, 1000, 10000):
        errors = [evaluations[:, at == trials][:, 0] for at, evaluations in courses.values()]
        cells = [", ".join(_mm(error, 2).removesuffix(" mm") for error in seeds) + " mm" for seeds in errors]
        print(f"| error at {trials:,} reaches | {cells[0]} | {cells[1]} | {_apart(*errors, names=names)} |")


def _seeds(reaches: list[Reach]) -> str:
    return ", ".join("never" if reach is None else f"{reach:,}" for reach in reaches)


def _apart(first: Any, second: Any, names: tuple[str, ...] = ("plain", "decorrelated")) -> str:
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if np.max(first) < np.min(second):
        return f"{names[0]} before or closer"
    if np.max(second) < np.min(first):
        return f"{names[1]} before or closer"
    return "overlap"


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
    print(
        "The rule's learning rate and amplitude, and the exploration noise's standard deviation in torque, "
        "joint 1 / joint 2.\n"
    )
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
            amplitude = rule["exploration"]["amplitude"]
            with np.load(run / "training.npz") as data:
                torque = amplitude * data["scale"][0]  # N m per joint
            unit = "rad/s^2" if scale == "inertia" else "N m"
            setting = f"{rule['learning_rate']:g} with {amplitude:g} {unit}"
            cells.append(f"{setting}: " + " / ".join(f"{value:.2f}" for value in torque) + " N m")
        print(f"| {label} | {' | '.join(cells)} |")


def trained_again(run: Path) -> tuple[list[str], list[float]]:
    """The labels of the arms that the mechanism check trained again, and their decorrelated learning rates."""
    rows = load_rows(run, "arms.csv")
    return [row["arm"] for row in rows], [load_config(_stored(row["run"]))["rule"]["learning_rate"] for row in rows]


def print_mechanism(run: Path, plain_rate: float) -> None:
    with np.load(run / "decorrelation.npz") as data:
        eigenvalues, ridge = data["eigenvalues"], data["ridge"]  # (arms, trainings, trials, inputs)
    labels, rates = trained_again(run)
    print(
        f"`{run.name}`: the eigenvalues of `C` of each learning reach, largest first, the median over the "
        "seeds. In parentheses, the decorrelated rule's step along that direction over the plain rule's at "
        f"{plain_rate:g}, arm A's and arm B's learning rate: rate / ({plain_rate:g} (eigenvalue + ridge)).\n"
    )
    inputs = eigenvalues.shape[3]
    print(f"| Arm | Reach | {' | '.join(f'Eigenvalue {i + 1}' for i in range(inputs))} |")
    print(f"| --- | ---: | {' | '.join('---:' for _ in range(inputs))} |")
    for arm, label in enumerate(labels):
        for reach in EIGENVALUES_AT:
            median = np.median(eigenvalues[arm, :, reach - 1], axis=0)
            ratio = rates[arm] / (plain_rate * (median + ridge[arm]))
            cells = " | ".join(f"{value:.3g} ({step:.2g})" for value, step in zip(median, ratio, strict=True))
            print(f"| {label} | {reach:,} | {cells} |")
    print(
        "\nThe reach from which, on each seed, at most two, and at most one, of the four directions stay above "
        "the ridge term for the rest of the 1,000 reaches.\n"
    )
    print("| Arm | At most two above, by seed | At most one above, by seed | The largest above at every reach |")
    print("| --- | --- | --- | --- |")
    for arm, label in enumerate(labels):
        above = (eigenvalues[arm] > ridge[arm]).sum(axis=2)  # (trainings, trials)
        reaches = np.arange(1, above.shape[1] + 1)
        cells = [_seeds([stays_below(reaches, counts, most + 0.5) for counts in above]) for most in (2, 1)]
        largest = (eigenvalues[arm, :, :, 0] > ridge[arm]).all()
        print(f"| {label} | {cells[0]} | {cells[1]} | {'every seed' if largest else 'not every seed'} |")


def _stored(name: str) -> Path:
    """A run that the mechanism check trained again, from the report that holds its copy."""
    for results in (REPORT_005, REPORT_006):
        if (results / Path(name).name).exists():
            return results / Path(name).name
    msg = f"no report holds {name}"
    raise FileNotFoundError(msg)


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
