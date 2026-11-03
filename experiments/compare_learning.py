# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Compare the learning of several runs of ``learn_feedback.py`` with joint PDs of a ``pd_grid.py`` run.

    uv run python experiments/compare_learning.py experiments/<experiment>/compare_<name>.toml

Each ``[[arm]]`` table names a run of ``experiments/learn_feedback.py`` by its
``run`` (a path under the storage root), with a ``label``; every combination of
the run is one training of the arm, normally one seed each. The ``[pd]`` table
names a run of ``experiments/pd_grid.py`` by its ``run``, and ``marks``: pairs of
a natural frequency (rad/s) and a damping ratio whose tracking error is drawn as a
reference. The closest PD of the grid is always drawn, and so is the PD alone
that the arms learned on, from their first noise-free reach. The run directory
receives:

- ``learning.png``: the noise-free tracking error over the trials learned from, a
  panel per arm: each training thin, their median thick (a diverged training
  counting as infinitely far), and the PDs' errors as dashed lines, labeled
  beside the last panel;
- ``arms.csv``: a row per arm: its trainings, how many improved on the PD alone,
  ended worse, or diverged, and the median, smallest, and largest final error and
  the median best error (m); a diverged training's final error is infinite.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from arm_rmhl_test.arm import Array
from arm_rmhl_test.storage import resolve_run_path, start_run

TEXT_COLOR = "#52514e"
TITLE_COLOR = "#0b0b0b"
GRID_COLOR = "#e4e3de"
SURFACE_COLOR = "#fcfcfb"
PD_COLOR = "#a3a29d"
# The arms are identities: categorical hues, in this order.
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
PLAIN = FuncFormatter(lambda value, _: f"{value:g}")  # log-axis labels as plain numbers
# Between the decades, only 2 and 5 are labeled.
SPARSE = FuncFormatter(
    lambda value, _: f"{value:g}" if round(value / 10 ** np.floor(np.log10(value))) in (2, 5) else ""
)


@dataclass(frozen=True)
class Arm:
    """The trainings of one run of ``learn_feedback.py``."""

    label: str
    rows: list[dict[str, str]]  # runs.csv
    evaluated_at: Array
    evaluations: Array  # (trainings, evaluations), m


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path, help="comparison configuration file (TOML)")
    args = parser.parse_args()

    config, run_dir = start_run(args.config)
    arms = [load_arm(resolve_run_path(table["run"]), table["label"]) for table in config["arm"]]
    pd_table = config["pd"]
    references = pd_references(resolve_run_path(pd_table["run"]), pd_table.get("marks", []))
    references.insert(0, ("PD alone", float(arms[0].evaluations[0, 0])))

    rows = [summarize_arm(arm) for arm in arms]
    with (run_dir / "arms.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(
            f"{row['arm']}: {row['improved']} of {row['trainings']} improved, {row['worse']} worse,"
            f" {row['diverged']} diverged; final error median {1000 * row['median_final_error_m']:.1f} mm"
            f" ({1000 * row['min_final_error_m']:.1f} to {1000 * row['max_final_error_m']:.1f})"
        )
    for label, error in references:
        print(f"{label}: {1000 * error:.1f} mm")
    plot_learning(arms, references, f"Feedback learned: {args.config.stem}").savefig(run_dir / "learning.png", dpi=150)
    print(f"Wrote the results to {run_dir}")


def load_arm(run: Path, label: str) -> Arm:
    """The trainings of a run of ``learn_feedback.py``."""
    with (run / "runs.csv").open() as f:
        rows = list(csv.DictReader(f))
    with np.load(run / "training.npz") as data:
        return Arm(label, rows, data["evaluated_at"], data["evaluations"])


def pd_references(run: Path, marks: list[list[float]]) -> list[tuple[str, float]]:
    """The closest PD of a ``pd_grid.py`` run and the marked ones: a label and a tracking error (m) each.

    Raises
    ------
    KeyError
        If a marked PD is not in the grid.
    """
    with (run / "grid.csv").open() as f:
        grid = {
            (float(row["command.omega"]), float(row["command.damping_ratio"])): float(row["tracking_error_m"])
            for row in csv.DictReader(f)
        }
    (omega, ratio), error = min(grid.items(), key=lambda item: item[1])
    references = [(f"closest PD, {omega:g} rad/s, {ratio:g}", error)]
    for omega, ratio in marks:
        if (omega, ratio) not in grid:
            msg = f"the PD of {omega:g} rad/s and damping ratio {ratio:g} is not in the grid"
            raise KeyError(msg)
        references.append((f"PD, {omega:g} rad/s, {ratio:g}", grid[omega, ratio]))
    return references


def summarize_arm(arm: Arm) -> dict[str, Any]:
    """How an arm's trainings went: the outcomes counted, and the final and best errors (m) over them."""
    outcomes = [row["outcome"] for row in arm.rows]
    final = np.array([np.inf if row["outcome"] == "diverged" else float(row["final_error_m"]) for row in arm.rows])
    best = np.array([float(row["best_error_m"]) for row in arm.rows])
    return {
        "arm": arm.label,
        "trainings": len(arm.rows),
        "improved": outcomes.count("improved"),
        "worse": outcomes.count("worse"),
        "diverged": outcomes.count("diverged"),
        "median_final_error_m": float(np.median(final)),
        "min_final_error_m": float(final.min()),
        "max_final_error_m": float(final.max()),
        "median_best_error_m": float(np.nanmedian(best)) if np.isfinite(best).any() else np.nan,
    }


def plot_learning(arms: list[Arm], references: list[tuple[str, float]], title: str) -> Figure:
    """The noise-free tracking error (mm) over the trials, a panel per arm, with the PDs' errors."""
    fig = Figure(figsize=(1.2 + 3.8 * len(arms), 3.6), facecolor=SURFACE_COLOR, layout="constrained")
    fig.suptitle(f"{title}: noise-free tracking error", color=TITLE_COLOR)
    axes = np.atleast_1d(fig.subplots(1, len(arms), sharey=True, squeeze=False)[0])
    for ax, arm, color in zip(axes, arms, CATEGORICAL, strict=False):
        _style(ax)
        for _, error in references:
            ax.axhline(1000 * error, color=PD_COLOR, linestyle="--", linewidth=1.2)
        # A diverged training counts as infinitely far from then on: the median holds while most remain.
        errors = 1000 * np.where(np.isfinite(arm.evaluations), arm.evaluations, np.inf)
        for training in errors:
            ax.plot(arm.evaluated_at, training, color=color, linewidth=0.8, alpha=0.45)
        ax.plot(arm.evaluated_at, np.median(errors, axis=0), color=color, linewidth=2.2)
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(PLAIN)
        ax.yaxis.set_minor_formatter(SPARSE)
        ax.set_title(f"{arm.label} ({len(arm.rows)} trainings)", color=TITLE_COLOR, fontsize=9)
        ax.set_xlabel("trials learned from", color=TEXT_COLOR)
    axes[0].set_ylabel("tracking error (mm)", color=TEXT_COLOR)
    # The panels share the y-axis, so the PDs are labeled once, beside the last panel, clear of the curves.
    for label, error in references:
        axes[-1].annotate(
            label,
            (1.0, 1000 * error),
            xycoords=("axes fraction", "data"),
            xytext=(4, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=6.5,
            color=TEXT_COLOR,
            annotation_clip=False,
        )
    return fig


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE_COLOR)
    ax.grid(color=GRID_COLOR, linewidth=0.8)
    ax.tick_params(colors=TEXT_COLOR, labelcolor=TEXT_COLOR, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)


if __name__ == "__main__":
    main()
