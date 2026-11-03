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
- **The feedback** comes from the readout's output, every 10 ms, from the tracking
  error `[q_ref - q, dq_ref - dq]` and a constant 1. It starts at zero weights and
  adds to the PD's torque; both are held over the period. It has two variants:
  - **raw torque**: the output is the torque (N m);
  - **inertia-scaled**: each joint's output is multiplied by its inertia at the
    start, as the PD's gains are. The output is then in rad/s^2, and the weights
    read as the PD's `omega^2` and `2 zeta omega`.

  The exploration noise is added to the output, in its units.
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
2. **Tuning.** For each rule and variant, the learning rate and the exploration
   amplitude are tuned by hand on seed 0, in rounds of `tune_<rule>*.toml` of
   1,000 trials each.
3. **The final runs.** The tuned settings of each rule and variant run on seeds 1
   to 5, which the tuning never saw, all with the same trial budget.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `pd_grid.toml` | `pd_grid.py` | the PD alone, 13 natural frequencies (2 to 160 rad/s) by 6 damping ratios (0.1 to 1.4) |
| `tune_plain.toml` | `learn_feedback.py` | tuning round 1 of the plain rule, seed 0: 3 exploration amplitudes (0.05 to 0.2 N m) by 5 learning rates (0.3 to 30), 1,000 trials |
| `tune_decorrelated.toml` | `learn_feedback.py` | tuning round 1 of the decorrelated rule, seed 0: the same amplitudes by 5 learning rates (10 to 1,000), 1,000 trials |
| `tune_plain_round2.toml` | `learn_feedback.py` | tuning round 2 of the plain rule with raw torque: amplitudes 0.2 to 0.8 N m by 5 learning rates (0.12 to 2) |
| `tune_decorrelated_round2.toml` | `learn_feedback.py` | tuning round 2 of the decorrelated rule with raw torque: amplitudes 0.2 to 0.8 N m by 5 learning rates (5 to 80) |
| `tune_plain_inertia.toml` | `learn_feedback.py` | tuning round 1 of the plain rule with inertia-scaled feedback: amplitudes 0.5 to 4 rad/s^2 by 6 learning rates (0.3 to 100) |
| `tune_decorrelated_inertia.toml` | `learn_feedback.py` | tuning round 1 of the decorrelated rule with inertia-scaled feedback: amplitudes 0.5 to 4 rad/s^2 by 6 learning rates (10 to 3,000) |
| `tune_plain_round3.toml` | `learn_feedback.py` | tuning round 3 of the plain rule with raw torque: amplitudes 0.8 to 3.2 N m by 4 learning rates (0.03 to 0.25) |
| `tune_decorrelated_round3.toml` | `learn_feedback.py` | tuning round 3 of the decorrelated rule with raw torque: amplitudes 0.8 to 3.2 N m by 4 learning rates (2.5 to 20) |
| `tune_plain_inertia_round2.toml` | `learn_feedback.py` | tuning round 2 of the plain rule with inertia-scaled feedback: amplitudes 2 to 8 rad/s^2 by 4 learning rates (0.04 to 0.3) |
| `tune_decorrelated_inertia_round2.toml` | `learn_feedback.py` | tuning round 2 of the decorrelated rule with inertia-scaled feedback: amplitudes 4 to 16 rad/s^2 by 4 learning rates (12 to 100) |

```bash
uv run python experiments/pd_grid.py experiments/feedback_from_scratch/pd_grid.toml
uv run python experiments/learn_feedback.py experiments/feedback_from_scratch/<configuration>.toml --workers 15
```

## Runs

Under `results/feedback_from_scratch/` in the storage root:

| Run | Result |
| --- | --- |
| `20261103-210822-pd_grid` | The closest PD is 80 rad/s with a damping ratio of 0.2: 0.8 mm. Its neighbors at a damping ratio of 0.1 or 0.4, and every PD of 112 rad/s or more, run away under the 10-ms hold. |
| `20261103-210821-tune_plain` | 8 of 15 settings improve on the PD alone, still falling at 1,000 trials. The closest is an amplitude of 0.2 N m with a learning rate of 1: 46.7 mm. The other 7 run away within 20 trials, to about 700 mm, raising nothing. |
| `20261103-210821-tune_decorrelated` | 8 of 15 settings improve, still falling at 1,000 trials. The closest is an amplitude of 0.2 N m with a learning rate of 30: 68.1 mm. Of the 7 that run away, 3 do so late, after 100 to 560 trials of improving. |

| `20261103-223958-tune_plain_round2` | Raw torque. 9 of 15 improve. The closest is 0.8 N m with a learning rate of 0.25: 27.8 mm. Where the learning rate times the amplitude reaches 0.4, the gains run away. |
| `20261103-223958-tune_decorrelated_round2` | Raw torque. 11 of 15 improve. The closest is 0.8 N m with a learning rate of 20: 19.5 mm. Where the learning rate times the amplitude reaches 16 to 32, the gains run away. |
| `20261103-223958-tune_plain_inertia` | Inertia-scaled. 6 of 24 improve. The closest is 2 rad/s^2 with a learning rate of 0.3: 46.4 mm. The run-aways are single updates that throw the damping from about 10 to tens of thousands per second. |
| `20261103-223958-tune_decorrelated_inertia` | Inertia-scaled. 15 of 24 improve. The closest is 4 rad/s^2 with a learning rate of 100: 19.1 mm. |

Each training took 6 to 13 minutes with 30 running at once on the
workstation, about 0.6 s per trial. Every closest setting so far is still
improving at 1,000 trials. The exploring reaches track only slightly worse
than the noise-free ones: over the last 100 trials of the closest decorrelated
setting with raw torque, 21.3 mm on average, against 19.5 mm at the end.
