# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for feedforward and feedback torques learned together."""

from typing import Any

import numpy as np
import pytest
from rclib import ESN

from arm_rmhl_test import feedback, feedforward
from arm_rmhl_test.arm import command_gains, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.combined import (
    CombinedTraining,
    Learners,
    Schedule,
    combine,
    learn,
    make_learners,
    make_schedule,
    run_trial,
    summarize,
    train,
)
from arm_rmhl_test.feedback import Training

READOUT = {"forgetting": 0.999, "delta": 10.0}
RULE = {
    "preset": "burms2015",
    "learning_rate": 2.0,
    "exploration": {"distribution": "gaussian", "amplitude": 0.1, "seed": 3},
}
CONCURRENT = Schedule()


@pytest.fixture
def setup(config: dict[str, Any]):
    """A short reach, to keep the tests fast, with the weak PD's gains."""
    config["reach"]["duration"] = 0.5
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    return arm, reach, kp, kd


def both() -> tuple[Learners, ESN, ESN]:
    """Fresh learners of both kinds, from zero weights, and their RLS and reward-modulated models."""
    rls = feedforward.make_model(READOUT)
    rmhl = feedback.make_model(feedback.make_rule(RULE), joints=2)
    return Learners(rls, rmhl), rls, rmhl


def test_without_a_feedforward_it_trains_exactly_as_the_feedback_alone(setup):
    arm, reach, kp, kd = setup
    scale = np.array([0.5, 2.0])
    alone = feedback.make_model(feedback.make_rule(RULE), arm.num_joints)
    learners = Learners(None, feedback.make_model(feedback.make_rule(RULE), arm.num_joints))

    training = train(
        learners, arm, reach, kp, kd, schedule=CONCURRENT, scale=scale, trials=5, dead_zone=0.0, evaluate_every=2
    )

    expected = feedback.train(alone, arm, reach, kp, kd, trials=5, dead_zone=0.0, evaluate_every=2, scale=scale)
    np.testing.assert_array_equal(training.errors, expected.errors)
    np.testing.assert_array_equal(training.evaluated_at, expected.evaluated_at)
    np.testing.assert_array_equal(training.evaluations, expected.evaluations)
    np.testing.assert_array_equal(training.weights, expected.weights)
    np.testing.assert_array_equal(training.feedforward_weights, 0.0)


def test_without_a_feedback_it_trains_exactly_as_the_feedforward_alone(setup):
    arm, reach, kp, kd = setup
    learners = Learners(feedforward.make_model(READOUT), None)

    training = train(
        learners, arm, reach, kp, kd, schedule=CONCURRENT, scale=np.ones(2), trials=4, dead_zone=0.0, evaluate_every=1
    )

    expected = feedforward.train(
        feedforward.make_model(READOUT), arm, reach, kp, kd, trials=4, dead_zone=0.0, evaluate_every=1
    )
    np.testing.assert_array_equal(training.errors, expected.errors)
    np.testing.assert_array_equal(training.evaluations, expected.evaluations)
    np.testing.assert_array_equal(training.feedforward_weights, expected.weights)
    np.testing.assert_array_equal(training.weights, 0.0)


def test_the_rls_readout_fits_its_output_plus_the_weak_pds_torque_alone(setup, monkeypatch: pytest.MonkeyPatch):
    arm, reach, kp, kd = setup
    learners, model, rmhl = both()
    run_trial(learners, arm, reach, kp, kd, 0.0, scale=np.ones(2), learn_feedforward=True, learn_feedback=True)
    rmhl.reinforce(-1.0)
    outputs: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    predict, fit = model.predict_online, model.partial_fit

    def recording_predict(x: Any) -> Any:
        outputs.append(np.asarray(predict(x))[0].copy())
        return outputs[-1].reshape(1, -1)

    def recording_fit(x: Any, y: Any) -> None:
        targets.append(np.asarray(y)[0].copy())
        fit(x, y)

    monkeypatch.setattr(model, "predict_online", recording_predict)
    monkeypatch.setattr(model, "partial_fit", recording_fit)

    _, run = run_trial(learners, arm, reach, kp, kd, 0.0, scale=np.ones(2), learn_feedforward=True, learn_feedback=True)

    assert len(targets) == len(outputs) == reach.steps
    pd = kp * (reach.q_ref[:-1] - run.q[:-1]) + kd * (reach.dq_ref[:-1] - run.dq[:-1])
    np.testing.assert_allclose(targets, np.array(outputs) + pd, rtol=1e-12, atol=1e-12)
    feedback_part = run.feedback - np.array(outputs)  # the feedback torque, with its noise
    assert np.all(feedback_part != 0.0)
    np.testing.assert_allclose(run.tau, pd + run.feedback, rtol=1e-12, atol=1e-12)


