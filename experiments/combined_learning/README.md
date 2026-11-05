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
      `tune_inertia.toml`);
   2. the feedforward's forgetting factor by its `delta`, report 002's grid, with
      each variant's best feedback setting;
   3. if the feedforward's best setting moved, the feedback's settings again,
      around their best.
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

```bash
uv run python experiments/learn_combined.py experiments/combined_learning/<configuration>.toml --workers 20
```

## Runs

Under `results/combined_learning/` in the storage root. None yet.
