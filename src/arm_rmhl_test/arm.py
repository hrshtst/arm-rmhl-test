# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""The arm, the reach, and the joint PD that drives it.

A reach starts from rest at the arm's initial posture. Its reference moves in joint
space, by a minimum-jerk schedule, to the posture that puts the hand at the target,
then holds that posture. Every control period, the torque is computed once and held
while skelarm integrates the arm with its smaller step.

A configuration describes the arm in skelarm's own tables, so skelarm's tools read
the same file:

- ``[skeleton]`` and ``[initial]``: the links and the start posture (degrees);
- ``[simulator]``: the integration step ``dt`` and the joint stops;
- ``[reach]``: the hand's ``target`` (m), the reference's ``move`` time (s), the
  trial's ``duration`` (s), and the ``control_period`` (s);
- ``[command]``: the joint PD's natural frequency ``omega`` (rad/s) and
  ``damping_ratio``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from skelarm import Skeleton, Trajectory, compute_inverse_kinematics
from skelarm.dynamics import compute_mass_matrix, integrate_with_limits
from skelarm.scenario import Simulator

Array = NDArray[np.float64]
Feedback = Callable[[Array], Array]


@dataclass(frozen=True)
class Reach:
    """One reach from rest: its reference at every control period, and how the arm is simulated.

    Attributes
    ----------
    q_ref, dq_ref, ddq_ref : Array
        The reference joint angles (rad), velocities (rad/s), and accelerations
        (rad/s^2) at the times ``k * period``, ``k = 0, ..., steps``; shape
        ``(steps + 1, joints)``.
    hand_ref : Array
        Where the reference puts the hand at those times (m); shape ``(steps + 1, 2)``.
    period : float
        The control period (s): the torque is computed at its start and held over it.
    simulator : Simulator
        skelarm's integration settings: the step ``dt`` and the joint stops.
    """

    q_ref: Array
    dq_ref: Array
    ddq_ref: Array
    hand_ref: Array
    period: float
    simulator: Simulator

    @property
    def steps(self) -> int:
        """The number of control periods in the trial."""
        return len(self.q_ref) - 1

    @property
    def substeps(self) -> int:
        """The number of integration steps per control period."""
        return round(self.period / self.simulator.dt)


@dataclass(frozen=True)
class ReachRun:
    """What happened in one reach, at every control period.

    Attributes
    ----------
    q, dq : Array
        The joint angles (rad) and velocities (rad/s) at the times ``k * period``;
        shape ``(steps + 1, joints)``.
    hand : Array
        The hand's position at those times (m); shape ``(steps + 1, 2)``.
    tau : Array
        The torque held over each period, the PD's and the feedback's (N m); shape
        ``(steps, joints)``.
    feedback : Array
        The feedback's part of it (N m); shape ``(steps, joints)``.
    """

    q: Array
    dq: Array
    hand: Array
    tau: Array
    feedback: Array


def make_arm(config: Mapping[str, Any]) -> Skeleton:
    """The arm of the ``[skeleton]`` table, at rest at the ``[initial]`` posture."""
    return Skeleton.from_config(config)


def make_reach(config: Mapping[str, Any], arm: Skeleton) -> Reach:
    """The reach of the ``[reach]`` table, from the arm's posture to the target.

    The goal posture is skelarm's inverse kinematics of the target, seeded with the
    start posture. The reference moves from the start to the goal by a minimum-jerk
    schedule over ``move`` seconds, then holds the goal until ``duration``.

    Raises
    ------
    ValueError
        If the target is out of reach, or the duration is not a whole number of
        control periods, or the control period not a whole number of integration
        steps.
    """
    table = config["reach"]
    period = float(table["control_period"])
    duration = float(table["duration"])
    simulator = Simulator.from_dict(config.get("simulator", {}))
    steps = round(duration / period)
    if not np.isclose(steps * period, duration):
        msg = f"the duration {duration} s is not a whole number of control periods of {period} s"
        raise ValueError(msg)
    if not np.isclose(round(period / simulator.dt) * simulator.dt, period):
        msg = f"the control period {period} s is not a whole number of integration steps of {simulator.dt} s"
        raise ValueError(msg)

    start = arm.q.copy()
    target = np.asarray(table["target"], dtype=np.float64)
    solution = compute_inverse_kinematics(arm.clone(), target, q0=start)
    if not solution.success:
        msg = f"the target {target.tolist()} m is out of reach ({solution.status})"
        raise ValueError(msg)
    trajectory = Trajectory(start, solution.q, float(table["move"]), schedule="minimum_jerk")
    samples = [trajectory.sample(k * period) for k in range(steps + 1)]
    q_ref = np.array([sample[0] for sample in samples])
    dq_ref = np.array([sample[1] for sample in samples])
    ddq_ref = np.array([sample[2] for sample in samples])
    return Reach(q_ref, dq_ref, ddq_ref, hand_positions(arm, q_ref), period, simulator)


