# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Feedforward torques learned by feedback-error learning, with a recursive least squares readout.

A supervised baseline for the reward-modulated feedback of
:mod:`arm_rmhl_test.feedback`, on the same arm, reach, and weak joint PD. An identity
NVAR passes the reference ``r = [q_ref, dq_ref, ddq_ref]``, at the start of each
control period, to rclib's recursive least squares (RLS) readout. Its output is a
feedforward torque, added to the PD's and held over the period like it.

In a reach that learns, every control period the readout fits, as its target, its
own output plus the PD's torque. This is feedback-error learning (Kawato et al.,
1987): the feedback controller's torque is the error of the feedforward one. As the
feedforward comes to give the torque the reach needs, the PD's share shrinks. The
readout learns within the reach, from a target every period, where the
reward-modulated readout learns between reaches, from one reward each.

The readout is linear with a bias, so its weights map the reference to the torque,
``u = A q_ref + B dq_ref + C ddq_ref + c`` (see :func:`split_weights`). They start
at zero: rclib's RLS readout creates them, at zero, at its first fit, and until then
the feedforward is zero. A reach that does not learn applies the weights as they
stand, read from the readout (see :func:`readout_weights`).

A configuration sets the readout and the training in two tables:

- ``[readout]``: RLS's ``forgetting`` factor, in (0, 1], and its ``delta``, the
  initial regularization: the covariance starts at the identity over ``delta``, so a
  larger ``delta`` holds the weights nearer zero at first.
- ``[training]``: as in :mod:`arm_rmhl_test.feedback`. The ``dead_zone`` only
  changes the scores, since the learning does not use them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
from rclib import ESN, readouts, reservoirs
from skelarm import Skeleton

from arm_rmhl_test.arm import Array, Reach, ReachRun, command_gains, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.feedback import Training, summarize_course, training_settings

SIGNALS = 3  # the reference's angle, velocity, and acceleration, per joint


def make_model(table: Mapping[str, Any]) -> ESN:
    """The reference, through an identity NVAR, to an RLS readout with a bias, by the ``[readout]`` table."""
    model = ESN()
    model.add_reservoir(reservoirs.Nvar(num_lags=1, polynomial_order=1))  # passes the reference through
    model.set_readout(readouts.Rls(float(table["forgetting"]), float(table["delta"]), include_bias=True))
    return model


def reference_inputs(reach: Reach) -> Array:
    """The readout's input at each control period's start, ``[q_ref, dq_ref, ddq_ref]``; shape ``(steps, 3 joints)``."""
    return np.hstack((reach.q_ref, reach.dq_ref, reach.ddq_ref))[: reach.steps]


def readout_weights(model: ESN, joints: int) -> Array:
    """The readout's weights: shape ``(3 joints + 1, joints)``, the bias in the last row; zero before its first fit.

    rclib's RLS readout does not give its weights, so they are read from its linear
    predictions: the bias is the output for a zero input, and each other row the
    output for that input alone at 1, less the bias.
    """
    inputs = SIGNALS * joints
    readout = model.get_readout()
    if readout.getInputDim() == 0:  # not fitted yet
        return np.zeros((inputs + 1, joints))
    outputs = np.asarray(readout.predict(np.vstack((np.eye(inputs), np.zeros(inputs)))))
    return np.vstack((outputs[:-1] - outputs[-1], outputs[-1]))


def split_weights(weights: Array) -> tuple[Array, Array, Array, Array]:
    """The weights as the torque per reference angle, velocity, and acceleration, and the constant torque.

    The weights have shape ``(3 joints + 1, joints)``, the bias in the last row. Row
    ``i`` of each matrix gives joint ``i``'s torque per reference angle (N m/rad),
    velocity (N m s/rad), or acceleration (N m s^2/rad) of each joint.
    """
    joints = weights.shape[1]
    angle, velocity, acceleration = (weights[k * joints : (k + 1) * joints].T for k in range(SIGNALS))
    return angle, velocity, acceleration, weights[SIGNALS * joints]


def run_frozen(
    weights: Array, arm: Skeleton, reach: Reach, kp: Array, kd: Array, dead_zone: float
) -> tuple[float, ReachRun]:
    """One reach under the PD and the feedforward of fixed weights; return its tracking error and the run."""
    torques = iter(reference_inputs(reach) @ weights[:-1] + weights[-1])
    run = run_reach(arm, reach, kp, kd, lambda _error: next(torques))
    return tracking_error(run, reach, dead_zone), run


