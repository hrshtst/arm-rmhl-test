# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for the feedback learned from one reward per reach."""

from typing import Any

import numpy as np
import pytest
from rclib import learning

from arm_rmhl_test.arm import command_gains, make_arm, make_reach, run_reach, tracking_error
from arm_rmhl_test.feedback import (
    feedback_gains,
    make_model,
    make_rule,
    run_trial,
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
    for gains in feedback_gains(model, arm.num_joints):
        np.testing.assert_array_equal(gains, 0.0)


def test_the_weights_read_as_stiffness_damping_and_a_constant_torque():
    model = make_model(make_rule(RULE), joints=2)
    weights = np.random.default_rng(0).normal(size=(5, 2))
    model.get_readout().setWeights(weights)
    error = np.array([0.1, -0.2, 0.3, 0.4])

    stiffness, damping, constant = feedback_gains(model, joints=2)

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


def test_the_training_table_gives_the_settings_of_train():
    config = {"training": {"trials": 1000, "dead_zone": 0.0, "evaluate_every": 20}}

    assert training_settings(config) == {"trials": 1000, "dead_zone": 0.0, "evaluate_every": 20}
