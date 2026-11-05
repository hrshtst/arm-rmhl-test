# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Feedforward and feedback torques learned together, by feedback-error learning and reward-modulated learning.

Every control period, the torque is the weak joint PD's, plus a feedforward torque
from the reference, learned by feedback-error learning with an RLS readout (see
:mod:`arm_rmhl_test.feedforward`), plus a feedback torque from the tracking error,
learned by reward-modulated Hebbian learning (see :mod:`arm_rmhl_test.feedback`).
Each learner works as it does alone:

- in a reach that the RLS readout learns from, it fits, every control period, its
  own output plus the weak PD's torque. The feedback torque, exploration noise
  included, is part of the plant for it, as the arm is;
- in a reach that the reward-modulated readout learns from, it explores, and at the
  end of the reach it receives one reward, minus the reach's tracking error.

A schedule says which reaches each learns from (see :class:`Schedule`): both every
reach (concurrent), or the RLS readout the first reaches and the reward-modulated
readout those after (staged). A learner that does not learn from a reach still adds
its torque, with its weights as they stand and without noise.

A learner left out adds no torque. Alone, each trains exactly as
:func:`arm_rmhl_test.feedforward.train` or :func:`arm_rmhl_test.feedback.train`
does, so an ablation is the combined system's configuration without one learner's
table. An evaluation is a reach that learns nothing, without noise, with both
readouts' weights as they stand.

A configuration sets the learners, the schedule and the training in these tables:

- ``[readout]``: the RLS readout, as in :mod:`arm_rmhl_test.feedforward`; without
  it, no feedforward;
- ``[feedback]`` and ``[rule]``: the reward-modulated feedback, as in
  :mod:`arm_rmhl_test.feedback`; without ``[rule]``, no feedback;
- ``[schedule]``: its ``kind``, ``"concurrent"`` or ``"staged"``, and for
  ``"staged"`` the ``handover``, the number of reaches the RLS readout learns from
  first; without the table, ``"concurrent"``;
- ``[training]``: as in :mod:`arm_rmhl_test.feedback`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from rclib import ESN
from skelarm import Skeleton

from arm_rmhl_test import feedback, feedforward
from arm_rmhl_test.arm import (
    Array,
    Feedback,
    Reach,
    ReachRun,
    command_gains,
    make_arm,
    make_reach,
    run_reach,
    tracking_error,
)
from arm_rmhl_test.feedback import Training, evaluation_trials, summarize_course, training_settings

SCHEDULES = ("concurrent", "staged")


@dataclass(frozen=True)
class CombinedTraining(Training):
    """The course of one training of both learners.

    The fields of :class:`arm_rmhl_test.feedback.Training` hold the feedback's
    ``weights`` and ``scale``; the feedforward's weights are added.

    Attributes
    ----------
    feedforward_weights : Array
        The RLS readout's weights at each evaluation; shape
        ``(evaluations, 3 joints + 1, joints)``, the bias in the last row; ``nan``
        for those never reached. Zero without a feedforward, as ``weights`` are
        without a feedback.
    """

    feedforward_weights: Array


@dataclass(frozen=True)
class Learners:
    """The two learners' models, each ``None`` when left out."""

    feedforward: ESN | None
    feedback: ESN | None


@dataclass(frozen=True)
class Schedule:
    """Which reaches each learner learns from.

    ``"concurrent"``: both learn from every reach. ``"staged"``: the RLS readout
    learns from the first ``handover`` reaches, then holds its weights; the
    reward-modulated readout learns from the reaches after.
    """

    kind: str = "concurrent"
    handover: int = 0

    def __post_init__(self) -> None:
        """Check the schedule.

        Raises
        ------
        ValueError
            If the kind is neither, or a staged schedule hands over before its first reach.
        """
        if self.kind not in SCHEDULES:
            msg = f"unknown schedule {self.kind!r}: use 'concurrent' or 'staged'"
            raise ValueError(msg)
        if self.kind == "staged" and self.handover < 1:
            msg = f"a staged schedule needs a handover of at least 1 reach, not {self.handover}"
            raise ValueError(msg)

    def feedforward_learns(self, trial: int) -> bool:
        """Whether the RLS readout learns from the reach of this trial, counted from 0."""
        return self.kind == "concurrent" or trial < self.handover

    def feedback_learns(self, trial: int) -> bool:
        """Whether the reward-modulated readout learns from the reach of this trial, counted from 0."""
        return self.kind == "concurrent" or trial >= self.handover