def run_trial(
    model: ESN, arm: Skeleton, reach: Reach, kp: Array, kd: Array, dead_zone: float, *, learn: bool = True
) -> tuple[float, ReachRun]:
    """One reach under the PD and the readout's feedforward; return its tracking error and the run.

    In a reach that learns, every control period the readout gives the feedforward
    from the reference, then fits, as its target, that feedforward plus the PD's
    torque, so the next period's feedforward comes from the updated weights. A reach
    that does not learn applies the readout's weights as they stand (see
    :func:`run_frozen`) and changes no learning state.

    Raises
    ------
    ValueError, RuntimeError, OverflowError
        When the arm diverges: rclib raises on a non-finite fit, and skelarm's
        kinematics raise ``OverflowError`` on a torque too large for them.
    """
    joints = arm.num_joints
    if not learn:
        return run_frozen(readout_weights(model, joints), arm, reach, kp, kd, dead_zone)
    model.reset_reservoirs()
    inputs = iter(reference_inputs(reach))

    def feedforward(error: Array) -> Array:
        x = next(inputs).reshape(1, -1)
        fitted = model.get_readout().getInputDim() > 0
        torque = np.asarray(model.predict_online(x))[0] if fitted else np.zeros(joints)
        target = torque + kp * error[:joints] + kd * error[joints:]
        # Before the first fit, the fit itself passes the input to the NVAR.
        model.partial_fit(None if fitted else x, target.reshape(1, -1))
        return torque

    run = run_reach(arm, reach, kp, kd, feedforward)
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
    """Learn from ``trials`` reaches, with reaches that learn nothing between to evaluate the weights.

    A reach with the weights as they stand is evaluated before the first trial,
    after every ``evaluate_every`` trials, and after the last. When the arm
    diverges, which rclib or skelarm reports by raising (see :func:`run_trial`), the
    run stops there and records why. The training's scale is 1: the readout's output
    is the torque.
    """
    joints = arm.num_joints
    evaluated_at = np.unique(np.append(np.arange(0, trials, evaluate_every), trials))
    evaluation_row = {int(trial): row for row, trial in enumerate(evaluated_at)}
    errors = np.full(trials, np.nan)
    evaluations = np.full(len(evaluated_at), np.nan)
    weights = np.full((len(evaluated_at), SIGNALS * joints + 1, joints), np.nan)
    diverged = None
    # A diverging arm overflows on its way to non-finite states, which rclib or skelarm then rejects.
    with np.errstate(over="ignore", invalid="ignore"):
        try:
            for trial in range(trials + 1):
                if trial in evaluation_row:  # after `trial` trials learned from
                    row = evaluation_row[trial]
                    weights[row] = readout_weights(model, joints)
                    evaluations[row] = np.inf  # until the reach completes
                    evaluations[row], _ = run_frozen(weights[row], arm, reach, kp, kd, dead_zone)
                if trial < trials:
                    errors[trial] = np.inf  # until the reach completes
                    errors[trial], _ = run_trial(model, arm, reach, kp, kd, dead_zone)
        except (ValueError, RuntimeError, OverflowError) as error:
            diverged = f"{type(error).__name__}: {error}"
    return Training(errors, evaluated_at, evaluations, weights, np.ones(joints), diverged)


def learn(config: Mapping[str, Any]) -> Training:
    """Train a fresh model on the configuration's arm, reach, PD, readout and training."""
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    return train(make_model(config["readout"]), arm, reach, kp, kd, **training_settings(config))


def summarize(training: Training) -> dict[str, Any]:
    """How a training went, as one row of a table.

    The row holds the course of :func:`arm_rmhl_test.feedback.summarize_course`,
    then the final weights of the feedforward torque (see :func:`split_weights`):
    ``angle_<i><k>``, ``velocity_<i><k>``, and ``acceleration_<i><k>``, the torque on
    joint ``i`` per reference angle, velocity, or acceleration of joint ``k``, and
    ``constant_<i>`` (N m). After a divergence, the weights are ``nan``.
    """
    row = summarize_course(training)
    *matrices, constant = split_weights(training.weights[-1])
    joints = len(constant)
    for name, matrix in zip(("angle", "velocity", "acceleration"), matrices, strict=True):
        row |= {f"{name}_{i + 1}{k + 1}": float(matrix[i, k]) for i in range(joints) for k in range(joints)}
    return row | {f"constant_{i + 1}": float(constant[i]) for i in range(joints)}
