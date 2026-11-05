# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the feedback learned from one reward per reach."""

from typing import Any

import numpy as np
import pytest
from rclib import learning
from skelarm.dynamics import compute_mass_matrix

from arm_rmhl_test.arm import command_gains, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.feedback import (
    Training,
    evaluation_trials,
    feedback_gains,
    feedback_scale,
    learn,
    make_model,
    make_rule,
    run_trial,
    split_weights,
    summarize,
    train,
    training_settings,
)

RULE = {
    "preset": "burms2015",
    "learning_rate": 2.0,
    "exploration": {"distribution": "gaussian", "amplitude": 0.1, "seed": 3},
}


@pytest.fixture
def setup(config: dict[str, Any]):
    """A short reach, to keep the tests fast, with the weak PD's gains."""
    config["reach"]["duration"] = 0.5
    arm = make_arm(config)
    reach = make_reach(config, arm)
    kp, kd = command_gains(config, arm)
    return arm, reach, kp, kd


def test_the_rule_is_the_preset_with_the_settings_of_the_table():
    rule = make_rule(RULE)

    assert rule.learning_rate == 2.0
    assert rule.exploration == learning.Exploration(distribution="gaussian", amplitude=0.1, seed=3)
    assert rule.update == "trial"  # as burms2015 sets it
    assert rule.decorrelation == 1.0


def test_false_turns_an_optional_setting_off_and_other_settings_are_replaced():
    assert make_rule({**RULE, "decorrelation": False}).decorrelation is None
    assert make_rule({**RULE, "decorrelation": 10.0}).decorrelation == 10.0
    rule = make_rule({**RULE, "baseline": {"kind": "ema", "decay": 0.9}, "modulator": "heaviside"})
    assert rule.baseline == learning.Baseline(kind="ema", decay=0.9)
    assert rule.modulator == "heaviside"


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError, match="unknown preset"):
        make_rule({**RULE, "preset": "nonexistent"})


def test_a_fresh_model_adds_no_torque(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)

    error, run = run_trial(model, arm, reach, kp, kd, dead_zone=0.0, explore=False)

    assert error == tracking_error(run_reach(arm, reach, kp, kd), reach)
    np.testing.assert_array_equal(run.feedback, 0.0)
    for gains in feedback_gains(model):
        np.testing.assert_array_equal(gains, 0.0)


def test_the_weights_read_as_stiffness_damping_and_a_constant_torque():
    model = make_model(make_rule(RULE), joints=2)
    weights = np.random.default_rng(0).normal(size=(5, 2))
    model.get_readout().setWeights(weights)
    error = np.array([0.1, -0.2, 0.3, 0.4])

    stiffness, damping, constant = feedback_gains(model)

    torque = model.act(error.reshape(1, -1), explore=False)[0]
    np.testing.assert_allclose(torque, stiffness @ error[:2] + damping @ error[2:] + constant)


def test_a_noise_free_reach_changes_no_learning_state(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)

    run_trial(model, arm, reach, kp, kd, dead_zone=0.0, explore=False)

    with pytest.raises(RuntimeError, match="exploring act"):
        model.reinforce(-1.0)


def test_exploring_reaches_learn_once_the_baseline_is_set(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)

    error, run = run_trial(model, arm, reach, kp, kd, dead_zone=0.0)
    model.reinforce(-error)

    assert np.all(run.feedback != 0.0)  # the exploration noise
    np.testing.assert_array_equal(model.get_readout().getWeights(), 0.0)  # the first reward sets the baseline
    error, _ = run_trial(model, arm, reach, kp, kd, dead_zone=0.0)
    model.reinforce(-error)
    assert np.any(np.asarray(model.get_readout().getWeights()) != 0.0)


def test_training_evaluates_noise_free_reaches_before_between_and_after(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)

    training = train(model, arm, reach, kp, kd, trials=5, dead_zone=0.0, evaluate_every=2)

    assert training.diverged is None
    assert np.all(np.isfinite(training.errors))
    np.testing.assert_array_equal(training.evaluated_at, [0, 2, 4, 5])
    assert np.all(np.isfinite(training.evaluations))
    assert training.evaluations[0] == tracking_error(run_reach(arm, reach, kp, kd), reach)
    np.testing.assert_array_equal(training.weights[0], 0.0)
    np.testing.assert_array_equal(training.weights[-1], model.get_readout().getWeights())


def test_a_diverging_arm_stops_the_training_and_is_recorded(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)
    model.get_readout().setWeights(np.full((5, 2), 1e300))  # a torque too large for skelarm's kinematics

    training = train(model, arm, reach, kp, kd, trials=3, dead_zone=0.0, evaluate_every=2)

    assert training.diverged is not None
    assert training.diverged.startswith("OverflowError")
    assert training.evaluations[0] == np.inf
    assert np.all(np.isnan(training.evaluations[1:]))
    assert np.all(np.isnan(training.errors))


def test_training_can_evaluate_every_trial_of_its_start(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)

    training = train(model, arm, reach, kp, kd, trials=7, dead_zone=0.0, evaluate_every=3, evaluate_all_until=2)

    np.testing.assert_array_equal(training.evaluated_at, [0, 1, 2, 3, 6, 7])
    assert np.all(np.isfinite(training.evaluations))


def test_evaluations_come_at_the_start_every_trial_until_a_point_then_every_few_and_at_the_end():
    np.testing.assert_array_equal(evaluation_trials(10, 4), [0, 4, 8, 10])
    np.testing.assert_array_equal(evaluation_trials(10, 4, 5), [0, 1, 2, 3, 4, 5, 8, 10])
    np.testing.assert_array_equal(evaluation_trials(3, 20, 100), [0, 1, 2, 3])  # never past the end
    np.testing.assert_array_equal(evaluation_trials(200, 20, 0), np.append(np.arange(0, 200, 20), 200))