def make_learners(config: Mapping[str, Any], joints: int) -> Learners:
    """The learners of the ``[readout]`` and ``[rule]`` tables, from zero weights.

    Raises
    ------
    ValueError
        If the configuration has neither table.
    """
    if "readout" not in config and "rule" not in config:
        msg = "nothing to learn: the configuration has neither a [readout] nor a [rule] table"
        raise ValueError(msg)
    return Learners(
        feedforward.make_model(config["readout"]) if "readout" in config else None,
        feedback.make_model(feedback.make_rule(config["rule"]), joints) if "rule" in config else None,
    )


def make_schedule(config: Mapping[str, Any]) -> Schedule:
    """The schedule of the ``[schedule]`` table; concurrent without it."""
    table = config.get("schedule", {})
    return Schedule(str(table.get("kind", "concurrent")), int(table.get("handover", 0)))


def combine(feedforward_torque: Feedback | None, feedback_torque: Feedback | None) -> Feedback | None:
    """The sum of the torques present, the feedforward computed first; just the one if only one is."""
    if feedforward_torque is None or feedback_torque is None:
        return feedforward_torque or feedback_torque
    return lambda error: feedforward_torque(error) + feedback_torque(error)


def run_trial(
    learners: Learners,
    arm: Skeleton,
    reach: Reach,
    kp: Array,
    kd: Array,
    dead_zone: float,
    *,
    scale: Array,
    learn_feedforward: bool,
    learn_feedback: bool,
) -> tuple[float, ReachRun]:
    """One reach under the PD and both learners' torques; return its tracking error and the run.

    The RLS readout learns within the reach if ``learn_feedforward`` is set (see
    :func:`arm_rmhl_test.feedforward.learning_feedforward`), and otherwise applies its
    weights as they stand. The reward-modulated readout explores if
    ``learn_feedback`` is set, recording the eligibility for the next ``reinforce``,
    and otherwise gives its output without noise; its torque is the output times
    ``scale``.

    Raises
    ------
    ValueError, RuntimeError, OverflowError
        When the arm diverges (see :func:`arm_rmhl_test.feedback.run_trial` and
        :func:`arm_rmhl_test.feedforward.run_trial`).
    """
    feedforward_torque = None
    if learners.feedforward is not None:
        if learn_feedforward:
            feedforward_torque = feedforward.learning_feedforward(learners.feedforward, reach, kp, kd)
        else:
            weights = feedforward.readout_weights(learners.feedforward, arm.num_joints)
            feedforward_torque = feedforward.frozen_feedforward(weights, reach)
    feedback_torque = None
    if learners.feedback is not None:
        feedback_torque = feedback.feedback_torque(learners.feedback, scale, explore=learn_feedback)
    run = run_reach(arm, reach, kp, kd, combine(feedforward_torque, feedback_torque))
    return tracking_error(run, reach, dead_zone), run