def test_the_feedback_is_reinforced_after_each_reach_with_minus_its_error(setup, monkeypatch: pytest.MonkeyPatch):
    arm, reach, kp, kd = setup
    learners, _, rmhl = both()
    rewards: list[float] = []
    reinforce = rmhl.reinforce

    def recording_reinforce(reward: float) -> None:
        rewards.append(reward)
        reinforce(reward)

    monkeypatch.setattr(rmhl, "reinforce", recording_reinforce)

    training = train(
        learners, arm, reach, kp, kd, schedule=CONCURRENT, scale=np.ones(2), trials=3, dead_zone=0.0, evaluate_every=3
    )

    np.testing.assert_array_equal(rewards, -training.errors)
    assert np.all(training.feedforward_weights[-1] != 0.0)  # the feedforward learned meanwhile


def test_a_staged_schedule_hands_the_learning_over(setup, monkeypatch: pytest.MonkeyPatch):
    arm, reach, kp, kd = setup
    learners, rls, rmhl = both()
    fits: list[Any] = []
    rewards: list[float] = []
    fit, reinforce = rls.partial_fit, rmhl.reinforce

    def recording_fit(x: Any, y: Any) -> None:
        fits.append(y)
        fit(x, y)

    def recording_reinforce(reward: float) -> None:
        rewards.append(reward)
        reinforce(reward)

    monkeypatch.setattr(rls, "partial_fit", recording_fit)
    monkeypatch.setattr(rmhl, "reinforce", recording_reinforce)

    training = train(
        learners,
        arm,
        reach,
        kp,
        kd,
        schedule=Schedule("staged", handover=2),
        scale=np.ones(2),
        trials=5,
        dead_zone=0.0,
        evaluate_every=1,
    )

    assert len(fits) == 2 * reach.steps  # the first two reaches
    np.testing.assert_array_equal(rewards, -training.errors[2:])  # the reaches after
    assert np.any(training.feedforward_weights[2] != 0.0)
    np.testing.assert_array_equal(
        training.feedforward_weights[2:], np.broadcast_to(training.feedforward_weights[2], (4, 7, 2))
    )
    np.testing.assert_array_equal(training.weights[:4], 0.0)  # the first reward only sets the baseline
    assert np.any(training.weights[4] != 0.0)


def test_a_reach_that_learns_neither_changes_no_learning_state(setup):
    arm, reach, kp, kd = setup
    learners, rls, rmhl = both()

    error, run = run_trial(
        learners, arm, reach, kp, kd, 0.0, scale=np.ones(2), learn_feedforward=False, learn_feedback=False
    )

    assert error == tracking_error(run_reach(arm, reach, kp, kd), reach)  # zero weights add no torque
    np.testing.assert_array_equal(run.feedback, 0.0)
    assert rls.get_readout().getInputDim() == 0
    with pytest.raises(RuntimeError, match="exploring act"):
        rmhl.reinforce(-1.0)


def test_the_stored_weights_replay_the_evaluations(setup):
    arm, reach, kp, kd = setup
    scale = np.array([0.5, 2.0])

    training = train(
        both()[0], arm, reach, kp, kd, schedule=CONCURRENT, scale=scale, trials=3, dead_zone=0.0, evaluate_every=1
    )

    for row in range(len(training.evaluated_at)):
        model = feedback.make_model(feedback.make_rule(RULE), arm.num_joints)
        model.get_readout().setWeights(training.weights[row])
        torque = combine(
            feedforward.frozen_feedforward(training.feedforward_weights[row], reach),
            feedback.feedback_torque(model, scale, explore=False),
        )
        assert tracking_error(run_reach(arm, reach, kp, kd, torque), reach) == training.evaluations[row]


