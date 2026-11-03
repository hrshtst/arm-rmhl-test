# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Feedback torques learned from one reward per reach, by reward-modulated Hebbian learning.

The arm plays the role of the reservoir. An identity NVAR passes the tracking error
``e = [q_ref - q, dq_ref - dq]`` straight to rclib's reward-modulated readout, whose
output, with exploration noise while learning, is the feedback torque added to the
joint PD's. At the end of each reach the readout receives one reward, minus the
reach's tracking error, and updates its weights by the trial rule.

The readout is linear with a bias, so its weights are a stiffness matrix ``K_p``, a
damping matrix ``K_d``, and a constant torque ``c``:
``tau_fb = K_p (q_ref - q) + K_d (dq_ref - dq) + c``.

A configuration sets the rule and the training in two tables:

- ``[rule]``: the ``preset`` of ``rclib.learning`` (such as ``"burms2015"``), its
  ``learning_rate``, a ``[rule.exploration]`` table and an optional
  ``[rule.baseline]`` table (the fields of ``rclib.learning.Exploration`` and
  ``Baseline``), and any other setting of ``RewardModulatedHebbian`` to override. An
  optional setting set to ``false`` is turned off: ``decorrelation = false`` gives the
  plain rule where ``burms2015`` is decorrelated.
- ``[training]``: the number of ``trials``, the reward's ``dead_zone`` (m), and how
  often a noise-free reach is evaluated, ``evaluate_every`` trials.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from rclib import ESN, learning, readouts, reservoirs
from skelarm import Skeleton

from arm_rmhl_test.arm import Array, Reach, ReachRun, run_reach, tracking_error

_OPTIONAL = {field.name for field in dataclasses.fields(learning.RewardModulatedHebbian) if field.default is None}


@dataclass(frozen=True)
class Training:
    """The course of one training run.

    Attributes
    ----------
    errors : Array
        The tracking error of each exploring reach, whose negative was its reward;
        ``inf`` for the reach that diverged and ``nan`` for those never run.
    evaluated_at : Array
        The number of trials learned from before each noise-free evaluation, from 0
        (before learning) to ``trials``.
    evaluations : Array
        The tracking error of each noise-free reach; ``nan`` for those never run.
    weights : Array
        The readout's weights at each evaluation; shape ``(evaluations, features + 1, joints)``,
        the bias in the last row; ``nan`` for those never reached.
    diverged : str | None
        Why the run stopped early, the error raised when the arm diverged, or
        ``None`` if it completed every trial.
    """

    errors: Array
    evaluated_at: Array
    evaluations: Array
    weights: Array
    diverged: str | None


def make_rule(table: Mapping[str, Any]) -> learning.RewardModulatedHebbian:
    """The rule of the ``[rule]`` table: a preset of ``rclib.learning`` with its settings replaced."""
    name = table["preset"]
    if name not in ("legenstein2010", "hoerzer2014", "miconi2017", "burms2015"):
        msg = f"unknown preset {name!r}"
        raise ValueError(msg)
    overrides: dict[str, Any] = {
        key: None if value is False and key in _OPTIONAL else value
        for key, value in table.items()
        if key not in ("preset", "learning_rate", "exploration", "baseline")
    }
    if "exploration" in table:
        overrides["exploration"] = learning.Exploration(**table["exploration"])
    if "baseline" in table:
        overrides["baseline"] = learning.Baseline(**table["baseline"])
    return getattr(learning, name)(float(table["learning_rate"]), **overrides)


def make_model(rule: learning.RewardModulatedHebbian, joints: int) -> ESN:
    """The tracking error, through an identity NVAR, to a reward-modulated readout with a bias.

    The readout's weights start at zero, so its feedback starts at zero torque.
    """
    model = ESN()
    model.add_reservoir(reservoirs.Nvar(num_lags=1, polynomial_order=1))  # passes the error through
    model.set_readout(readouts.RewardModulated(joints, rule, include_bias=True))
    model.get_readout().setWeights(np.zeros((2 * joints + 1, joints)))
    return model


def feedback_gains(model: ESN, joints: int) -> tuple[Array, Array, Array]:
    """The readout's weights as the stiffness matrix, the damping matrix, and the constant torque."""
    weights = np.asarray(model.get_readout().getWeights())
    return weights[:joints].T, weights[joints : 2 * joints].T, weights[2 * joints]


def run_trial(
    model: ESN, arm: Skeleton, reach: Reach, kp: Array, kd: Array, dead_zone: float, *, explore: bool = True
) -> tuple[float, ReachRun]:
    """One reach under the PD and the model's feedback; return its tracking error and the run.

    An exploring reach adds the noise and records the eligibility for the next
    ``reinforce``; a noise-free reach changes no learning state.

    Raises
    ------
    ValueError, RuntimeError, OverflowError
        When the arm diverges: rclib's ``act`` raises ``ValueError`` on a non-finite
        tracking error and ``RuntimeError`` when the feedback would overflow, and
        skelarm's kinematics raise ``OverflowError`` on a torque too large for them.
    """
    model.reset_reservoirs()

    def feedback(error: Array) -> Array:
        return model.act(error.reshape(1, -1), explore=explore)[0]

    run = run_reach(arm, reach, kp, kd, feedback)
    return tracking_error(run, reach, dead_zone), run


def train(
    model: ESN,
    arm: Skeleton,
    reach: Reach,
    kp: Array,
    kd: Array,
    *,
    trials: int,
    dead_zone: float,
    evaluate_every: int,
) -> Training:
    """Learn from ``trials`` exploring reaches, one reward each, with noise-free evaluations between.

    A noise-free reach is evaluated before the first trial, after every
    ``evaluate_every`` trials, and after the last. When the arm diverges, which
    rclib or skelarm reports by raising (see :func:`run_trial`), the run stops
    there, as in rclib's body-control example, and records why.
    """
    joints = arm.num_joints
    evaluated_at = np.unique(np.append(np.arange(0, trials, evaluate_every), trials))
    evaluation_row = {int(trial): row for row, trial in enumerate(evaluated_at)}
    errors = np.full(trials, np.nan)
    evaluations = np.full(len(evaluated_at), np.nan)
    weights = np.full((len(evaluated_at), 2 * joints + 1, joints), np.nan)
    diverged = None
    # A diverging arm overflows on its way to non-finite states, which rclib or skelarm then rejects.
    with np.errstate(over="ignore", invalid="ignore"):
        try:
            for trial in range(trials + 1):
                if trial in evaluation_row:  # after `trial` trials learned from
                    row = evaluation_row[trial]
                    weights[row] = model.get_readout().getWeights()
                    evaluations[row] = np.inf  # until the reach completes
                    evaluations[row], _ = run_trial(model, arm, reach, kp, kd, dead_zone, explore=False)
                if trial < trials:
                    errors[trial] = np.inf  # until the reach completes
                    errors[trial], _ = run_trial(model, arm, reach, kp, kd, dead_zone)
                    model.reinforce(-errors[trial])
        except (ValueError, RuntimeError, OverflowError) as error:
            diverged = f"{type(error).__name__}: {error}"
            model.clear_eligibility()
    return Training(errors, evaluated_at, evaluations, weights, diverged)


def training_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    """The keyword arguments of :func:`train` from the ``[training]`` table."""
    table = config["training"]
    return {
        "trials": int(table["trials"]),
        "dead_zone": float(table["dead_zone"]),
        "evaluate_every": int(table["evaluate_every"]),
    }
