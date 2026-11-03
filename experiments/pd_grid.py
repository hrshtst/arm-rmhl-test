# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Track the reach with the joint PD alone, for every combination of a sweep of its gains.

    uv run python experiments/pd_grid.py experiments/<experiment>/pd_grid.toml

The configuration describes the arm, the reach and the joint PD of ``[command]``
(see :mod:`arm_rmhl_test.arm`), and a ``[sweep]`` of its settings (see
:mod:`arm_rmhl_test.sweeps`), normally ``"command.omega"`` and
``"command.damping_ratio"``. Every combination makes one reach, without feedback
learned or noise. The run directory receives:

- ``grid.csv``: one row per combination: its values, the PD's gains of each joint
  ``kp_<joint>`` (N m/rad) and ``kd_<joint>`` (N m s/rad), the reach's tracking
  error (m), its effort (N^2 m^2 s), and the peak torque of any joint (N m); a
  reach that diverged has an infinite tracking error and no effort or peak;
- ``grid.png``, when two settings are swept: the tracking error over them, the
  first along the horizontal axis.

The combination that tracks closest is printed.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.colors import LogNorm
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from arm_rmhl_test.arm import command_gains, effort, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.storage import start_run
from arm_rmhl_test.sweeps import expand

TEXT_COLOR = "#52514e"
TITLE_COLOR = "#0b0b0b"
SURFACE_COLOR = "#fcfcfb"
COLORMAP = "Blues"  # sequential: darker is a larger error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", type=Path, help="configuration file (TOML)")
    args = parser.parse_args()

    config, run_dir = start_run(args.config)
    combinations = expand(config)
    rows = [values | track(variant) for values, variant in combinations]
    with (run_dir / "grid.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    names = list(config.get("sweep", {}))
    best = min(rows, key=lambda row: row["tracking_error_m"])
    values = ", ".join(f"{name}={best[name]:g}" for name in names)
    finite = sum(np.isfinite(row["tracking_error_m"]) for row in rows)
    print(f"{len(rows)} combinations, {finite} without divergence")
    print(
        f"Closest tracking: {values or 'the [command] PD'}: {1000 * best['tracking_error_m']:.1f} mm;"
        f" effort {best['effort']:.3g} N^2 m^2 s; peak torque {best['peak_torque_nm']:.3g} N m"
    )
    if len(names) == 2:
        title = f"Joint PD alone: {args.config.stem}"
        plot_grid(rows, config["sweep"], title).savefig(run_dir / "grid.png", dpi=150)
    print(f"Wrote the results to {run_dir}")


def track(config: dict[str, Any]) -> dict[str, float]:
    """The PD's gains and how its reach went: tracking error, effort, and peak torque."""
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    row = {f"kp_{joint + 1}": float(gain) for joint, gain in enumerate(kp)}
    row |= {f"kd_{joint + 1}": float(gain) for joint, gain in enumerate(kd)}
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            run = run_reach(arm, reach, kp, kd)
    except OverflowError:  # skelarm's kinematics, on a torque too large for them
        return row | {"tracking_error_m": np.inf, "effort": np.nan, "peak_torque_nm": np.nan}
    error = tracking_error(run, reach)
    finite = np.isfinite(error)
    return row | {
        "tracking_error_m": error,
        "effort": effort(run, reach) if finite else np.nan,
        "peak_torque_nm": float(np.abs(run.tau).max()) if finite else np.nan,
    }


def plot_grid(rows: list[dict[str, Any]], sweep: dict[str, list[Any]], title: str) -> Figure:
    """A heatmap of the tracking error (mm) over the two swept settings; the closest cell is outlined."""
    x_name, y_name = sweep
    grid = np.full((len(sweep[y_name]), len(sweep[x_name])), np.nan)
    for row in rows:
        grid[sweep[y_name].index(row[y_name]), sweep[x_name].index(row[x_name])] = 1000 * row["tracking_error_m"]
    shown = np.where(np.isfinite(grid), grid, np.nan)
    norm = LogNorm(vmin=float(np.nanmin(shown)), vmax=float(np.nanmax(shown)))

    size = (1.0 + 0.75 * len(sweep[x_name]), 1.6 + 0.5 * len(sweep[y_name]))
    fig = Figure(figsize=size, facecolor=SURFACE_COLOR, layout="constrained")
    ax = fig.subplots()
    image = ax.imshow(shown, cmap=COLORMAP, norm=norm, origin="lower", aspect="auto")
    for (y, x), value in np.ndenumerate(grid):
        dark = np.isfinite(value) and norm(value) > 0.6
        text = f"{value:.3g}" if np.isfinite(value) else "diverged"
        ax.text(x, y, text, ha="center", va="center", fontsize=7, color="white" if dark else TITLE_COLOR)
    y_best, x_best = np.unravel_index(np.nanargmin(shown), shown.shape)
    ax.add_patch(Rectangle((x_best - 0.5, y_best - 0.5), 1.0, 1.0, fill=False, edgecolor=TITLE_COLOR, linewidth=2.0))
    ax.set_xticks(range(len(sweep[x_name])), [f"{v:g}" for v in sweep[x_name]])
    ax.set_yticks(range(len(sweep[y_name])), [f"{v:g}" for v in sweep[y_name]])
    ax.set_xlabel(x_name, color=TEXT_COLOR)
    ax.set_ylabel(y_name, color=TEXT_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelcolor=TEXT_COLOR, labelsize=8)
    ax.set_title(f"{title}\ntracking error (mm); the closest outlined", color=TITLE_COLOR, fontsize=10)
    fig.colorbar(image, ax=ax, shrink=0.9).ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    return fig


if __name__ == "__main__":
    main()
