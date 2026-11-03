# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Learn feedback torques from one reward per reach, for every combination of a sweep.

    uv run python experiments/learn_feedback.py experiments/<experiment>/<configuration>.toml --workers 20

The configuration describes the arm, the reach and the joint PD of ``[command]``
(see :mod:`arm_rmhl_test.arm`), the feedback's scale, the rule and the training
(see :mod:`arm_rmhl_test.feedback`), and an optional ``[sweep]`` of its settings (see
:mod:`arm_rmhl_test.sweeps`), such as ``"rule.learning_rate"`` or the exploration's
``"rule.exploration.seed"``. Every combination trains a fresh model, from zero
feedback. The run directory receives:

- ``runs.csv``: one row per combination: its values, the summary of
  :func:`arm_rmhl_test.feedback.summarize` (the noise-free tracking errors of the
  PD alone, at the end and at best, the outcome, and the final gains of the
  torque), and the seconds it took;
- ``training.npz``: the course of every training, a row per combination in the
  order of ``runs.csv``: the tracking error of each exploring reach, ``errors``
  ``(combinations, trials)``; the trials learned from before each noise-free
  evaluation, ``evaluated_at``; their tracking errors, ``evaluations``
  ``(combinations, evaluations)``; the readout's weights then, ``weights``
  ``(combinations, evaluations, 2 joints + 1, joints)``; and each joint's factor
  from the readout's output to the torque, ``scale`` ``(combinations, joints)``;
- ``learning.png``: the noise-free tracking error over the trials learned from, one
  panel per combination of all but the last swept setting, one line per value of
  the last; the dashed line is the PD alone, and a cross marks where the arm
  diverged.

