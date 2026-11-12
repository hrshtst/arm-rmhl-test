# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Draw the figures of report 007 from the copies of its runs and of reports 001's, 004's, 005's and 006's.

    uv run python reports/007-plain-rule/make_figures.py

It writes, under ``figures/``:

- ``final.png``: the noise-free tracking error of every arm over the reaches, each
  seed thin and the median over the seeds thick, against the PDs: a row per
  feedback scale, the combined controllers and the feedforward alone on the left,
  the feedback alone on the right;
- ``levels.png``: the reach from which each seed stays closer than each PD, per arm;
- ``mechanism.png``: the eigenvalues of ``C`` over the first 1,000 learning reaches
  of the two decorrelated arms trained again, a panel per eigenvalue, against the
  ridge term and the eigenvalue at which the decorrelated rule's step equals the
  plain rule's at arm A's learning rate.
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
    SCALES,
    arms,
    grid_errors,
    latest,
    load_config,
    load_course,
    runs_of,
    stays_below,
    trained_again,
)
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator

FIGURES = HERE / "figures"
INK = "#3a3936"
MUTED = "#6f6e69"
REF = "#8f8e89"
GRID = "#e8e7e3"
# The arms are identities: categorical hues, in this order, as compare_learning.py draws them.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
COMBINED_PANEL = 3  # the first three arms: the combined controllers and the feedforward alone
NEVER = 80000.0  # where a level never reached is drawn, right of the axis's last tick
DECORRELATED_COLORS = {"combined": SERIES[1], "feedback alone": SERIES[5]}  # the arms trained again

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
    results = HERE / "results"
    pds = grid_errors(latest(REPORT_001, "-pd_grid"))
    runs = {scale: runs_of(scale, results) for scale in SCALES}
    draw_final(runs, pds)
    draw_levels(runs, pds)
    plain_rate = load_config(latest(results, "-final_combined_inertia"))["rule"]["learning_rate"]
    draw_mechanism(latest(results, "-decorrelation_inertia"), plain_rate)


def millimetres(values: np.ndarray) -> np.ndarray:
    scaled = 1000.0 * np.asarray(values, dtype=float)
    return np.where(np.isfinite(scaled), np.minimum(scaled, 1500.0), 1500.0)


def draw_final(runs, pds) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(9.4, 8.0), sharex=True, sharey=True, layout="constrained")
    marks = [(f"PD, {omega:g} rad/s, {ratio:g}", pds[omega, ratio]) for omega, ratio in MARKED_PDS]
    marks = [("weak PD alone", pds[5.0, 0.7]), *marks, ("closest PD, 80 rad/s, 0.2", pds[80.0, 0.2])]
    for row, (scale, title) in zip(axes, SCALES.items(), strict=True):
        arms_of_scale = list(runs[scale].items())
        for index, ((label, run), color) in enumerate(zip(arms_of_scale, SERIES, strict=True)):
            ax = row[0] if index < COMBINED_PANEL else row[1]
            at, evaluations = load_course(run)
            errors = millimetres(evaluations)
            if len(errors) > 1:
                for errors_of_seed in errors:
                    ax.plot(at, errors_of_seed, color=color, lw=0.6, alpha=0.35, zorder=2)
            ax.plot(at, np.median(errors, axis=0), color=color, lw=2.0, label=label, zorder=3)
        row[0].set_title("combined, and the feedforward alone")
        row[1].set_title("the feedback alone")
        for ax in row:
            for text, value in marks:
                ax.axhline(1000.0 * value, color=REF, lw=0.8, ls=(0, (4, 3)), zorder=1)
                if ax is row[-1]:
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
            _reach_axes(ax)
        row[0].set_ylabel(f"{title}\ntracking error (mm)")
    for ax in axes[-1]:
        ax.set_xlabel("reaches learned from")
    handles, labels = [], []
    for ax in axes[0]:
        more_handles, more_labels = ax.get_legend_handles_labels()
        handles += more_handles
        labels += more_labels
    fig.legend(handles, labels, loc="outside lower center", ncol=2)
    fig.savefig(FIGURES / "final.png", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


def _reach_axes(ax) -> None:
    ax.set_yscale("log")
    ax.set_ylim(0.4, 1500)
    ax.yaxis.set_major_locator(FixedLocator([0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_xscale("symlog", linthresh=1, linscale=0.45)
    ax.xaxis.set_major_locator(FixedLocator([0, 1, 10, 100, 1000, 10000]))
    ax.xaxis.set_minor_locator(NullLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    ax.set_xlim(0, 10000)


def draw_levels(runs, pds) -> None:
    fig = plt.figure(figsize=(10.0, 7.2), layout="constrained")
    labels = list(arms("inertia"))
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


def draw_mechanism(run, plain_rate: float) -> None:
    with np.load(run / "decorrelation.npz") as data:
        eigenvalues, ridge = data["eigenvalues"], data["ridge"]  # (arms, trainings, trials, inputs)
    labels, rates = trained_again(run)
    if len(set(rates)) != 1 or len(set(ridge.tolist())) != 1:
        msg = f"the arms trained again differ in their learning rates {rates} or ridge terms {ridge}"
        raise ValueError(msg)
    equal = rates[0] / plain_rate - float(ridge[0])  # the eigenvalue at which both rules step alike
    reaches = np.arange(1, eigenvalues.shape[2] + 1)
    inputs = eigenvalues.shape[3]
    fig, grid = plt.subplots(
        1, inputs, figsize=(10.0, 3.4), sharex=True, sharey=True, squeeze=False, layout="constrained"
    )
    axes = list(grid[0])
    for direction, ax in enumerate(axes):
        for arm, label in enumerate(labels):
            color = DECORRELATED_COLORS["combined" if label.startswith("combined") else "feedback alone"]
            values = eigenvalues[arm, :, :, direction]
            for seed in values:
                ax.plot(reaches, seed, color=color, lw=0.5, alpha=0.3, zorder=2)
            legend = f"{label}, median" if direction == 0 else None
            ax.plot(reaches, np.median(values, axis=0), color=color, lw=1.8, label=legend, zorder=3)
        ax.axhline(float(ridge[0]), color=REF, lw=0.8, ls=(0, (4, 3)), zorder=1)
        ax.axhline(equal, color=INK, lw=0.8, ls=(0, (1, 2)), zorder=1)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(1, reaches[-1])
        ax.set_ylim(1e-3, 2e3)
        ax.xaxis.set_major_locator(FixedLocator([1, 10, 100, 1000]))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
        ax.yaxis.set_major_locator(FixedLocator([1e-3, 1e-2, 1e-1, 1, 10, 100, 1000]))
        ax.yaxis.set_minor_locator(NullLocator())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_title(f"eigenvalue {direction + 1}", fontsize=9)
        ax.set_xlabel("learning reach")
    last = axes[-1]
    for value, text in ((float(ridge[0]), "ridge term, 1"), (equal, f"steps equal at {plain_rate:g}")):
        last.annotate(
            text,
            xy=(1.0, value),
            xycoords=("axes fraction", "data"),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            ha="left",
            fontsize=7.5,
            color=MUTED,
            annotation_clip=False,
        )
    axes[0].set_ylabel("eigenvalue of C")
    fig.legend(loc="outside lower center", ncol=2)
    fig.savefig(FIGURES / "mechanism.png", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)


if __name__ == "__main__":
    main()
