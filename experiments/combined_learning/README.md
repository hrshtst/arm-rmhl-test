# Combined learning

Feedback-error learning and reward-modulated learning, together on the weak PD's
reach. Alone, feedback-error learning with an RLS readout settles at 4.6 mm within
300 reaches (report [002](../../reports/002-feedback-error-learning/README.md)), and
the decorrelated reward-modulated feedback reaches 5.6 mm (raw torque) or 3.8 mm
(inertia-scaled, with a chattering torque) in 10,000 (report
[001](../../reports/001-feedback-from-scratch/README.md)); neither comes within
the 40-rad/s PD's 3.1 mm. Combined, do they track more closely than either alone,
for the same number of reaches? What does each contribute, measured by leaving it
out, and against the weak PD alone? Does learning both at once interfere, against
handing over from one to the other? This belongs to RQ1 of the
[project README](../../README.md#research-questions).

## Setup

- **The arm, the reach, and the weak PD** are those of `feedback_from_scratch`: a
  test checks that the tables are the same.
- **The torque**, every 10 ms, is the weak PD's, plus a feedforward from the
  reference, plus a feedback from the tracking error, all held over the period.
- **The feedforward** is report 002's: an RLS readout of `[q_ref, dq_ref, ddq_ref,
  1]`, learned by feedback-error learning. Every period of a reach it learns from,
  it fits its own output plus the weak PD's torque. The feedback torque, its noise
  included, is part of the plant for it, as the arm is.
- **The feedback** is report 001's: a reward-modulated readout of `[e_q, e_dq, 1]`,
  learned by the decorrelated `burms2015` rule from one reward per reach, minus the
  reach's tracking error, with exploration noise on its output, in raw torque or
  scaled by each joint's inertia.
- **The schedule** says which reaches each learns from: both every reach
  (`concurrent`), or the feedforward the first 100 reaches and the feedback the rest
  (`staged`). A learner that does not learn from a reach adds its torque, with its
  weights as they stand, without noise.
- **The ablations** leave one learner's table out of the configuration: without
  `[readout]` there is no feedforward, without `[rule]` no feedback. Alone, each
  learner trains exactly as in its own experiment, which tests check bit for bit.

Learning is judged as before: by a reach that learns nothing, without noise, with
the weights as they stand. Evaluations come after every one of the first 100
reaches, where the feedforward moves fast, then after every 20th. The outcome at
the end is `improved` or `worse` than the PD alone, or `diverged` when rclib or
skelarm raised.

## Protocol

1. **Tuning**, on seed 0 for 1,000 reaches, chosen by the lowest noise-free error at
   1,000 reaches over all rounds, for each schedule and feedback scale, as in
   `feedback_from_scratch`. The settings of both learners are tuned inside the
   combination, in alternating rounds:
   1. the feedback's learning rate by its exploration amplitude, with the
      feedforward at report 002's tuned setting (`tune_raw.toml`,
      `tune_inertia.toml`), and again past the grid's edge for a variant whose
      best lies on it, until none does (`tune_<schedule>_<scale>_round<n>.toml`);
   2. the feedforward's forgetting factor by its `delta`, report 002's grid, with
      each variant's best feedback setting (`tune_readout_<schedule>_<scale>.toml`);
   3. if the feedforward's best setting moved, the feedback's settings again,
      around their best;
   4. added after the first final runs, which showed the feedforward winding up
      (see [below](#the-feedforwards-wind-up)): for the concurrent schedule, the
      feedforward does not forget, a forgetting factor of 1 with its best `delta`
      for it in its round, and the feedback's settings again around their best
      (`tune_concurrent_<scale>_round5.toml`). The staged schedule keeps its
      settings: its feedforward stops learning after 100 reaches, long before it
      could wind up.
2. **The final runs**, on seeds 1 to 5, which the tuning never saw, for 10,000
   reaches: each schedule and scale at its tuned setting; the ablations, each
   learner alone at the concurrent schedule's settings, the feedback on seeds 1 to
   5 and the feedforward once, having no noise.
3. **The comparison** against the weak PD alone, the PDs of the grid, report 001's
   and report 002's runs, each learner tuned alone, in tracking error over the
   reaches, effort, peak torque, and torque variation. Lesions of the final
   combined controllers, without their feedback or without their feedforward, show
   how the two learned parts depend on each other.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `tune_raw.toml` | `learn_combined.py` | tuning round 1, raw torque: both schedules, 5 learning rates (0.8 to 80) by 4 amplitudes (0.1 to 3.2 N m), 1,000 trials |
| `tune_inertia.toml` | `learn_combined.py` | tuning round 1, inertia-scaled: both schedules, 5 learning rates (16 to 1,600) by 4 amplitudes (0.25 to 8 rad/s^2), 1,000 trials |
| `tune_concurrent_raw_round2.toml` | `learn_combined.py` | the feedback's round 1 past its edge, raw torque, concurrent: learning rates 250 and 800 by amplitudes 0.1, 0.32, and 1 N m |
| `tune_staged_inertia_round2.toml` | `learn_combined.py` | the feedback's round 1 past its corner, inertia-scaled, staged: learning rates 1,600 to 16,000 by amplitudes 0.025 to 0.25 rad/s^2 |
| `tune_readout_staged_raw.toml` | `learn_combined.py` | the feedforward's round, raw torque, staged, the feedback at 8 and 0.32 N m: 4 forgetting factors (0.99 to 1) by 4 values of `delta` (0.1 to 100) |
| `tune_readout_concurrent_inertia.toml` | `learn_combined.py` | the feedforward's round, inertia-scaled, concurrent, the feedback at 160 and 2.5 rad/s^2: the same grid |
| `tune_staged_inertia_round3.toml` | `learn_combined.py` | the feedback's round 2 past its edge, inertia-scaled, staged: a learning rate of 5,000 with 0.8 rad/s^2 |
| `tune_readout_concurrent_raw.toml` | `learn_combined.py` | the feedforward's round, raw torque, concurrent, the feedback at 80 and 0.32 N m: the same grid |
| `tune_readout_staged_inertia.toml` | `learn_combined.py` | the feedforward's round, inertia-scaled, staged, the feedback at 5,000 and 0.25 rad/s^2: the same grid |
| `tune_concurrent_raw_round4.toml` | `learn_combined.py` | the feedback again, raw torque, concurrent, with the feedforward's new best (0.9999, 100): learning rates 25, 80, and 250 by amplitudes 0.1, 0.32, and 1 N m |
| `tune_concurrent_raw_round5.toml` | `learn_combined.py` | the feedback again, raw torque, concurrent, the feedforward without forgetting (1, 100): learning rates 25, 80, and 250 by amplitudes 0.1, 0.32, and 1 N m |
| `tune_concurrent_inertia_round5.toml` | `learn_combined.py` | the feedback again, inertia-scaled, concurrent, the feedforward without forgetting (1, 10): learning rates 50, 160, and 500 by amplitudes 0.8, 2.5, and 8 rad/s^2 |
| `tune_concurrent_raw_round6.toml` | `learn_combined.py` | round 5 past its edge, raw torque, concurrent: learning rates 25 and 80 by amplitudes 1 and 3.2 N m |
| `tune_concurrent_inertia_round6.toml` | `learn_combined.py` | round 5 past its corner, inertia-scaled, concurrent: learning rates 16 and 50 by amplitudes 0.25, 0.8, and 2.5 rad/s^2 |
| `tune_concurrent_inertia_round7.toml` | `learn_combined.py` | round 6 past its edge, inertia-scaled, concurrent: learning rates 5 and 16 by amplitudes 0.8, 2.5, and 8 rad/s^2 |
| `final_staged_raw.toml` | `learn_combined.py` | the final runs, raw torque, staged: the tuned setting on seeds 1 to 5, 10,000 trials |
| `final_concurrent_inertia.toml` | `learn_combined.py` | the final runs, inertia-scaled, concurrent, the feedforward without forgetting: likewise |
| `final_staged_inertia.toml` | `learn_combined.py` | the final runs, inertia-scaled, staged: likewise |
| `final_feedback_alone_inertia.toml` | `learn_combined.py` | ablation: `final_concurrent_inertia.toml` without its feedforward, seeds 1 to 5 |
| `final_feedforward_alone_inertia.toml` | `learn_combined.py` | ablation: `final_concurrent_inertia.toml` without its feedback, once |
| `final_concurrent_raw.toml` | `learn_combined.py` | the final runs, raw torque, concurrent, the feedforward without forgetting: the tuned setting on seeds 1 to 5, 10,000 trials |
| `final_feedback_alone_raw.toml` | `learn_combined.py` | ablation: `final_concurrent_raw.toml` without its feedforward, seeds 1 to 5 |
| `final_feedforward_alone_raw.toml` | `learn_combined.py` | ablation: `final_concurrent_raw.toml` without its feedback, once |
| `windup_feedforward_alone.toml` | `learn_combined.py` | the wind-up without the feedback: the feedforward alone over report 002's grid, 4 forgetting factors by 4 values of `delta`, 3,000 trials |
| `final_feedforward_alone.toml` | `learn_combined.py` | the feedforward alone at report 002's setting, forgetting at 0.9999: report 002's final run continued, once; it shows the wind-up |
| `compare_raw.toml` | `compare_learning.py` | the final runs for raw torque, both schedules and the ablations, against the decorrelated rule tuned alone for 10,000 trials in `feedback_from_scratch`, the PD alone, and PDs of its grid |
| `compare_inertia.toml` | `compare_learning.py` | likewise, inertia-scaled |
| `compare_feedforward.toml` | `compare_learning.py` | the feedforward alone: report 002's final run, the same continued, and both settings without forgetting |

```bash
uv run python experiments/learn_combined.py experiments/combined_learning/<configuration>.toml --workers 20
uv run python experiments/compare_learning.py experiments/combined_learning/compare_<name>.toml
```

## Runs

Under `results/combined_learning/` in the storage root, all current. Errors are
the noise-free tracking errors, at 1,000 trials on seed 0 for the tuning, and at
10,000 trials on seeds 1 to 5 for the final runs.

| Run | Result |
| --- | --- |
| `20261105-203031-tune_raw` | 37 of 40 settings improve on the PD alone. Concurrent: the closest is a learning rate of 80 with an amplitude of 0.32 N m, 1.62 mm, on the grid's edge, ahead of 25 with 1 N m by 5.5e-8 m; staged: 8 with 0.32 N m, 2.29 mm. Three run away to 577 to 723 mm, raising nothing: 80 with 1 or 3.2 N m concurrent, 80 with 3.2 N m staged. |
| `20261105-204908-tune_inertia` | 26 of 40 improve. Concurrent: the closest is 160 with 2.5 rad/s^2, 1.38 mm; staged: 1,600 with 0.25 rad/s^2, 2.00 mm, in the grid's corner and still falling. The other 14 run away to 649 to 782 mm, raising nothing, at the larger learning rates with the larger amplitudes. |
| `20261105-211104-tune_concurrent_raw_round2` | All 6 run away, to 669 to 764 mm, raising nothing: the learning rate of 80 with 0.32 N m stays the closest, beside learning rates that run away. |
| `20261105-211104-tune_staged_inertia_round2` | 8 of 9 improve. The closest is 5,000 with 0.25 rad/s^2, 1.44 mm, on this grid's edge in amplitude. 16,000 with 0.25 rad/s^2 runs away, to 823 mm. Round 1's best, repeated, comes out bit for bit the same. |
| `20261105-211936-tune_readout_staged_raw` | 12 of 16 improve. The closest is report 002's setting, a forgetting factor of 0.9999 with a `delta` of 10, 2.29 mm, bit for bit round 1's run; next, 0.9999 with 1, 2.63 mm. At 0.99, every `delta` runs away within 10 trials, to 719 mm. |
| `20261105-212835-tune_readout_concurrent_inertia` | 2 of 16 improve: report 002's setting, 1.38 mm, bit for bit round 1's run, and 1 with 10, 2.99 mm. The other `delta` values run away at forgetting factors of 1 and 0.9999, and every one at 0.999, to 602 to 942 mm, raising nothing; at 0.99, rclib raises within 2 trials (`inputs must be finite`). |
| `20261105-213923-tune_staged_inertia_round3` | 5,000 with 0.8 rad/s^2 runs away, to 786 mm: 5,000 with 0.25 rad/s^2 stays the closest. |
| `20261105-213923-tune_readout_concurrent_raw` | 4 of 16 improve. The closest is a forgetting factor of 0.9999 with a `delta` of 100, 1.45 mm, ahead of report 002's setting, 1.62 mm, bit for bit round 1's run; over the evaluations from 800 to 1,000 trials, though, their means are 1.77 and 1.70 mm. 8 run away to 546 to 719 mm; at 0.99, rclib raises. The best is on the grid's edge in `delta`; the grid is not extended, as the protocol's round for the feedforward is report 002's grid, and at 1,000 trials the effect of `delta` is within the swing between evaluations. |
| `20261105-213923-tune_readout_staged_inertia` | 3 of 16 improve. The closest is report 002's setting, 1.44 mm, bit for bit round 2's run; the other 13 run away, to 687 to 816 mm, raising nothing. |
| `20261105-215525-tune_concurrent_raw_round4` | 8 of 9 improve. The closest is a learning rate of 250 with 0.32 N m, 1.00 mm, on the grid's edge (round 2 ran 250 and 800 with the feedforward at 0.9999 and 10: all ran away); 80 with 0.32 N m, 1.45 mm, is bit for bit the feedforward's round. 250 with 1 N m runs away, to 708 mm. Superseded by round 5: the feedforward winds up below a forgetting factor of 1. |
| `20261106-131329-tune_concurrent_raw_round5` | 8 of 9 improve. The closest is a learning rate of 80 with 1 N m, 2.04 mm, on the grid's edge in amplitude, ahead of 25 with 1 N m, 2.05 mm; 80 with 0.32 N m, 2.29 mm, is bit for bit the feedforward's round. 250 with 1 N m runs away, to 647 mm. |
| `20261106-131329-tune_concurrent_inertia_round5` | 5 of 9 improve. The closest is 50 with 0.8 rad/s^2, 2.68 mm, in the grid's corner; 160 with 2.5 rad/s^2, 2.99 mm, is bit for bit the feedforward's round. The learning rate of 500, and 160 with 8 rad/s^2, run away, to 551 to 728 mm. |
| `20261106-132333-tune_concurrent_raw_round6` | 3.2 N m runs away at both learning rates, to 278 and 705 mm; the settings at 1 N m are bit for bit round 5's. A learning rate of 80 with 1 N m, 2.04 mm, stays the closest, now inside the grid. |
| `20261106-132333-tune_concurrent_inertia_round6` | All 6 improve. The closest is a learning rate of 16 with 2.5 rad/s^2, 2.59 mm, ahead of round 5's best, 50 with 0.8 rad/s^2, 2.68 mm, bit for bit round 5's run; 16 is on the edge in learning rate. |
| `20261106-133311-tune_concurrent_inertia_round7` | All 6 improve. A learning rate of 16 with 2.5 rad/s^2, 2.59 mm, stays the closest, now inside the grid, ahead of 5 with 8 rad/s^2 by 1.4e-6 m; the settings at 16 are bit for bit round 6's. |
| `20261106-133440-windup_feedforward_alone` | Every forgetting factor below 1 runs away, every `delta` alike, and stays worse than the PD alone from 16 to 19 trials at 0.99, 160 to 180 at 0.999, and 1,260 to 1,580 at 0.9999: times one minus the forgetting factor, 0.13 to 0.19 across the three. Without forgetting, none does through 3,000 trials: 3.9 to 11.6 mm at 1,000, the closest with a `delta` of 10. |
| `20261105-215525-final_staged_raw` | All 5 improve: 1.47 to 1.63 mm, median 1.54 mm (2.15 mm at 1,000 trials, 1.79 mm at 3,000), still falling. |
| `20261105-215525-final_staged_inertia` | 1 of 5 improves, seed 1, 1.05 mm. Seeds 2 to 4 run away within 200 reaches of the handover, seed 5 at 5,100 reaches, to 702 to 784 mm, raising nothing; the feedforward's weights stand still, frozen since the handover, while the feedback's grow. |
| `20261105-215525-final_concurrent_inertia` | Superseded: run with the feedforward forgetting at 0.9999 and the feedback at 160 with 2.5 rad/s^2, before the protocol's step 1.4. None improves. Seeds 1 and 2 track at 1.2 mm after 1,000 reaches, then run away at 1,580, the feedforward's weights jumping from below 1 to hundreds: they wind up, as the feedforward alone does, at the same reach. Seed 3 runs away at 1,540, from 9.2 mm. Seeds 4 and 5 run away within 200 reaches, long before the feedforward could wind up. All end at 719 mm, the arm against its stops, raising nothing, apart from seed 4, which raises at reach 9,149. |
| `20261105-215525-final_feedback_alone_inertia` | Superseded: the feedback alone at 160 with 2.5 rad/s^2, the concurrent schedule's setting before the protocol's step 1.4. All 5 improve: 5.5 to 8.1 mm, median 6.6 mm (30.6 mm at 1,000 trials, 12.5 mm at 3,000), still falling. |
| `20261105-215525-final_feedforward_alone` | Report 002's final run, continued (run as the concurrent inertia-scaled schedule's ablation, before the protocol's step 1.4), within 2.4e-16 m of it over its 1,000 reaches: 4.58 mm at 1,000 reaches and 4.73 mm at 1,360. Then it winds up: it swings out to 20 and 122 mm at 1,380 and 1,500, and runs away for good at 1,580, to 719 mm, raising nothing; its weights reach 1e17. |
| `20261106-133311-final_concurrent_raw` | 4 of 5 improve: 1.00 to 1.28 mm; the median of all 5, 1.12 mm (1.63 mm at 1,000 trials, 1.30 mm at 3,000). Seed 2 runs away at reach 4, before the feedforward has learned much, swings between 286 and 827 mm, and ends at 286 mm, raising nothing. The feedforward's weights hold below 1.1 on the 4 seeds that improve. |
| `20261106-133311-final_feedback_alone_raw` | 1 of 5 improves, seed 2, 4.17 mm (31.2 mm at 1,000 trials, 6.2 mm at 3,000), still falling. Seeds 1, 3, 4 and 5 run away within 5 reaches and end at 440 to 691 mm, raising nothing; seed 4 comes back to 139 mm once, at reach 3,880. Its learning rate of 80 is 32 times report 001's for raw torque. |
| `20261106-133311-final_feedforward_alone_raw` | 4.65 mm (5.64 mm at 1,000 trials, 4.96 mm at 3,000), still falling slowly. It does not wind up: its weights hold below 0.5. |
| `20261106-134705-final_concurrent_inertia` | All 5 improve: 1.08 to 1.36 mm, median 1.25 mm (2.02 mm at 1,000 trials, 1.50 mm at 3,000), still falling. The feedforward's weights hold below 0.6. |
| `20261106-134705-final_feedback_alone_inertia` | All 5 improve: 21.8 to 26.0 mm, median 24.6 mm (103 mm at 1,000 trials, 58.8 mm at 3,000), still falling: its learning rate of 16 is a tenth of the setting before the protocol's step 1.4. |
| `20261106-134705-final_feedforward_alone_inertia` | 4.47 mm; its closest, 3.74 mm, at 500 trials (3.85 mm at 1,000, 4.19 mm at 3,000), rising slowly. It does not wind up: its weights hold below 0.5. |
| `20261106-151833-compare_raw` | The final runs for raw torque, both schedules and the ablations, against the decorrelated rule tuned alone (median 5.6 mm at 10,000 trials) and the PDs; one of report 003's figures. |
| `20261106-151909-compare_inertia` | Likewise, inertia-scaled (the decorrelated rule tuned alone: median 3.8 mm). |
| `20261106-151834-compare_feedforward` | The feedforward alone: report 002's final run, the same continued until it winds up, and both settings without forgetting. |

## The feedforward's wind-up

The reach moves both joints along the same minimum-jerk profile, so over a reach
the feedforward's seven inputs, `[q_ref, dq_ref, ddq_ref, 1]`, span only four
dimensions: the two reference angles and the constant are affinely dependent, and so
are the two velocities and the two accelerations. Below a forgetting factor of 1, an
RLS readout's covariance grows by the inverse of the factor every period in the
directions no input excites. The reaches before the feedforward runs away scale
with 1/(1 - λ), as wind-up does, in every run that keeps learning: 12 to 20 at
0.99, 160 to 180 at 0.999, and 1,380 to 1,580 at 0.9999, after the covariance has
grown about 1e12-fold in those directions. The feedforward alone, without the
feedback beside it, does the same (`windup_feedforward_alone`). Report 002's and
the tuning's budgets were too short to show it at 0.9999. With a forgetting factor of 1, the covariance
does not grow, and the concurrent schedule's feedforward is tuned again without
forgetting (the protocol's step 1.4). The staged schedule's feedforward stops
learning after 100 reaches.

The tuned settings:

| Variant | Feedback: learning rate, amplitude | Feedforward: forgetting factor, `delta` | Error at 1,000 trials, seed 0 |
| --- | --- | --- | --- |
| raw torque, staged | 8, 0.32 N m | 0.9999, 10 | 2.29 mm |
| raw torque, concurrent | 80, 1 N m | 1, 100 | 2.04 mm |
| inertia-scaled, concurrent | 16, 2.5 rad/s^2 | 1, 10 | 2.59 mm |
| inertia-scaled, staged | 5,000, 0.25 rad/s^2 | 0.9999, 10 | 1.44 mm |

The error swings between evaluations 20 trials apart. After 200 trials, the largest
swing of an improving setting is at most 5.9 mm (raw) and 4.2 mm
(inertia-scaled), at the larger learning rates and amplitudes, and 0.95 mm and
0.18 mm for the median setting. The choice between settings a fraction of a
millimeter apart is then partly chance; the final runs on five other seeds judge
it.
