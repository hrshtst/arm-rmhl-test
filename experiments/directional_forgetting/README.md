# Directional forgetting

The feedforward of `combined_learning` again, with its RLS readout forgetting
directionally. Forgetting exponentially below a forgetting factor of 1, the readout
winds up: the reach excites four of its seven input directions, and in the other
three its covariance grows every control period, until the feedforward stays worse
than the weak PD alone from 0.13 to 0.19 / (1 - λ) reaches on (report
[003](../../reports/003-combined-learning/README.md), Section 3.2). So the
concurrent schedule's final runs did without forgetting, although at 1,000 reaches
it had tuned to closer tracking with it, 1.00 mm against 2.04 mm with raw torque
and 1.38 mm against 2.59 mm inertia-scaled. rclib's RLS readout now also forgets
directionally, only along each period's input, so the unexcited directions keep
their information. Does that remove the wind-up? And with forgetting safe, does
the concurrent schedule track more closely than without it, on the same seeds and
budget? This belongs to RQ1 of the [project README](../../README.md#research-questions).

## Setup

- **Everything but the forgetting method** is `combined_learning`'s: the arm, the
  reach, the weak PD, the feedforward of `[q_ref, dq_ref, ddq_ref, 1]` learned by
  feedback-error learning, the reward-modulated feedback of `[e_q, e_dq, 1]` by the
  decorrelated `burms2015` rule in raw torque or inertia-scaled, the concurrent
  schedule, the evaluations and the outcomes. A test checks that the tables are the
  same.
- **The feedforward forgets directionally**: `forgetting_method = "directional"` in
  `[readout]` (rclib's `readouts.Rls`). Each period it discounts the share
  1 - λ of the readout's information along that period's input, then adds the
  period's sample. At a forgetting factor of 1 nothing is forgotten, and it is the
  same update as before.
- **The staged schedule is not run again**: its feedforward stops learning after
  100 reaches, long before it could wind up.

## Protocol

1. **The wind-up**, without the feedback: the feedforward alone over report 002's
   grid, its forgetting factor (1, 0.9999, 0.999, 0.99) by its `delta` (0.1, 1, 10,
   100), for 3,000 reaches, against `combined_learning`'s run of the same grid
   forgetting exponentially; and at report 002's setting, 0.9999 with 10, for
   10,000 reaches, against the same setting forgetting exponentially, which ran
   away. The rows at a forgetting factor of 1 should repeat `combined_learning`'s
   bit for bit.
2. **Tuning**, on seed 0 for 1,000 reaches, as in `combined_learning`, chosen by the
   lowest noise-free error at 1,000 reaches over all rounds, for each feedback
   scale, the concurrent schedule only:
   1. the feedforward's forgetting factor by its `delta`, report 002's grid, with
      the feedback at its best before `combined_learning`'s step 1.4, the last
      setting tuned with the feedforward forgetting: raw torque, a learning rate of
      250 with 0.32 N m; inertia-scaled, 160 with 2.5 rad/s^2
      (`tune_readout_concurrent_<scale>.toml`);
   2. if the feedforward's best setting moved from the one the feedback was tuned
      with (0.9999 with 100 raw, 0.9999 with 10 inertia-scaled), the feedback's
      learning rate by its amplitude around its best, and again past the grid's edge
      until no best lies on it (`tune_concurrent_<scale>_round<n>.toml`).
3. **The final runs**, on seeds 1 to 5, which the tuning never saw, for 10,000
   reaches: each scale at its tuned setting, and the feedforward alone at each
   tuned feedforward setting, once, having no noise.
4. **The comparison** against `combined_learning`'s concurrent final runs without
   forgetting, its superseded ones forgetting exponentially at report 002's
   setting, the weak PD alone and the PDs of the grid: tracking error over the
   reaches, effort, peak torque, torque variation, and lesions.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `windup_feedforward_alone.toml` | `learn_combined.py` | the wind-up without the feedback: the feedforward alone over report 002's grid, 4 forgetting factors by 4 values of `delta`, 3,000 trials |
| `continued_feedforward_alone.toml` | `learn_combined.py` | the feedforward alone at report 002's setting, 0.9999 with 10, 10,000 trials, once |
| `tune_readout_concurrent_raw.toml` | `learn_combined.py` | the feedforward's round, raw torque, the feedback at 250 and 0.32 N m: report 002's grid, 1,000 trials on seed 0 |
| `tune_readout_concurrent_inertia.toml` | `learn_combined.py` | the feedforward's round, inertia-scaled, the feedback at 160 and 2.5 rad/s^2: the same grid |
| `tune_concurrent_raw_round2.toml` | `learn_combined.py` | the feedback again, raw torque, with the feedforward's new best (0.999, 100): learning rates 80, 250, and 800 by amplitudes 0.1, 0.32, and 1 N m |
| `tune_concurrent_inertia_round2.toml` | `learn_combined.py` | the feedback again, inertia-scaled, with the feedforward's new best (0.999, 10): learning rates 50, 160, and 500 by amplitudes 0.8, 2.5, and 8 rad/s^2 |

```bash
uv run python experiments/learn_combined.py experiments/directional_forgetting/<configuration>.toml --workers 16
```

## Runs

Under `results/directional_forgetting/` in the storage root. Errors are the
noise-free tracking errors, at 1,000 trials on seed 0 for the tuning, and at 10,000
trials on seeds 1 to 5 for the final runs.

| Run | Result |
| --- | --- |
| `20261107-201945-tune_readout_concurrent_raw` | 4 of 16 improve, all with a `delta` of 100. The closest is a forgetting factor of 0.999, 1.07 mm (0.77 mm at 600 trials), ahead of 0.99, 1.38 mm, 0.9999, 1.89 mm, and 1, 2.27 mm, which is bit for bit `combined_learning`'s round 5 at this feedback setting. The 12 with a `delta` of 10 or less run away, to 516 to 712 mm, at every forgetting factor, raising nothing. The best is on the grid's edge in `delta`; the grid is not extended, as in `combined_learning`. |
| `20261107-201946-tune_readout_concurrent_inertia` | 4 of 16 improve. The closest is a forgetting factor of 0.999 with a `delta` of 10, 1.61 mm (1.10 mm at 660 trials), ahead of 0.99 with 100, 1.94 mm, 0.9999 with 10, 2.36 mm, and 1 with 10, 2.99 mm. The rows at a forgetting factor of 1 are bit for bit `combined_learning`'s round. The other 12 run away, to 484 to 942 mm, raising nothing; at 0.99, forgetting exponentially, rclib raised within 2 trials. |
