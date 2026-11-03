# Feedback from scratch

Can a reward-modulated Hebbian readout learn feedback torques that make a weak
joint PD's reach accurate, from one reward per reach? How close does it come to
the best joint PD of a grid? This is RQ1 of the [project README](../../README.md#research-questions).

## Setup

- **The arm** is arm-esn-ctrl's v2 arm: two links in the horizontal plane, without
  gravity, simulated by skelarm every 2 ms.
- **The reach** starts from rest at (30, 30) deg. Its reference moves the hand to
  (-0.6, 0.4) m by a minimum-jerk move of 1 s in joint space, then holds the goal
  for 1 s.
- **The weak PD** has a natural frequency of 5 rad/s and a damping ratio of 0.7,
  scaled by each joint's inertia at the start. Alone, it lags 170 mm behind the
  reference on average.
- **The feedback** is the readout's output, every 10 ms, from the tracking error
  `[q_ref - q, dq_ref - dq]` and a constant 1. It starts at zero weights and adds
  to the PD's torque; both are held over the period.
- **The reward** is minus the reach's tracking error: the hand's mean distance from
  where the reference puts it, over the 200 control periods, with no dead zone.
- **The rule** is `burms2015` of rclib: Gaussian exploration on the output, and one
  update per reach from the reward's difference from the mean of the last 50
  rewards. The plain rule turns its decorrelation off; the decorrelated rule
  keeps it.

Learning is judged by a noise-free reach every 20 trials, and by the outcome at
the end: `improved` or `worse` than the PD alone, or `diverged` when rclib or
skelarm raised.

## Protocol

1. **The yardstick.** `pd_grid.toml` runs the PD alone over a grid of natural
   frequencies and damping ratios.
2. **Tuning.** For each rule, the learning rate and the exploration amplitude are
   tuned by hand on seed 0, in rounds of `tune_<rule>*.toml`.
3. **The final runs.** Each rule's tuned settings run on seeds 1 to 5, which the
   tuning never saw, with the same trial budget.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `pd_grid.toml` | `pd_grid.py` | the PD alone, 13 natural frequencies (2 to 160 rad/s) by 6 damping ratios (0.1 to 1.4) |
| `tune_plain.toml` | `learn_feedback.py` | tuning round 1 of the plain rule, seed 0: 3 exploration amplitudes (0.05 to 0.2 N m) by 5 learning rates (0.3 to 30), 1,000 trials |
| `tune_decorrelated.toml` | `learn_feedback.py` | tuning round 1 of the decorrelated rule, seed 0: the same amplitudes by 5 learning rates (10 to 1,000), 1,000 trials |

```bash
uv run python experiments/pd_grid.py experiments/feedback_from_scratch/pd_grid.toml
uv run python experiments/learn_feedback.py experiments/feedback_from_scratch/tune_plain.toml --workers 15
uv run python experiments/learn_feedback.py experiments/feedback_from_scratch/tune_decorrelated.toml --workers 15
```

## Runs

None yet.
