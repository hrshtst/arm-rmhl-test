# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for feedforward torques learned by feedback-error learning with an RLS readout."""

from typing import Any

import numpy as np
import pytest

from arm_rmhl_test import feedforward
from arm_rmhl_test.arm import command_gains, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.feedback import Training
from arm_rmhl_test.feedforward import (
    learn,
    make_model,
    readout_weights,
    reference_inputs,
    run_frozen,
    run_trial,
    split_weights,
    summarize,
    train,
)

READOUT = {"forgetting": 0.999, "delta": 10.0}


@pytest.fixture
def setup(config: dict[str, Any]):
    """A short reach, to keep the tests fast, with the weak PD's gains."""
    config["reach"]["duration"] = 0.5
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    return arm, reach, kp, kd


def test_the_readout_is_rls_with_the_settings_of_the_table():
    readout = make_model(READOUT).get_readout()

    assert (readout.getLambda(), readout.getDelta(), readout.getIncludeBias()) == (0.999, 10.0, True)


def test_the_input_is_the_reference_at_the_start_of_each_period(setup):
    _, reach, _, _ = setup

    inputs = reference_inputs(reach)

    assert inputs.shape == (reach.steps, 6)
    np.testing.assert_array_equal(inputs[7], np.concatenate((reach.q_ref[7], reach.dq_ref[7], reach.ddq_ref[7])))


def test_a_fresh_model_adds_no_torque_and_learns_nothing_without_learning(setup):
    arm, reach, kp, kd = setup
    model = make_model(READOUT)

    error, run = run_trial(model, arm, reach, kp, kd, dead_zone=0.0, learn=False)

    np.testing.assert_array_equal(run.feedback, 0.0)
    assert error == tracking_error(run_reach(arm, reach, kp, kd), reach)
    assert model.get_readout().getInputDim() == 0  # never fitted
    np.testing.assert_array_equal(readout_weights(model, arm.num_joints), np.zeros((7, 2)))


def test_a_reach_that_learns_fits_its_feedforward_plus_the_pds_torque(setup, monkeypatch: pytest.MonkeyPatch):
    arm, reach, kp, kd = setup
    model = make_model(READOUT)
    targets: list[np.ndarray] = []
    fit = model.partial_fit

    def recording_fit(x: Any, y: Any) -> None:
        targets.append(np.asarray(y)[0].copy())
        fit(x, y)

    monkeypatch.setattr(model, "partial_fit", recording_fit)

    _, run = run_trial(model, arm, reach, kp, kd, dead_zone=0.0)

    assert len(targets) == reach.steps
    np.testing.assert_array_equal(run.feedback[0], 0.0)  # the weights start at zero
    assert np.any(run.feedback[1:] != 0.0)  # and change within the reach
    pd = kp * (reach.q_ref[:-1] - run.q[:-1]) + kd * (reach.dq_ref[:-1] - run.dq[:-1])
    np.testing.assert_allclose(targets, run.feedback + pd, rtol=1e-12, atol=1e-12)


def test_the_weights_read_from_the_readout_give_its_predictions(setup):
    arm, reach, kp, kd = setup
    model = make_model(READOUT)
    run_trial(model, arm, reach, kp, kd, dead_zone=0.0)

    weights = readout_weights(model, arm.num_joints)

    inputs = np.random.default_rng(0).normal(size=(10, 6))
    predicted = np.asarray(model.get_readout().predict(inputs))
    np.testing.assert_allclose(inputs @ weights[:-1] + weights[-1], predicted, rtol=1e-12, atol=1e-12)


def test_training_learns_and_its_weights_replay_its_evaluations(setup):
    arm, reach, kp, kd = setup
    model = make_model(READOUT)

    training = train(model, arm, reach, kp, kd, trials=4, dead_zone=0.0, evaluate_every=2)

    assert training.diverged is None
    np.testing.assert_array_equal(training.evaluated_at, [0, 2, 4])
    assert training.evaluations[0] == tracking_error(run_reach(arm, reach, kp, kd), reach)
    assert training.evaluations[-1] < training.evaluations[0]
    np.testing.assert_array_equal(training.weights[0], 0.0)
    np.testing.assert_array_equal(training.scale, [1.0, 1.0])
    for weights, evaluation in zip(training.weights, training.evaluations, strict=True):
        assert run_frozen(weights, arm, reach, kp, kd, 0.0)[0] == evaluation


def test_a_diverging_arm_stops_the_training_and_is_recorded(setup, monkeypatch: pytest.MonkeyPatch):
    arm, reach, kp, kd = setup
    calls: list[None] = []

    def run_reach_overflowing(*args: Any) -> Any:
        calls.append(None)
        if len(calls) == 2:  # the first reach that learns
            raise OverflowError("math range error")
        return run_reach(*args)

    monkeypatch.setattr(feedforward, "run_reach", run_reach_overflowing)

    training = train(make_model(READOUT), arm, reach, kp, kd, trials=3, dead_zone=0.0, evaluate_every=2)

    assert training.diverged == "OverflowError: math range error"
    assert np.isfinite(training.evaluations[0])
    assert training.errors[0] == np.inf
    assert np.all(np.isnan(training.errors[1:]))
    assert np.all(np.isnan(training.evaluations[1:]))


def test_learning_from_a_configuration_trains_a_fresh_model(setup, config: dict[str, Any]):
    arm, reach, kp, kd = setup
    config |= {"readout": READOUT, "training": {"trials": 2, "dead_zone": 0.0, "evaluate_every": 1}}

    training = learn(config)

    expected = train(make_model(READOUT), arm, reach, kp, kd, trials=2, dead_zone=0.0, evaluate_every=1)
    np.testing.assert_array_equal(training.errors, expected.errors)
    np.testing.assert_array_equal(training.weights, expected.weights)


def test_the_weights_split_into_reference_gains_with_a_row_per_joint_torque():
    weights = np.arange(14.0).reshape(7, 2)

    angle, velocity, acceleration, constant = split_weights(weights)

    np.testing.assert_array_equal(angle, [[0.0, 2.0], [1.0, 3.0]])
    np.testing.assert_array_equal(velocity, [[4.0, 6.0], [5.0, 7.0]])
    np.testing.assert_array_equal(acceleration, [[8.0, 10.0], [9.0, 11.0]])
    np.testing.assert_array_equal(constant, [12.0, 13.0])


def test_a_summary_gives_the_course_and_the_final_weights():
    weights = np.full((3, 7, 2), np.nan)
    weights[-1] = np.arange(14.0).reshape(7, 2)
    training = Training(np.full(4, 0.1), np.array([0, 2, 4]), np.array([0.17, 0.05, 0.02]), weights, np.ones(2), None)

    row = summarize(training)

    assert (row["pd_error_m"], row["final_error_m"], row["outcome"]) == (0.17, 0.02, "improved")
    assert (row["angle_12"], row["velocity_21"], row["acceleration_22"], row["constant_2"]) == (2.0, 5.0, 11.0, 13.0)
    assert "stiffness_11" not in row