def test_a_diverging_arm_stops_the_training_and_is_recorded(setup):
    arm, reach, kp, kd = setup
    learners, _, rmhl = both()
    rmhl.get_readout().setWeights(np.full((5, 2), 1e300))  # a torque too large for skelarm's kinematics

    training = train(
        learners, arm, reach, kp, kd, schedule=CONCURRENT, scale=np.ones(2), trials=3, dead_zone=0.0, evaluate_every=2
    )

    assert training.diverged is not None
    assert training.diverged.startswith("OverflowError")
    assert training.evaluations[0] == np.inf
    assert np.all(np.isnan(training.evaluations[1:]))


def test_the_schedules_say_which_reaches_each_learner_learns_from():
    staged = Schedule("staged", handover=3)

    assert all(CONCURRENT.feedforward_learns(t) and CONCURRENT.feedback_learns(t) for t in range(5))
    assert [staged.feedforward_learns(t) for t in range(5)] == [True, True, True, False, False]
    assert [staged.feedback_learns(t) for t in range(5)] == [False, False, False, True, True]
    with pytest.raises(ValueError, match="unknown schedule"):
        Schedule("alternating")
    with pytest.raises(ValueError, match="handover"):
        Schedule("staged")


def test_the_tables_give_the_learners_and_the_schedule(config: dict[str, Any]):
    assert make_schedule(config) == CONCURRENT
    assert make_schedule(config | {"schedule": {"kind": "staged", "handover": 100}}) == Schedule("staged", 100)
    assert make_schedule(config | {"schedule": {"kind": "concurrent", "handover": 100}}).feedforward_learns(200)

    learners = make_learners(config | {"readout": READOUT, "rule": RULE}, joints=2)
    assert learners.feedforward is not None
    assert learners.feedback is not None
    np.testing.assert_array_equal(learners.feedback.get_readout().getWeights(), 0.0)
    assert make_learners(config | {"rule": RULE}, joints=2).feedforward is None
    assert make_learners(config | {"readout": READOUT}, joints=2).feedback is None
    with pytest.raises(ValueError, match="nothing to learn"):
        make_learners(config, joints=2)


def test_learning_from_a_configuration_trains_fresh_learners(setup, config: dict[str, Any]):
    arm, reach, kp, kd = setup
    config |= {
        "readout": READOUT,
        "feedback": {"scale": "inertia"},
        "rule": RULE,
        "schedule": {"kind": "staged", "handover": 1},
        "training": {"trials": 2, "dead_zone": 0.0, "evaluate_every": 1},
    }

    training = learn(config)

    expected = train(
        both()[0],
        arm,
        reach,
        kp,
        kd,
        schedule=Schedule("staged", 1),
        scale=feedback.feedback_scale(config, arm),
        trials=2,
        dead_zone=0.0,
        evaluate_every=1,
    )
    np.testing.assert_array_equal(training.errors, expected.errors)
    np.testing.assert_array_equal(training.scale, expected.scale)
    np.testing.assert_array_equal(training.weights, expected.weights)
    np.testing.assert_array_equal(training.feedforward_weights, expected.feedforward_weights)


def test_the_summary_reads_the_final_gains_and_weights():
    feedback_weights = np.arange(10.0).reshape(5, 2)  # rows: e_q1, e_q2, e_dq1, e_dq2, 1
    feedforward_weights = 100 + np.arange(14.0).reshape(7, 2)  # rows: q_ref, dq_ref, ddq_ref by joint, then 1
    training = CombinedTraining(
        np.zeros(2),
        np.array([0, 2]),
        np.array([0.17, 0.004]),
        np.stack((np.zeros((5, 2)), feedback_weights)),
        np.array([1.0, 2.0]),
        None,
        np.stack((np.zeros((7, 2)), feedforward_weights)),
    )

    row = summarize(training)

    assert (row["final_error_m"], row["outcome"]) == (0.004, "improved")
    assert (row["stiffness_12"], row["damping_21"], row["feedback_constant_2"]) == (2.0, 2 * 5.0, 2 * 9.0)
    assert (row["angle_12"], row["acceleration_21"], row["feedforward_constant_1"]) == (102.0, 109.0, 112.0)
    with pytest.raises(TypeError, match="CombinedTraining"):
        summarize(
            Training(np.zeros(2), np.array([0, 2]), np.array([0.17, 0.004]), np.zeros((2, 5, 2)), np.ones(2), None)
        )
