# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Train runs of the decorrelated rule again, recording the matrix its update divides by.

    uv run python experiments/record_decorrelation.py experiments/<experiment>/decorrelation_<name>.toml --workers 10

The decorrelated rule changes the feedback's weights after each learning reach by
``eta (R - R_avg) inv(C + lambda I) E``: ``C`` sums the feedback's input times its
transpose over the reach, ``E`` the input times the exploration noise, and ``lambda``
is the rule's ``decorrelation``. Each ``[[arm]]`` table names a run of
``experiments/learn_feedback.py`` or ``learn_combined.py`` by its ``run`` (a path
under the storage root), with a ``label``; its feedback must be decorrelated and
without the constant, and every arm must have as many combinations. A run whose
``training.npz`` holds the feedforward's weights is trained as ``learn_combined.py``
trains, and any other as ``learn_feedback.py`` does. Every combination of the run is trained again from its own
``config.toml``, for the first ``trials`` reaches of the ``[training]`` table, and
each learning reach's ``C`` is recorded. Neither the package nor rclib changes: the
recording wraps :func:`arm_rmhl_test.feedback.feedback_torque`, through which both
runners' trainings get the feedback's torque.

Two checks must hold on every learning reach, or the runner stops:

- the reach's tracking error equals the stored one, bit for bit;
- the change of the weights over the reach is ``inv(C + lambda I) E`` times one
  number, to a relative residual of ``1e-9``, so that the ``C`` recorded is the
  rule's.

The run directory receives:

- ``decorrelation.npz``: ``eigenvalues`` ``(arms, trainings, trials, inputs)``,
  the eigenvalues of each learning reach's ``C``, largest first; ``errors``
  ``(arms, trainings, trials)``, the learning reaches' tracking errors (m);
  ``residual`` ``(arms, trainings, trials - 1)``, the second check's; and ``ridge``
  ``(arms,)``, each arm's ``lambda``;
- ``arms.csv``: a row per arm: its label, run, trainings and ``lambda``, the largest
  residual, and the median over its trainings of the directions of ``C`` above
  ``lambda`` after 1, 10, 30, 100, 300 and 1,000 reaches, where it has them;
- ``decorrelation.png``: each eigenvalue of ``C`` over the reaches, the median over
  the trainings, a panel per arm, against ``lambda``.

With ``--workers``, the trainings are spread over that many processes, each
computing with one thread; their results are the same as in one process.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import multiprocessing
import tomllib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from arm_rmhl_test import combined, feedback
from arm_rmhl_test.arm import Array
from arm_rmhl_test.storage import resolve_run_path, start_run
from arm_rmhl_test.sweeps import expand