With ``--workers``, the combinations are spread over that many processes, each
computing with one thread; their results are the same as in one process.
"""

from __future__ import annotations

import argparse
import csv
import math
import multiprocessing
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib import colormaps
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from arm_rmhl_test.feedback import Training, learn, summarize, training_settings
from arm_rmhl_test.storage import start_run
from arm_rmhl_test.sweeps import expand

TEXT_COLOR = "#52514e"
TITLE_COLOR = "#0b0b0b"
GRID_COLOR = "#e4e3de"
SURFACE_COLOR = "#fcfcfb"
PD_COLOR = "#a3a29d"
# Seeds are identities: categorical hues, in this order. Other settings are magnitudes: a blue ramp, light to dark.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b"]
PLAIN = FuncFormatter(lambda value, _: f"{value:g}")  # log-axis labels as plain numbers
# Between the decades, only 2 and 5 are labeled.
SPARSE = FuncFormatter(
    lambda value, _: f"{value:g}" if round(value / 10 ** np.floor(np.log10(value))) in (2, 5) else ""
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path, help="configuration file (TOML)")
    parser.add_argument(
        "--workers", type=int, default=1, help="worker processes, of one thread each (default 1: in this process)"
    )
    args = parser.parse_args()

    config, run_dir = start_run(args.config)
    combinations = expand(config)
    names = list(config.get("sweep", {}))
    swept = f" of {', '.join(names)}" if names else ""
    print(f"{len(combinations)} combinations{swept}, {training_settings(config)['trials']} trials each", flush=True)

    rows: list[dict[str, Any]] = []
    trainings: list[Training] = []
    for k, ((values, _), (training, seconds)) in enumerate(
        zip(combinations, learn_all([variant for _, variant in combinations], args.workers), strict=True)
    ):
        row = values | summarize(training) | {"seconds": seconds}
        rows.append(row)
        trainings.append(training)
        label = ", ".join(f"{name}={_format(value)}" for name, value in values.items()) or "the configuration"
        print(
            f"[{k + 1:3d}/{len(combinations)}] {label}: {row['outcome']};"
            f" noise-free error {1000 * row['pd_error_m']:.1f} -> {1000 * row['final_error_m']:.1f} mm"
            f" (best {1000 * row['best_error_m']:.1f} mm after {row['best_after']} trials); {seconds:.0f} s",
            flush=True,
        )

    with (run_dir / "runs.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    np.savez_compressed(
        run_dir / "training.npz",
        errors=np.array([t.errors for t in trainings]),
        evaluated_at=trainings[0].evaluated_at,
        evaluations=np.array([t.evaluations for t in trainings]),
        weights=np.array([t.weights for t in trainings]),
        scale=np.array([t.scale for t in trainings]),
    )
    plot_learning(combinations, trainings, f"Feedback learned: {args.config.stem}").savefig(
        run_dir / "learning.png", dpi=150
    )
    outcomes = {
        outcome: sum(row["outcome"] == outcome for row in rows) for outcome in ("improved", "worse", "diverged")
    }
    print("\n" + "; ".join(f"{count} {outcome}" for outcome, count in outcomes.items()))
    print(f"Wrote the results to {run_dir}")


def learn_all(configs: list[dict[str, Any]], workers: int) -> Iterator[tuple[Training, float]]:
    """Train on each configuration, in order, in this process or over ``workers`` processes."""
    if workers == 1:
        yield from map(timed_learn, configs)
        return
    # Many processes of one thread each (arm_rmhl_test sets OMP_NUM_THREADS=1 as each imports it).
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        yield from pool.map(timed_learn, configs)


def timed_learn(config: dict[str, Any]) -> tuple[Training, float]:
    """The training of :func:`arm_rmhl_test.feedback.learn`, and the seconds it took."""
    started = time.perf_counter()
    training = learn(config)
    return training, time.perf_counter() - started


def plot_learning(
    combinations: list[tuple[dict[str, Any], dict[str, Any]]], trainings: list[Training], title: str
) -> Figure:
    """The noise-free tracking error (mm) over the trials, a panel per combination of all but the last swept setting."""
    panels: dict[
        tuple[tuple[str, Any], ...], list[tuple[Any, Training]]
    ] = {}  # the last setting's value, and its training
    for (values, _), training in zip(combinations, trainings, strict=True):
        items = list(values.items())
        panels.setdefault(tuple(items[:-1]), []).append((items[-1][1] if items else None, training))
    last_name = next(reversed(combinations[0][0]), None)
    lines = max(len(members) for members in panels.values())
    categorical = last_name is not None and last_name.endswith("seed") and lines <= len(CATEGORICAL)
    colors = CATEGORICAL if categorical else _ramp(lines)

    columns = min(len(panels), 4)
    rows = math.ceil(len(panels) / columns)
    fig = Figure(figsize=(1.0 + 3.6 * columns, 0.9 + 2.8 * rows), facecolor=SURFACE_COLOR, layout="constrained")
    fig.suptitle(f"{title}: noise-free tracking error", color=TITLE_COLOR)
    axes = np.asarray(fig.subplots(rows, columns, sharex=True, sharey=True, squeeze=False))
    pd_error = 1000 * trainings[0].evaluations[0]
    for ax, (grouped, members) in zip(axes.flat, panels.items(), strict=False):
        _style(ax)
        ax.axhline(pd_error, color=PD_COLOR, linestyle="--", linewidth=1.5, label="PD alone")
        for color, (value, training) in zip(colors, members, strict=False):
            _draw_training(ax, training, color, "" if value is None else _format(value))
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(PLAIN)
        ax.yaxis.set_minor_formatter(SPARSE)
        panel = ", ".join(f"{name.rsplit('.', 1)[-1]} = {_format(value)}" for name, value in grouped)
        ax.set_title(panel, color=TITLE_COLOR, fontsize=9)
    for ax in axes.flat[len(panels) :]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("trials learned from", color=TEXT_COLOR)
    for ax in axes[:, 0]:
        ax.set_ylabel("tracking error (mm)", color=TEXT_COLOR)
    legend_title = "" if last_name is None else last_name.rsplit(".", 1)[-1]
    axes.flat[0].legend(title=legend_title, fontsize=7, title_fontsize=7, frameon=False, labelcolor=TEXT_COLOR)
    return fig


def _draw_training(ax: Axes, training: Training, color: str, label: str) -> None:
    """One training's noise-free errors, with a cross at the last evaluation before the arm diverged."""
    reached = np.isfinite(training.evaluations)
    trials, errors = training.evaluated_at[reached], 1000 * training.evaluations[reached]
    ax.plot(trials, errors, color=color, linewidth=2.0, label=label)
    if training.diverged is not None and len(trials):
        ax.plot(trials[-1], errors[-1], marker="x", markersize=8, markeredgewidth=2.0, color=color)


def _ramp(count: int) -> list[Any]:
    """``count`` colors from light to dark blue: steps of the ramp, or of matplotlib's Blues beyond its length."""
    if count == 1:
        return [RAMP[2]]
    if count > len(RAMP):
        return [colormaps["Blues"](0.35 + 0.65 * i / (count - 1)) for i in range(count)]
    return [RAMP[round(i * (len(RAMP) - 1) / (count - 1))] for i in range(count)]


def _format(value: Any) -> str:
    """A swept value as text: numbers in their shortest form."""
    is_number = isinstance(value, int | float) and not isinstance(value, bool)
    return f"{value:g}" if is_number else str(value)


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE_COLOR)
    ax.grid(color=GRID_COLOR, linewidth=0.8)
    ax.tick_params(colors=TEXT_COLOR, labelcolor=TEXT_COLOR, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)


if __name__ == "__main__":
    main()
