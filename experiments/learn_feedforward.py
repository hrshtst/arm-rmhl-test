# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Learn feedforward torques by feedback-error learning, for every combination of a sweep.

    uv run python experiments/learn_feedforward.py experiments/<experiment>/<configuration>.toml --workers 16

The configuration describes the arm, the reach and the joint PD of ``[command]``
(see :mod:`arm_rmhl_test.arm`), the RLS readout and the training (see
:mod:`arm_rmhl_test.feedforward`), and an optional ``[sweep]`` of its settings (see
:mod:`arm_rmhl_test.sweeps`), such as ``"readout.forgetting"``. Every combination
trains a fresh model, from zero feedforward. The run directory receives, as from
``learn_feedback.py``:

- ``runs.csv``: one row per combination: its values, the summary of
  :func:`arm_rmhl_test.feedforward.summarize` (the tracking errors of the PD alone,
  at the end and at best, the outcome, and the final weights of the torque), and the
  seconds it took;
- ``training.npz``: the course of every training, a row per combination in the
  order of ``runs.csv``: the tracking error of each reach learned from, ``errors``
  ``(combinations, trials)``; the trials learned from before each evaluation,
  ``evaluated_at``; their tracking errors, ``evaluations``
  ``(combinations, evaluations)``; the readout's weights then, ``weights``
  ``(combinations, evaluations, 3 joints + 1, joints)``; and ``scale``, 1;
- ``learning.png``: the evaluations' tracking error over the trials learned from,
  as from ``learn_feedback.py``.

An evaluation is a reach that learns nothing, with the weights as they stand; the
figure calls it noise-free, as there is no noise in feedback-error learning at all.
With ``--workers``, the combinations are spread over that many processes, each
computing with one thread; their results are the same as in one process.
"""

from __future__ import annotations

import time
from typing import Any

from learn_feedback import run_sweep

from arm_rmhl_test.feedback import Training
from arm_rmhl_test.feedforward import learn, summarize


def main() -> None:
    run_sweep(__doc__ or "", timed_learn, summarize, "Feedforward learned")


def timed_learn(config: dict[str, Any]) -> tuple[Training, float]:
    """The training of :func:`arm_rmhl_test.feedforward.learn`, and the seconds it took."""
    started = time.perf_counter()
    training = learn(config)
    return training, time.perf_counter() - started


if __name__ == "__main__":
    main()