TOLERANCE = 1e-9  # the second check's largest relative residual
AFTER = (1, 10, 30, 100, 300, 1000)  # reaches at which arms.csv counts the directions above lambda
TEXT_COLOR = "#52514e"
TITLE_COLOR = "#0b0b0b"
GRID_COLOR = "#e4e3de"
SURFACE_COLOR = "#fcfcfb"
REF_COLOR = "#a3a29d"
# The eigenvalues are ordered magnitudes: a blue ramp, dark for the largest.
RAMP = ["#0d366b", "#1c5cab", "#5598e7", "#86b6ef"]
PLAIN = FuncFormatter(lambda value, _: f"{value:g}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path, help="configuration file (TOML)")
    parser.add_argument(
        "--workers", type=int, default=1, help="worker processes, of one thread each (default 1: in this process)"
    )
    args = parser.parse_args()

    config, run_dir = start_run(args.config)
    trials = int(config["training"]["trials"])
    arms = [(table["label"], resolve_run_path(table["run"])) for table in config["arm"]]
    jobs = [(run, index, trials) for _, run in arms for index in range(len(_combinations(run)))]
    print(f"{len(arms)} arms, {len(jobs)} trainings, {trials} trials each", flush=True)
    results = dict(zip(jobs, _record_all(jobs, args.workers), strict=True))

    rows: list[dict[str, Any]] = []
    arrays: dict[str, list[Any]] = {"eigenvalues": [], "errors": [], "residual": [], "ridge": []}
    for label, run in arms:
        records = [results[job] for job in jobs if job[0] == run]
        ridge = _ridge(_stored_config(run))
        eigenvalues = np.stack([record["eigenvalues"] for record in records])
        residual = np.stack([record["residual"] for record in records])
        above = np.median((eigenvalues > ridge).sum(axis=2), axis=0)
        rows.append(
            {"arm": label, "run": run.name, "trainings": len(records), "ridge": ridge}
            | {"max_residual": float(residual.max(initial=0.0))}
            | {f"above_after_{n}": float(above[n - 1]) for n in AFTER if n <= trials}
        )
        arrays["eigenvalues"].append(eigenvalues)
        arrays["errors"].append(np.stack([record["errors"] for record in records]))
        arrays["residual"].append(residual)
        arrays["ridge"].append(ridge)
        print(f"{label}: {len(records)} trainings reproduced; largest residual {rows[-1]['max_residual']:.1e}")
        counts = ", ".join(f"{above[n - 1]:g} after {n}" for n in AFTER if n <= trials)
        print(f"  directions above the ridge, median: {counts}")

    stacked = {key: np.stack(value) for key, value in arrays.items()}
    np.savez_compressed(run_dir / "decorrelation.npz", allow_pickle=False, **stacked)
    with (run_dir / "arms.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plot_eigenvalues([label for label, _ in arms], stacked["eigenvalues"], arrays["ridge"]).savefig(
        run_dir / "decorrelation.png", dpi=150
    )
    print(f"Wrote the results to {run_dir}")


def record(run: Path, index: int, trials: int) -> dict[str, Array]:
    """Train combination ``index`` of ``run`` again for ``trials`` reaches; each learning reach's ``C`` and the checks.

    Raises
    ------
    ValueError
        If the run's feedback is not decorrelated, or has the constant.
    RuntimeError
        If a check fails.
    """
    stored_config = _stored_config(run)
    ridge = _ridge(stored_config)
    if feedback.feedback_constant(stored_config):
        msg = f"{run.name}: the feedback has the constant; only a feedback without it is recorded"
        raise ValueError(msg)
    config = _combinations(run)[index]
    config["training"] = config["training"] | {"trials": trials}
    with np.load(run / "training.npz") as stored:
        expected = stored["errors"][index, :trials]
        learn = combined.learn if "feedforward_weights" in stored else feedback.learn  # which runner made it

    reaches: list[dict[str, Array]] = []
    original = feedback.feedback_torque

    def recording(model: Any, scale: Array, *, explore: bool) -> feedback.Feedback:
        torque = original(model, scale, explore=explore)
        if not explore:
            return torque
        weights = feedback.readout_weights(model)[:-1]  # the input's rows; the bias row is zero
        inputs, joints = weights.shape
        reach = {"weights": weights, "C": np.zeros((inputs, inputs)), "E": np.zeros((inputs, joints))}
        reaches.append(reach)

        def explored(error: Array) -> Array:
            tau = torque(error)
            reach["C"] += np.outer(error, error)
            noise = tau / scale - error @ weights  # the output less its noise-free part
            reach["E"] += np.outer(error, noise)
            return tau

        return explored

    feedback.feedback_torque = recording
    try:
        training = learn(config)
    finally:
        feedback.feedback_torque = original

    label = f"{run.name}, combination {index}"
    if not np.array_equal(training.errors, expected, equal_nan=True):
        first = int(np.flatnonzero(training.errors != expected)[0])
        msg = f"{label}: reach {first + 1} gives {training.errors[first]!r}, stored {expected[first]!r}"
        raise RuntimeError(msg)
    if len(reaches) != trials:
        msg = f"{label}: {len(reaches)} learning reaches recorded, not {trials}"
        raise RuntimeError(msg)
    residual = np.array([residual_from_rule(now, after, ridge) for now, after in itertools.pairwise(reaches)])
    if residual.size and residual.max() > TOLERANCE:
        worst = int(residual.argmax())
        msg = f"{label}: reach {worst + 1}'s change is off inv(C + lambda I) E by {residual[worst]:.1e}"
        raise RuntimeError(msg)
    eigenvalues = np.array([np.linalg.eigvalsh(reach["C"])[::-1] for reach in reaches])
    return {"eigenvalues": eigenvalues, "errors": training.errors, "residual": residual}


def residual_from_rule(now: dict[str, Array], after: dict[str, Array], ridge: float) -> float:
    """How far the change of the weights over a reach is from a multiple of ``inv(C + ridge I) E``, relatively.

    ``now`` holds the reach's weights at its start, its ``C`` and its ``E``; ``after``
    the next learning reach's weights at its start. The multiple is the least-squares
    one; the residual is relative to the larger of the change and the fitted multiple.
    """
    change = after["weights"] - now["weights"]
    direction = np.linalg.solve(now["C"] + ridge * np.eye(len(now["C"])), now["E"])
    factor = np.sum(change * direction) / np.sum(direction * direction)
    size = max(float(np.linalg.norm(change)), abs(factor) * float(np.linalg.norm(direction)))
    return float(np.linalg.norm(change - factor * direction)) / size if size > 0 else 0.0


def plot_eigenvalues(labels: list[str], eigenvalues: Array, ridges: list[float]) -> Figure:
    """Each eigenvalue of ``C`` over the reaches, the median over the trainings, a panel per arm, against the ridge."""
    fig = Figure(figsize=(4.2 * len(labels), 3.6), layout="constrained", facecolor=SURFACE_COLOR)
    axes = fig.subplots(1, len(labels), sharey=True, squeeze=False)[0]
    reaches = np.arange(1, eigenvalues.shape[2] + 1)
    for ax, label, values, ridge in zip(axes, labels, eigenvalues, ridges, strict=True):
        for k, color in zip(range(values.shape[2]), RAMP, strict=False):
            ax.plot(reaches, np.median(values[:, :, k], axis=0), color=color, lw=1.6, label=f"eigenvalue {k + 1}")
        ax.axhline(ridge, color=REF_COLOR, lw=1.0, ls=(0, (4, 3)))
        ax.annotate(
            f"ridge, {ridge:g}", (1.0, ridge), xycoords=("axes fraction", "data"), xytext=(-2, 3),
            textcoords="offset points", ha="right", va="bottom", fontsize=8, color=TEXT_COLOR,
        )  # fmt: skip
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.xaxis.set_major_formatter(PLAIN)
        ax.yaxis.set_major_formatter(PLAIN)
        ax.set_title(label, loc="left", fontsize=9.5, color=TITLE_COLOR)
        ax.set_xlabel("learning reach", color=TEXT_COLOR)
        ax.set_facecolor(SURFACE_COLOR)
        ax.grid(color=GRID_COLOR, lw=0.6)
        ax.tick_params(colors=TEXT_COLOR)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].set_ylabel("eigenvalue of C, median over trainings", color=TEXT_COLOR)
    axes[0].legend(frameon=False, fontsize=8)
    return fig


def _record_all(jobs: list[tuple[Path, int, int]], workers: int) -> list[dict[str, Array]]:
    if workers == 1:
        return [record(*job) for job in jobs]
    # Many processes of one thread each (arm_rmhl_test sets OMP_NUM_THREADS=1 as each imports it).
    with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(record, *zip(*jobs, strict=True)))


def _stored_config(run: Path) -> dict[str, Any]:
    with (run / "config.toml").open("rb") as f:
        return tomllib.load(f)


def _combinations(run: Path) -> list[dict[str, Any]]:
    """The run's combinations, in the order of its ``runs.csv`` and ``training.npz``."""
    return [variant for _, variant in expand(_stored_config(run))]


def _ridge(config: dict[str, Any]) -> float:
    """The ``lambda`` of the configuration's rule, as rclib's preset and its settings give it."""
    ridge = feedback.make_rule(config["rule"]).decorrelation
    if ridge is None:
        msg = "the rule is not decorrelated: it has no matrix C"
        raise ValueError(msg)
    return float(ridge)


if __name__ == "__main__":
    main()