def hand_positions(arm: Skeleton, postures: Array) -> Array:
    """The hand's position (m) at each posture, a row each."""
    model = arm.clone()
    hands = np.empty((len(postures), 2))
    for i, q in enumerate(postures):
        model.set_state(q=q, dq=np.zeros_like(q))  # also refreshes the forward kinematics
        hands[i] = _hand(model)
    return hands


def pd_gains(arm: Skeleton, omega: float, damping_ratio: float) -> tuple[Array, Array]:
    """Joint PD gains of one natural frequency and damping ratio for every joint.

    Each joint's gains are scaled by its diagonal entry of the mass matrix at the
    arm's current posture, normally the start of the reach:
    ``kp = M_ii omega^2`` and ``kd = 2 M_ii damping_ratio omega``.
    """
    inertia = np.diag(compute_mass_matrix(arm))
    return inertia * omega**2, 2.0 * inertia * damping_ratio * omega


def command_gains(config: Mapping[str, Any], arm: Skeleton) -> tuple[Array, Array]:
    """The gains of the ``[command]`` table's joint PD."""
    table = config["command"]
    return pd_gains(arm, float(table["omega"]), float(table["damping_ratio"]))


def run_reach(arm: Skeleton, reach: Reach, kp: Array, kd: Array, feedback: Feedback | None = None) -> ReachRun:
    """One reach from the arm's current state, under the joint PD and an optional feedback.

    Every control period ``k``, the tracking error ``e = [q_ref - q, dq_ref - dq]``
    gives the PD's torque ``kp * (q_ref - q) + kd * (dq_ref - dq)`` and the
    feedback's torque ``feedback(e)``. Their sum is held while skelarm integrates the
    arm over the period. The arm passed in is not changed.
    """
    model = arm.clone()
    joints = model.num_joints
    lower = upper = None
    if reach.simulator.enforce_limits:
        lower = np.array([link.prop.qmin for link in model.links[1:]])
        upper = np.array([link.prop.qmax for link in model.links[1:]])
    q = np.empty((reach.steps + 1, joints))
    dq = np.empty((reach.steps + 1, joints))
    hand = np.empty((reach.steps + 1, 2))
    tau = np.empty((reach.steps, joints))
    feedback_tau = np.zeros((reach.steps, joints))
    q[0], dq[0], hand[0] = model.q, model.dq, _hand(model)
    for k in range(reach.steps):
        error = np.concatenate((reach.q_ref[k] - q[k], reach.dq_ref[k] - dq[k]))
        if feedback is not None:
            feedback_tau[k] = feedback(error)
        tau[k] = kp * error[:joints] + kd * error[joints:] + feedback_tau[k]
        for _ in range(reach.substeps):
            integrate_with_limits(model, tau[k], reach.simulator.dt, lower, upper, stops=reach.simulator.stops)
        q[k + 1], dq[k + 1], hand[k + 1] = model.q, model.dq, _hand(model)  # the step refreshed the kinematics
    return ReachRun(q, dq, hand, tau, feedback_tau)


def _hand(arm: Skeleton) -> Array:
    """The hand's position (m), from the arm's forward kinematics as last computed."""
    return np.array([arm.links[-1].xe, arm.links[-1].ye])


def tracking_error(run: ReachRun, reach: Reach, dead_zone: float = 0.0) -> float:
    """The hand's mean distance from the reference's hand position beyond a dead zone (m).

    The mean is over the ends of the control periods, ``k = 1, ..., steps``; the
    start, where the arm is put, is left out. A run that went non-finite scores
    ``inf``.
    """
    distance = np.linalg.norm(run.hand[1:] - reach.hand_ref[1:], axis=1)
    error = float(np.mean(np.maximum(distance - dead_zone, 0.0)))
    return error if np.isfinite(error) else np.inf


def effort(run: ReachRun, reach: Reach) -> float:
    """The squared torque summed over the joints and integrated over the trial (N^2 m^2 s)."""
    return float(np.sum(run.tau**2) * reach.period)
