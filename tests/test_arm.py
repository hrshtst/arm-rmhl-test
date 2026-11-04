# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the arm, the reach, and the joint PD."""

from typing import Any

import numpy as np
import pytest
from skelarm.dynamics import compute_mass_matrix

from arm_rmhl_test.arm import (
    command_gains,
    effort,
    hand_positions,
    make_arm,
    make_reach,
    pd_gains,
    run_reach,
    tracking_error,
)


def test_the_arm_starts_at_rest_at_the_initial_posture(config: dict[str, Any]):
    arm = make_arm(config)

    assert arm.num_joints == 2
    np.testing.assert_allclose(arm.q, np.radians([30.0, 30.0]))
    np.testing.assert_array_equal(arm.dq, [0.0, 0.0])


def test_the_reference_moves_from_rest_to_the_target_and_holds_it(config: dict[str, Any]):
    arm = make_arm(config)
    reach = make_reach(config, arm)

    assert reach.steps == 200
    assert reach.substeps == 5
    np.testing.assert_allclose(reach.q_ref[0], arm.q)
    np.testing.assert_allclose(reach.hand_ref[-1], [-0.6, 0.4], atol=1e-5)
    np.testing.assert_array_equal(reach.dq_ref[0], [0.0, 0.0])
    after_move = reach.q_ref[100:]  # the move takes 1 s, 100 periods
    np.testing.assert_array_equal(after_move, np.broadcast_to(reach.q_ref[-1], after_move.shape))
    np.testing.assert_array_equal(reach.dq_ref[100:], 0.0)
    np.testing.assert_allclose(reach.hand_ref, hand_positions(arm, reach.q_ref))


def test_the_reference_accelerations_are_the_derivative_of_its_velocities(config: dict[str, Any]):
    reach = make_reach(config, make_arm(config))

    # The minimum-jerk move starts and ends at rest, without acceleration, and holds still after.
    np.testing.assert_allclose(reach.ddq_ref[[0, 100]], 0.0, atol=1e-12)
    np.testing.assert_array_equal(reach.ddq_ref[101:], 0.0)
    # Central differences of the velocities over the move.
    differences = (reach.dq_ref[2:101] - reach.dq_ref[:99]) / (2 * reach.period)
    np.testing.assert_allclose(reach.ddq_ref[1:100], differences, atol=2e-3 * np.abs(reach.ddq_ref).max())


def test_a_target_out_of_reach_is_refused(config: dict[str, Any]):
    config["reach"]["target"] = [1.0, 0.5]  # the arm is 0.9 m long

    with pytest.raises(ValueError, match="out of reach"):
        make_reach(config, make_arm(config))


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [("duration", 2.005, "control periods"), ("control_period", 0.005, "integration steps")],
)
def test_periods_must_divide_evenly(config: dict[str, Any], key: str, value: float, message: str):
    config["reach"][key] = value

    with pytest.raises(ValueError, match=message):
        make_reach(config, make_arm(config))


def test_pd_gains_are_scaled_by_each_joint_inertia(config: dict[str, Any]):
    arm = make_arm(config)
    inertia = np.diag(compute_mass_matrix(arm))

    kp, kd = pd_gains(arm, omega=5.0, damping_ratio=0.7)

    np.testing.assert_allclose(kp, inertia * 25.0)
    np.testing.assert_allclose(kd, inertia * 7.0)
    np.testing.assert_allclose(command_gains(config, arm)[0], kp)


def test_without_torque_the_arm_stays_put_and_the_error_is_the_reference_distance(config: dict[str, Any]):
    arm = make_arm(config)
    reach = make_reach(config, arm)
    start_q = arm.q.copy()

    run = run_reach(arm, reach, kp=np.zeros(2), kd=np.zeros(2))

    np.testing.assert_allclose(run.q, np.broadcast_to(start_q, run.q.shape))  # no gravity in the plane
    np.testing.assert_array_equal(arm.q, start_q)  # the arm passed in is not changed
    distance = np.linalg.norm(reach.hand_ref[1:] - run.hand[0], axis=1)
    assert tracking_error(run, reach) == pytest.approx(distance.mean())
    assert effort(run, reach) == 0.0


def test_the_feedback_sees_the_tracking_error_and_its_torque_is_added(config: dict[str, Any]):
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)

    by_gains = run_reach(arm, reach, kp, kd)
    by_feedback = run_reach(arm, reach, np.zeros(2), np.zeros(2), feedback=lambda e: kp * e[:2] + kd * e[2:])

    np.testing.assert_allclose(by_feedback.q, by_gains.q)
    np.testing.assert_allclose(by_feedback.tau, by_gains.tau)
    np.testing.assert_allclose(by_feedback.feedback, by_gains.tau)
    np.testing.assert_array_equal(by_gains.feedback, 0.0)


def test_a_stiffer_pd_tracks_closer(config: dict[str, Any]):
    arm = make_arm(config)
    reach = make_reach(config, arm)

    weak = tracking_error(run_reach(arm, reach, *pd_gains(arm, 5.0, 0.7)), reach)
    stiff = tracking_error(run_reach(arm, reach, *pd_gains(arm, 20.0, 0.7)), reach)

    assert weak > 0.1  # the weak PD lags far behind: 170 mm on average
    assert stiff < 0.02


def test_the_dead_zone_forgives_small_errors_and_a_non_finite_run_scores_infinity(config: dict[str, Any]):
    arm = make_arm(config)
    reach = make_reach(config, arm)
    run = run_reach(arm, reach, *command_gains(config, arm))
    worst = np.linalg.norm(run.hand[1:] - reach.hand_ref[1:], axis=1).max()

    assert tracking_error(run, reach, dead_zone=0.01) < tracking_error(run, reach)
    assert tracking_error(run, reach, dead_zone=worst) == 0.0
    run.hand[5] = np.nan
    assert tracking_error(run, reach) == np.inf
