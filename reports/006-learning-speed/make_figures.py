# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Draw the figures of report 006 from the copies of its runs and of reports 001's, 004's and 005's.

    uv run python reports/006-learning-speed/make_figures.py

It writes, under ``figures/``:

- ``final.png``: the noise-free tracking error of every arm over the reaches, each
  seed thin and the median over the seeds thick, a panel per feedback scale, against
  the PDs;
- ``levels.png``: the reach from which each seed stays closer than each PD, per arm.
"""

from __future__ import annotations

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from make_tables import (
    HERE,
    MARKED_PDS,
    REPORT_001,
    REPORT_004,
    REPORT_005,
    SCALES,
    arms,
    grid_errors,
    latest,
    load_course,
    stays_below,
)
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

FIGURES = HERE / "figures"
INK = "#3a3936"
MUTED = "#6f6e69"
REF = "#8f8e89"
GRID = "#e8e7e3"
# The arms are identities: categorical hues, in this order, the first four as in report 003's figure.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]
NEVER = 80000.0  # where a level never reached is drawn, right of the axis's last tick
WHERE = {"this": HERE / "results", "001": REPORT_001, "004": REPORT_004, "005": REPORT_005}

plt.rcParams.update(
    {
        "figure.dpi": 100,
        "savefig.dpi": 200,
        "font.size": 9.5,
        "axes.titlesize": 10,
        "axes.labelsize": 9.5,
        "axes.edgecolor": "#c9c7c0",
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    }
)


def main() -> None:
    FIGURES.mkdir(exist_ok=True)
    pds = grid_errors(latest(REPORT_001, "-pd_grid"))
    runs = {
        scale: {label: latest(WHERE[source], name) for label, (source, name) in arms(scale).items()} for scale in SCALES
    }
    draw_final(runs, pds)
    draw_levels(runs, pds)


def millimetres(values: np.ndarray) -> np.ndarray:
    scaled = 1000.0 * np.asarray(values, dtype=float)
    return np.where(np.isfinite(scaled), np.minimum(scaled, 1500.0), 1500.0)


def draw_final(runs, pds) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.6), sharey=True, layout="constrained")
    marks = [(f"PD, {omega:g} rad/s, {ratio:g}", pds[omega, ratio]) for omega, ratio in MARKED_PDS]
    marks = [("weak PD alone", pds[5.0, 0.7]), *marks, ("closest PD, 80 rad/s, 0.2", pds[80.0, 0.2])]
    for ax, (scale, title) in zip(axes, SCALES.items(), strict=True):
        for (label, run), color in zip(runs[scale].items(), SERIES, strict=True):
            at, evaluations = load_course(run)
            errors = millimetres(evaluations)
            if len(errors) > 1:
                for row in errors:
                    ax.plot(at, row, color=color, lw=0.6, alpha=0.35, zorder=2)
            ax.plot(at, np.median(errors, axis=0), color=color, lw=2.0, label=label, zorder=3)
        for text, value in marks:
            ax.axhline(1000.0 * value, color=REF, lw=0.8, ls=(0, (4, 3)), zorder=1)
            if ax is axes[-1]:
                ax.annotate(
                    text,
                    xy=(1.0, 1000.0 * value),
                    xycoords=("axes fraction", "data"),
                    xytext=(4, 0),
                    textcoords="offset points",
                    va="center",
                    ha="left",
                    fontsize=7.5,
                    color=MUTED,
                    annotation_clip=False,
                )
        ax.set_yscale("log")
        ax.set_ylim(0.04, 1500)  # the staged raw torque's seeds reach down to 0.05 mm
        ax.yaxis.set_major_locator(FixedLocator([0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_xscale("symlog", linthresh=1, linscale=0.45)
        ax.xaxis.set_major_locator(FixedLocator([0, 1, 10, 100, 1000, 10000]))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
        ax.set_xlim(0, 10000)
        ax.set_xlabel("reaches learned from")
        ax.set_title(title)
    axes[0].set_ylabel("tracking error (mm)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=2)
    fig.savefig(FIGURES / "final.png", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


def draw_levels(runs, pds) -> None:
    fig = plt.figure(figsize=(10.0, 6.4), layout="constrained")
    labels = list(runs["inertia"])
    positions = {label: len(labels) - 1 - i for i, label in enumerate(labels)}
    subfigs = np.asarray(fig.subfigures(2, 1, hspace=0.04)).ravel()
    for subfig, (scale, title) in zip(subfigs, SCALES.items(), strict=True):
        row = subfig.subplots(1, 3, sharex=True, sharey=True)
        subfig.suptitle(title, x=0.0, ha="left", fontweight="bold", fontsize=10.5)
        for ax, pd in zip(row, MARKED_PDS, strict=True):
            level = pds[pd]
            for (label, run), color in zip(runs[scale].items(), SERIES, strict=True):
                at, evaluations = load_course(run)
                reaches = [stays_below(at, errors, level) for errors in evaluations]
                median = stays_below(at, np.median(evaluations, axis=0), level)
                y = positions[label]
                offsets = np.linspace(-0.22, 0.22, len(reaches)) if len(reaches) > 1 else [0.0]
                for offset, reach in zip(offsets, reaches, strict=True):
                    never = reach is None
                    ax.plot(
                        NEVER if never else max(reach, 1),
                        y + offset,
                        "o",
                        ms=4,
                        mfc="none" if never else color,
                        mec=color,
                        alpha=0.75,
                        zorder=2,
                    )
                ax.plot(
                    NEVER if median is None else max(median, 1),
                    y,
                    "D",
                    ms=8,
                    mfc="none" if median is None else color,
                    mec="white" if median is not None else color,
                    mew=1.2,
                    zorder=3,
                )
            ax.set_xscale("log")
            ax.xaxis.set_major_locator(FixedLocator([1, 10, 100, 1000, 10000, NEVER]))
            ax.xaxis.set_minor_locator(NullLocator())
            ax.xaxis.set_major_formatter(FuncFormatter(_reach_label))
            ax.set_xlim(0.8, 160000)
            ax.set_ylim(-0.6, len(labels) - 0.4)
            ax.set_yticks([positions[label] for label in labels], labels)
            ax.set_title(f"{1000.0 * level:.1f} mm: PD, {pd[0]:g} rad/s, {pd[1]:g}", fontsize=9)
        subfig.supxlabel("the reach from which the error stays below the level", fontsize=9)
    fig.savefig(FIGURES / "levels.png", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


def _reach_label(value: float, _: object) -> str:
    if value == NEVER:
        return "never"
    return f"{value / 1000:g}k" if value >= 1000 else f"{value:g}"


if __name__ == "__main__":
    main()
