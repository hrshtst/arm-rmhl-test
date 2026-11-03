# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Tests for sweeping a configuration over some of its settings."""

import pytest

from arm_rmhl_test.sweeps import expand

CONFIG = {
    "rule": {"learning_rate": 1.0, "exploration": {"amplitude": 0.1, "seed": 0}},
    "training": {"trials": 10},
}


def test_every_combination_replaces_its_settings_and_the_last_varies_fastest():
    config = CONFIG | {"sweep": {"rule.exploration.amplitude": [0.05, 0.2], "rule.learning_rate": [1.0, 2.0, 4.0]}}

    combinations = expand(config)

    assert [values for values, _ in combinations] == [
        {"rule.exploration.amplitude": amplitude, "rule.learning_rate": rate}
        for amplitude in (0.05, 0.2)
        for rate in (1.0, 2.0, 4.0)
    ]
    _, variant = combinations[4]
    assert variant == {
        "rule": {"learning_rate": 2.0, "exploration": {"amplitude": 0.2, "seed": 0}},
        "training": {"trials": 10},
    }
    assert config["rule"] == CONFIG["rule"]  # the original is not changed


def test_the_combinations_do_not_share_tables():
    combinations = expand(CONFIG | {"sweep": {"rule.exploration.seed": [0, 1]}})

    (_, first), (_, second) = combinations
    assert first["rule"]["exploration"]["seed"] == 0
    assert second["rule"]["exploration"]["seed"] == 1
    assert first["training"] is not second["training"]


def test_without_a_sweep_the_configuration_is_one_combination():
    assert expand(CONFIG) == [({}, CONFIG)]


@pytest.mark.parametrize("path", ["rule.learnig_rate", "rule.exploration.amplitude.value", "command.omega"])
def test_a_setting_not_in_the_configuration_is_refused(path: str):
    with pytest.raises(KeyError, match="not in the configuration"):
        expand(CONFIG | {"sweep": {path: [1.0]}})
