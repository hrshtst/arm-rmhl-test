# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""Sanity checks of the environment: the pinned libraries import and offer what the study uses."""

import arm_rmhl_test  # noqa: F401  (sets OMP_NUM_THREADS before rclib is imported)


def test_rclib_offers_reward_modulated_learning():
    from rclib import ESN, learning, readouts

    assert hasattr(ESN, "act")
    assert hasattr(ESN, "reinforce")
    assert callable(learning.burms2015)
    assert hasattr(readouts, "RewardModulated")


def test_skelarm_imports():
    from skelarm import Skeleton, compute_forward_kinematics

    assert callable(compute_forward_kinematics)
    assert Skeleton is not None
