# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Learn feedforward and feedback torques together, for every combination of a sweep.

    uv run python experiments/learn_combined.py experiments/<experiment>/<configuration>.toml --workers 16

The configuration describes the arm, the reach and the joint PD of ``[command]``
(see :mod:`arm_rmhl_test.arm`), the learners, the schedule and the training (see
:mod:`arm_rmhl_test.combined`), and an optional ``[sweep]`` of its settings (see
:mod:`arm_rmhl_test.sweeps`), such as ``"schedule.kind"``, ``"rule.learning_rate"``
or ``"readout.forgetting"``. Every combination trains fresh learners, from zero
weights. Without a ``[readout]`` table it learns no feedforward, and without a
``[rule]`` table no feedback. The run directory receives, as from
``learn_feedback.py``:

- ``runs.csv``: one row per combination: its values, the summary of
  :func:`arm_rmhl_test.combined.summarize` (the noise-free tracking errors of the PD
  alone, at the end and at best, the outcome, and the final gains of the feedback
  and weights of the feedforward), and the seconds it took;
- ``training.npz``: the course of every training, a row per combination in the
  order of ``runs.csv``: as from ``learn_feedback.py``, where ``weights`` and
  ``scale`` are the feedback's, and the feedforward's weights at each evaluation,
  ``feedforward_weights`` ``(combinations, evaluations, 3 joints + 1, joints)``;
  zero for a learner left out;
- ``learning.png``: the noise-free tracking error over the trials learned from, as
  from ``learn_feedback.py``.

With ``--workers``, the combinations are spread over that many processes, each
computing with one thread; their results are the same as in one process.
"""

from __future__ import annotations

import time
from typing import Any

from learn_feedback import run_sweep

from arm_rmhl_test.combined import learn, summarize
from arm_rmhl_test.feedback import Training


def main() -> None:
    run_sweep(__doc__ or "", timed_learn, summarize, "Feedforward and feedback learned")


def timed_learn(config: dict[str, Any]) -> tuple[Training, float]:
    """The training of :func:`arm_rmhl_test.combined.learn`, and the seconds it took."""
    started = time.perf_counter()
    training = learn(config)
    return training, time.perf_counter() - started


if __name__ == "__main__":
    main()
