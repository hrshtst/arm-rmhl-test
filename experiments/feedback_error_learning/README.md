# Feedback-error learning

A supervised baseline for [`feedback_from_scratch`](../feedback_from_scratch/README.md).
Given a target torque every control period instead of one reward per reach, how
fast and how close does an online learner bring the weak PD's reach to its
reference? How do its result, effort, and torque compare with the reward-modulated
feedback of report [001](../../reports/001-feedback-from-scratch/README.md) and
with joint PDs of a grid? This belongs to RQ1 of the
[project README](../../README.md#research-questions).

## Setup

- **The arm, the reach, and the weak PD** are those of `feedback_from_scratch`: a
  test checks that the tables are the same.
- **The feedforward** comes from rclib's recursive least squares (RLS) readout,
  every 10 ms, from the reference `[q_ref, dq_ref, ddq_ref]` at the start of the
  period and a constant 1. It starts at zero weights and adds to the PD's torque;
  both are held over the period. The readout is linear, so its weights are a
  torque per reference angle, velocity, and acceleration, and a constant.
- **The learning** is feedback-error learning (Kawato et al., 1987). Every control
  period of a reach, the readout fits, as its target, its own output plus the weak
  PD's torque: the feedback controller's torque is the error of the feedforward.
  It learns within the reach, and there is no noise and no reward.
- **The readout's settings** are RLS's forgetting factor and `delta`, its initial
  regularization: the covariance starts at the identity over `delta`.

Learning is judged as in `feedback_from_scratch`: by a reach that learns nothing,
with the weights as they stand, after every trial; the score is the same tracking
error. The outcome at the end is `improved` or `worse` than the PD alone, or
`diverged` when rclib or skelarm raised.

What differs from `feedback_from_scratch`, besides the learning signal: the
readout sees the reference, not the tracking error, so it learns a feedforward
for this reach rather than feedback; and nothing is random, so each setting is one
training, with no seeds.

## Protocol

1. **Tuning.** `tune.toml` runs the forgetting factor (1, 0.9999, 0.999, 0.99) by
   `delta` (0.1, 1, 10, 100) for 100 reaches each.
2. **The final run.** The tuned setting is the one with the lowest error at 100
   reaches. It runs for 1,000 reaches, to show whether it stays there: the
   reference holds still for the last second of each reach, which can wind up an
   RLS covariance that forgets. There is no held-out check like the seeds of
   `feedback_from_scratch`: the tuning and the final run are the same task.
3. **The comparison.** The final run against the decorrelated rule's runs of
   10,000 trials in `feedback_from_scratch`, the PD alone, and PDs of its grid, in
   tracking error over the trials, effort, peak torque, and torque variation.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `tune.toml` | `learn_feedforward.py` | tuning: 4 forgetting factors (0.99 to 1) by 4 values of `delta` (0.1 to 100), 100 trials |

```bash
uv run python experiments/learn_feedforward.py experiments/feedback_error_learning/<configuration>.toml --workers 16
```

## Runs

Under `results/feedback_error_learning/` in the storage root. None yet.
