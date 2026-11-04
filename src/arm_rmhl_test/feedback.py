# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Feedback torques learned from one reward per reach, by reward-modulated Hebbian learning.

The arm plays the role of the reservoir. An identity NVAR passes the tracking error
``e = [q_ref - q, dq_ref - dq]`` straight to rclib's reward-modulated readout, whose
output, with exploration noise while learning, is the feedback torque added to the
joint PD's. At the end of each reach the readout receives one reward, minus the
reach's tracking error, and updates its weights by the trial rule.

The readout is linear with a bias, so its weights are a stiffness matrix ``K_p``, a
damping matrix ``K_d``, and a constant ``c``. The feedback torque is the readout's
output ``y = K_p (q_ref - q) + K_d (dq_ref - dq) + c`` times a factor per joint, its
scale: 1, so that the output is the torque (N m), or the joint's inertia, so that
the output is in rad/s^2 like the PD's ``omega^2 e + 2 zeta omega de``. The
exploration noise is added to the output, in its units.

A configuration sets the feedback, the rule and the training in three tables:

- ``[feedback]``: the ``scale``, ``"none"`` or ``"inertia"`` (see
  :func:`feedback_scale`); without the table, ``"none"``.

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
from skelarm.dynamics import compute_mass_matrix

from arm_rmhl_test.arm import Array, Reach, ReachRun, command_gains, make_arm, make_reach, run_reach, tracking_error

_OPTIONAL = {field.name for field in dataclasses.fields(learning.RewardModulatedHebbian) if field.default is None}


@dataclass(frozen=True)
class Training:
    """The course of one training run.

    Attributes
    ----------
    errors : Array
        The tracking error of each reach learned from, an exploring reach whose
        negative was its reward in reward-modulated learning; ``inf`` for the reach
        that diverged and ``nan`` for those never run.
    evaluated_at : Array
        The number of trials learned from before each evaluation, from 0 (before
        learning) to ``trials``.
    evaluations : Array
        The tracking error of each evaluation, a reach without noise that learns
        nothing; ``nan`` for those never run.
    weights : Array
        The readout's weights at each evaluation; shape ``(evaluations, features + 1, joints)``,
        the bias in the last row; ``nan`` for those never reached.
    scale : Array
        Each joint's factor from the readout's output to its feedback torque.
    diverged : str | None
        Why the run stopped early, the error raised when the arm diverged, or
        ``None`` if it completed every trial.
    """

    errors: Array
    evaluated_at: Array
    evaluations: Array
    weights: Array
    scale: Array
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


def feedback_gains(model: ESN) -> tuple[Array, Array, Array]:
    """The model's stiffness matrix, damping matrix, and constant torque (see :func:`split_weights`)."""
    return split_weights(np.asarray(model.get_readout().getWeights()))


def split_weights(weights: Array) -> tuple[Array, Array, Array]:
    """The readout's weights as the stiffness matrix, the damping matrix, and the constant torque.

    The weights have shape ``(2 joints + 1, joints)``, the bias in the last row. Row
    ``i`` of each matrix gives joint ``i``'s torque per error of each joint.
    """
    joints = weights.shape[1]
    return weights[:joints].T, weights[joints : 2 * joints].T, weights[2 * joints]


def feedback_scale(config: Mapping[str, Any], arm: Skeleton) -> Array:
    """Each joint's factor from the readout's output to its feedback torque, by the ``[feedback]`` table's ``scale``.

    With ``"none"``, the default, the factor is 1: the output is the torque (N m).
    With ``"inertia"``, it is the joint's diagonal entry of the mass matrix at the
    arm's posture, normally the start of the reach, as in the PD's gains: the output
    is in rad/s^2, and the weights read as ``omega^2`` and ``2 zeta omega``.

    Raises
    ------
    ValueError
        If the scale is neither.
    """
    scale = config.get("feedback", {}).get("scale", "none")
    if scale == "none":
        return np.ones(arm.num_joints)
    if scale == "inertia":
        return np.diag(compute_mass_matrix(arm)).copy()
    msg = f"unknown feedback scale {scale!r}: use 'none' or 'inertia'"
    raise ValueError(msg)