def train(
    learners: Learners,
    arm: Skeleton,
    reach: Reach,
    kp: Array,
    kd: Array,
    *,
    schedule: Schedule,
    scale: Array,
    trials: int,
    dead_zone: float,
    evaluate_every: int,
    evaluate_all_until: int = 0,
) -> CombinedTraining:
    """Learn from ``trials`` reaches by the schedule, with evaluations between.

    After each reach the reward-modulated readout learned from, it is reinforced with
    minus the reach's tracking error. An evaluation comes at the trials of
    :func:`arm_rmhl_test.feedback.evaluation_trials`. When the arm diverges, which
    rclib or skelarm reports by raising, the run stops there and records why.
    """
    joints = arm.num_joints
    evaluated_at = evaluation_trials(trials, evaluate_every, evaluate_all_until)
    evaluation_row = {int(trial): row for row, trial in enumerate(evaluated_at)}
    errors = np.full(trials, np.nan)
    evaluations = np.full(len(evaluated_at), np.nan)
    feedback_weights = np.full((len(evaluated_at), 2 * joints + 1, joints), np.nan)
    feedforward_weights = np.full((len(evaluated_at), feedforward.SIGNALS * joints + 1, joints), np.nan)
    diverged = None
    # A diverging arm overflows on its way to non-finite states, which rclib or skelarm then rejects.
    with np.errstate(over="ignore", invalid="ignore"):
        try:
            for trial in range(trials + 1):
                if trial in evaluation_row:  # after `trial` trials learned from
                    row = evaluation_row[trial]
                    feedforward_weights[row] = _feedforward_weights(learners, joints)
                    feedback_weights[row] = _feedback_weights(learners, joints)
                    evaluations[row] = np.inf  # until the reach completes
                    evaluations[row], _ = run_trial(
                        learners,
                        arm,
                        reach,
                        kp,
                        kd,
                        dead_zone,
                        scale=scale,
                        learn_feedforward=False,
                        learn_feedback=False,
                    )
                if trial < trials:
                    learn_feedback = learners.feedback is not None and schedule.feedback_learns(trial)
                    errors[trial] = np.inf  # until the reach completes
                    errors[trial], _ = run_trial(
                        learners,
                        arm,
                        reach,
                        kp,
                        kd,
                        dead_zone,
                        scale=scale,
                        learn_feedforward=schedule.feedforward_learns(trial),
                        learn_feedback=learn_feedback,
                    )
                    if learners.feedback is not None and learn_feedback:
                        learners.feedback.reinforce(-errors[trial])
        except (ValueError, RuntimeError, OverflowError) as error:
            diverged = f"{type(error).__name__}: {error}"
            if learners.feedback is not None:
                learners.feedback.clear_eligibility()
    return CombinedTraining(errors, evaluated_at, evaluations, feedback_weights, scale, diverged, feedforward_weights)


def _feedforward_weights(learners: Learners, joints: int) -> Array:
    """The RLS readout's weights as they stand; zero without a feedforward."""
    if learners.feedforward is None:
        return np.zeros((feedforward.SIGNALS * joints + 1, joints))
    return feedforward.readout_weights(learners.feedforward, joints)


def _feedback_weights(learners: Learners, joints: int) -> Array:
    """The reward-modulated readout's weights as they stand; zero without a feedback."""
    if learners.feedback is None:
        return np.zeros((2 * joints + 1, joints))
    return np.asarray(learners.feedback.get_readout().getWeights())


def learn(config: Mapping[str, Any]) -> CombinedTraining:
    """Train fresh learners on the configuration's arm, reach, PD, learners, schedule and training."""
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    return train(
        make_learners(config, arm.num_joints),
        arm,
        reach,
        kp,
        kd,
        schedule=make_schedule(config),
        scale=feedback.feedback_scale(config, arm),
        **training_settings(config),
    )


def summarize(training: Training) -> dict[str, Any]:
    """How a training of both learners went, as one row of a table.

    The row holds the course of :func:`arm_rmhl_test.feedback.summarize_course`; the
    feedback's final gains, the weights times the scale: ``stiffness_<i><k>``
    (N m/rad), ``damping_<i><k>`` (N m s/rad), and ``feedback_constant_<i>`` (N m);
    and the feedforward's final weights: ``angle_<i><k>``, ``velocity_<i><k>``, and
    ``acceleration_<i><k>``, the torque on joint ``i`` per reference angle, velocity,
    or acceleration of joint ``k``, and ``feedforward_constant_<i>`` (N m). After a
    divergence, the gains and weights are ``nan``.

    Raises
    ------
    TypeError
        If the training is not a :class:`CombinedTraining`.
    """
    if not isinstance(training, CombinedTraining):
        msg = f"a training of both learners is a CombinedTraining, not a {type(training).__name__}"
        raise TypeError(msg)
    row = summarize_course(training)
    stiffness, damping, feedback_constant = feedback.split_weights(training.scale * training.weights[-1])
    *matrices, feedforward_constant = feedforward.split_weights(training.feedforward_weights[-1])
    joints = len(feedback_constant)
    named = zip(
        ("stiffness", "damping", "angle", "velocity", "acceleration"), (stiffness, damping, *matrices), strict=True
    )
    for name, matrix in named:
        row |= {f"{name}_{i + 1}{k + 1}": float(matrix[i, k]) for i in range(joints) for k in range(joints)}
    row |= {f"feedback_constant_{i + 1}": float(feedback_constant[i]) for i in range(joints)}
    return row | {f"feedforward_constant_{i + 1}": float(feedforward_constant[i]) for i in range(joints)}
