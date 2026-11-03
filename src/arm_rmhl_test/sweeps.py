# Copyright (C) 2026 Hiroshi Atsuta <atsuta@ieee.org>
# SPDX-License-Identifier: GPL-3.0-only

"""A configuration swept over some of its settings.

A ``[sweep]`` table lists values for settings the configuration already has, each
named by its dotted path, a quoted key in TOML:

.. code-block:: toml

    [sweep]
    "rule.exploration.amplitude" = [0.05, 0.1]
    "rule.learning_rate" = [0.3, 1.0, 3.0]

Every combination of those values gives one configuration: a copy of the original
with those settings replaced and without the ``[sweep]`` table. The combinations
come in the order of ``itertools.product``: the last setting varies fastest.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Mapping
from typing import Any


def expand(config: Mapping[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every combination of the ``[sweep]`` table: its values by setting, and its configuration.

    A configuration without a ``[sweep]`` table is one combination of no values.

    Raises
    ------
    KeyError
        If a swept setting is not in the configuration.
    """
    sweep: Mapping[str, list[Any]] = config.get("sweep", {})
    base = {name: table for name, table in config.items() if name != "sweep"}
    combinations = []
    for values in itertools.product(*sweep.values()):
        combination = dict(zip(sweep, values, strict=True))
        variant = copy.deepcopy(base)
        for path, value in combination.items():
            _replace(variant, path, value)
        combinations.append((combination, variant))
    return combinations


def _replace(config: dict[str, Any], path: str, value: Any) -> None:
    """Replace the setting at a dotted path, which must be in the configuration."""
    *tables, key = path.split(".")
    table: Any = config
    for name in tables:
        table = table.get(name) if isinstance(table, dict) else None
    if not isinstance(table, dict) or key not in table:
        msg = f"the swept setting {path!r} is not in the configuration"
        raise KeyError(msg)
    table[key] = value