def run_trial(
    model: ESN,
    arm: Skeleton,
    reach: Reach,
    kp: Array,
    kd: Array,
    dead_zone: float,
    *,
    scale: Array | None = None,
    explore: bool = True,
) -> tuple[float, ReachRun]:
    """One reach under the PD and the model's feedback; return its tracking error and the run.

    The feedback torque is the model's output times ``scale``, 1 by default. An
    exploring reach adds the noise and records the eligibility for the next
    ``reinforce``; a noise-free reach changes no learning state.

    Raises
    ------
    ValueError, RuntimeError, OverflowError
        When the arm diverges: rclib's ``act`` raises ``ValueError`` on a non-finite
        tracking error and ``RuntimeError`` when the feedback would overflow, and
        skelarm's kinematics raise ``OverflowError`` on a torque too large for them.
    """
    model.reset_reservoirs()
    factor = np.ones(arm.num_joints) if scale is None else scale

    def feedback(error: Array) -> Array:
        return factor * model.act(error.reshape(1, -1), explore=explore)[0]

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
    scale: Array | None = None,
) -> Training:
    """Learn from ``trials`` exploring reaches, one reward each, with noise-free evaluations between.

    The feedback torque is the model's output times ``scale``, 1 by default. A
    noise-free reach is evaluated before the first trial, after every
    ``evaluate_every`` trials, and after the last. When the arm diverges, which
    rclib or skelarm reports by raising (see :func:`run_trial`), the run stops
    there, as in rclib's body-control example, and records why.
    """
    joints = arm.num_joints
    scale = np.ones(joints) if scale is None else np.asarray(scale, dtype=np.float64)
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
                    evaluations[row], _ = run_trial(model, arm, reach, kp, kd, dead_zone, scale=scale, explore=False)
                if trial < trials:
                    errors[trial] = np.inf  # until the reach completes
                    errors[trial], _ = run_trial(model, arm, reach, kp, kd, dead_zone, scale=scale)
                    model.reinforce(-errors[trial])
        except (ValueError, RuntimeError, OverflowError) as error:
            diverged = f"{type(error).__name__}: {error}"
            model.clear_eligibility()
    return Training(errors, evaluated_at, evaluations, weights, scale, diverged)


def training_settings(config: Mapping[str, Any]) -> dict[str, Any]:
    """The keyword arguments of :func:`train` from the ``[training]`` table."""
    table = config["training"]
    return {
        "trials": int(table["trials"]),
        "dead_zone": float(table["dead_zone"]),
        "evaluate_every": int(table["evaluate_every"]),
    }


def learn(config: Mapping[str, Any]) -> Training:
    """Train a fresh model on the configuration's arm, reach, PD, feedback scale, rule and training."""
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    model = make_model(make_rule(config["rule"]), arm.num_joints)
    return train(model, arm, reach, kp, kd, scale=feedback_scale(config, arm), **training_settings(config))


def summarize(training: Training) -> dict[str, Any]:
    """How a training went, as one row of a table.

    The row holds the course of :func:`summarize_course`, then the final gains of
    the feedback torque, the weights times the scale: ``stiffness_<i><k>`` (N m/rad)
    and ``damping_<i><k>`` (N m s/rad), the torque on joint ``i`` per error of joint
    ``k``, and ``constant_<i>`` (N m). After a divergence, the gains are ``nan``.
    """
    row = summarize_course(training)
    stiffness, damping, constant = split_weights(training.scale * training.weights[-1])
    joints = len(constant)
    for name, gains in (("stiffness", stiffness), ("damping", damping)):
        row |= {f"{name}_{i + 1}{k + 1}": float(gains[i, k]) for i in range(joints) for k in range(joints)}
    row |= {f"constant_{i + 1}": float(constant[i]) for i in range(joints)}
    return row


def summarize_course(training: Training) -> dict[str, Any]:
    """How a training's evaluations went, as the first columns of a row.

    The row holds the evaluations' tracking errors (m) of the PD alone, before
    learning (``pd_error_m``), at the end (``final_error_m``), and the lowest of all
    (``best_error_m``) with the trials learned from before it (``best_after``); the
    ``outcome``: ``"diverged"`` if the arm diverged, ``"improved"`` if the final
    error is below the PD's, and ``"worse"`` if not; and why the arm diverged
    (``diverged``, empty if it did not). After a divergence, the final error is
    ``nan``.
    """
    evaluations = training.evaluations
    completed = np.where(np.isfinite(evaluations), evaluations, np.nan)
    pd_error, final_error = float(evaluations[0]), float(evaluations[-1])
    if training.diverged is not None:
        outcome = "diverged"
    elif final_error < pd_error:
        outcome = "improved"
    else:
        outcome = "worse"
    row: dict[str, Any] = {"pd_error_m": pd_error, "final_error_m": final_error}
    if np.isnan(completed).all():
        row |= {"best_error_m": np.nan, "best_after": -1}
    else:
        best = int(np.nanargmin(completed))
        row |= {"best_error_m": float(completed[best]), "best_after": int(training.evaluated_at[best])}
    return row | {"outcome": outcome, "diverged": training.diverged or ""}