def test_the_training_table_gives_the_settings_of_train():
    config = {"training": {"trials": 1000, "dead_zone": 0.0, "evaluate_every": 20}}

    assert training_settings(config) == {
        "trials": 1000,
        "dead_zone": 0.0,
        "evaluate_every": 20,
        "evaluate_all_until": 0,  # by default, no trial is evaluated for being early
    }
    config["training"]["evaluate_all_until"] = 100
    assert training_settings(config)["evaluate_all_until"] == 100


def test_learning_from_a_configuration_trains_a_fresh_model(setup, config: dict[str, Any]):
    arm, reach, kp, kd = setup
    config |= {"rule": RULE, "training": {"trials": 3, "dead_zone": 0.0, "evaluate_every": 2}}
    model = make_model(make_rule(RULE), arm.num_joints)

    training = learn(config)

    expected = train(model, arm, reach, kp, kd, trials=3, dead_zone=0.0, evaluate_every=2)
    np.testing.assert_array_equal(training.errors, expected.errors)
    np.testing.assert_array_equal(training.weights, expected.weights)


def training(evaluations: list[float], diverged: str | None = None) -> Training:
    """A training of four trials evaluated every two, whose final weights count up from 0."""
    weights = np.full((len(evaluations), 5, 2), np.nan)
    if diverged is None:
        weights[-1] = np.arange(10.0).reshape(5, 2)
    return Training(np.full(4, 0.1), np.array([0, 2, 4]), np.array(evaluations), weights, np.ones(2), diverged)


def test_the_weights_split_into_gains_with_a_row_per_joint_torque():
    stiffness, damping, constant = split_weights(np.arange(10.0).reshape(5, 2))

    np.testing.assert_array_equal(stiffness, [[0.0, 2.0], [1.0, 3.0]])
    np.testing.assert_array_equal(damping, [[4.0, 6.0], [5.0, 7.0]])
    np.testing.assert_array_equal(constant, [8.0, 9.0])


def test_a_summary_gives_the_errors_the_outcome_and_the_final_gains():
    row = summarize(training([0.17, 0.12, 0.13]))

    assert row["pd_error_m"] == 0.17
    assert row["final_error_m"] == 0.13
    assert (row["best_error_m"], row["best_after"]) == (0.12, 2)
    assert (row["outcome"], row["diverged"]) == ("improved", "")
    assert (row["stiffness_12"], row["stiffness_21"], row["damping_11"], row["constant_2"]) == (2.0, 1.0, 4.0, 9.0)


def test_a_final_error_no_better_than_the_pds_is_worse():
    assert summarize(training([0.17, 0.12, 0.7]))["outcome"] == "worse"


def test_a_diverged_training_is_summarized_by_what_it_reached():
    row = summarize(training([0.17, np.inf, np.nan], diverged="OverflowError: math range error"))

    assert row["outcome"] == "diverged"
    assert row["diverged"] == "OverflowError: math range error"
    assert (row["best_error_m"], row["best_after"]) == (0.17, 0)
    assert np.isnan(row["final_error_m"])
    assert np.isnan(row["stiffness_11"])


def test_a_training_that_diverged_at_once_has_no_best():
    row = summarize(training([np.inf, np.nan, np.nan], diverged="RuntimeError: the output is not finite"))

    assert np.isnan(row["best_error_m"])
    assert row["best_after"] == -1


def test_the_feedback_scale_is_one_or_each_joints_inertia(config: dict[str, Any]):
    arm = make_arm(config)

    np.testing.assert_array_equal(feedback_scale(config, arm), [1.0, 1.0])
    np.testing.assert_array_equal(feedback_scale({"feedback": {"scale": "none"}}, arm), [1.0, 1.0])
    inertia = np.diag(compute_mass_matrix(arm))
    np.testing.assert_array_equal(feedback_scale({"feedback": {"scale": "inertia"}}, arm), inertia)
    with pytest.raises(ValueError, match="unknown feedback scale"):
        feedback_scale({"feedback": {"scale": "mass"}}, arm)


def test_the_scaled_feedback_torque_is_the_output_times_the_scale(setup):
    arm, reach, kp, kd = setup
    model = make_model(make_rule(RULE), arm.num_joints)
    model.get_readout().setWeights(np.random.default_rng(0).normal(scale=0.1, size=(5, 2)))
    scale = np.array([0.5, 2.0])

    _, run = run_trial(model, arm, reach, kp, kd, dead_zone=0.0, scale=scale, explore=False)

    error = np.concatenate((reach.q_ref[3] - run.q[3], reach.dq_ref[3] - run.dq[3]))
    output = model.act(error.reshape(1, -1), explore=False)[0]
    np.testing.assert_allclose(run.feedback[3], scale * output)


def test_the_summary_gives_the_gains_of_the_torque():
    scaled = training([0.17, 0.12, 0.13])
    scaled = Training(
        scaled.errors, scaled.evaluated_at, scaled.evaluations, scaled.weights, np.array([0.5, 2.0]), None
    )

    row = summarize(scaled)

    assert (row["stiffness_12"], row["stiffness_21"]) == (0.5 * 2.0, 2.0 * 1.0)  # row i is joint i's torque
    assert (row["damping_11"], row["constant_2"]) == (0.5 * 4.0, 2.0 * 9.0)
