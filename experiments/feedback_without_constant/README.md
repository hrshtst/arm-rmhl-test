# Feedback without its constant

The combined controller of `directional_forgetting`, without the feedback's
constant torque. There, both readouts had a constant input, the feedback's bias
and the feedforward's, so only the sum of their constant torques reached the arm.
With the feedforward forgetting directionally, the split between them drifted.
Inertia-scaled, the feedback's constant on joint 1 grew by 0.6 N m between
reaches 1,000 and 10,000 in median, and the feedforward's bias fell by about as
much. Without its feedback, the controller then lagged 159 mm, nearly the weak
PD's 170 mm; without forgetting, 7.6 mm. Its error also scattered more between
evaluations than without forgetting (report
[004](../../reports/004-directional-forgetting/README.md), Sections 3.3 and 3.5).
Report 004 read the drift as the shared constant's, untested. Without the
feedback's constant, does the feedforward hold the constant torque and work alone
again, and is the tracking as close? This belongs to RQ1 of the
[project README](../../README.md#research-questions).

## Setup

- **Everything but the feedback's constant** is `directional_forgetting`'s final
  runs: the arm, the reach, the weak PD, the feedforward of
  `[q_ref, dq_ref, ddq_ref, 1]` learned by feedback-error learning, forgetting
  directionally, the reward-modulated feedback by the decorrelated `burms2015` rule
  in raw torque or inertia-scaled, the concurrent schedule, the tuned settings, the
  seeds, the budget, the evaluations and the outcomes. A test checks that the
  tables are the same.
- **The feedback has no constant**: `constant = false` in `[feedback]`. Its readout
  has no bias, so its torque is `K_p e_q + K_d e_dq`, times the scale: it gives a
  constant torque only through a steady error, which the reward sees. The recorded
  weights keep their shape, with a zero bias row.
- **Why the feedback's constant, not the feedforward's.** Both joints' reference
  angles follow the same minimum-jerk profile `s(t)`, as
  `q_ref_i = q0_i + (q1_i - q0_i) s(t)`, so a combination of the two is constant.
  Fitted by least squares, the feedforward's six reference inputs give a constant
  to within 7e-15. The feedforward makes a constant torque without its bias, and
  removing that bias would leave the shared direction in place.
- **The settings are not tuned again.** They were tuned with the constant, on
  seed 0. Keeping them changes one thing against `directional_forgetting`'s final
  runs. A setting that suits the feedback without its constant better may exist.
- **The feedforward alone is not run again**: without the feedback, nothing
  changes. `directional_forgetting`'s runs of it serve.

## Protocol

1. **The final runs**: `directional_forgetting`'s two concurrent final runs, raw
   torque and inertia-scaled, without the feedback's constant, on seeds 1 to 5, for
   10,000 reaches.
2. **The comparison**, on the same seeds and budget, against
   `directional_forgetting`'s final runs with the constant and `combined_learning`'s
   without forgetting (report 003), the weak PD alone and the PDs of
   `feedback_from_scratch`'s grid:
   1. the seeds improved, and the median error over the reaches and at 10,000;
   2. the scatter: over the last 1,000 reaches, the median, the 10th and 90th
      percentile and the largest of each seed's 50 evaluations;
   3. the lesions: each controller replayed as learned, without its feedback, and
      without its feedforward;
   4. the constant torque: the feedforward's bias on each joint at 100, 1,000,
      3,000 and 10,000 reaches, against the feedback's constant, the feedforward's
      bias and their sum with the constant;
   5. the feedback's gains, the effort, the peak torque and the torque variation.

   The question is answered by the inertia-scaled runs. Report 004's reading
   predicts that, without the constant, the feedforward's bias holds still, and
   that the controller without its feedback comes back toward the 7.6 mm without
   forgetting from 159 mm. The reading is not supported if the lesion stays near the
   weak PD's, or if the bias still drifts. The raw torque runs are reported beside
   them. Three of their five seeds ran away within 3 reaches with the constant, and
   did so again without forgetting, so they test the feedback's setting more than
   the constant.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `final_concurrent_raw.toml` | `learn_combined.py` | `directional_forgetting`'s final runs for raw torque without the feedback's constant: the feedforward at 0.999 with 100, the feedback at 250 with 0.32 N m; seeds 1 to 5, 10,000 trials |
| `final_concurrent_inertia.toml` | `learn_combined.py` | likewise, inertia-scaled: the feedforward at 0.999 with 10, the feedback at 50 with 8 rad/s^2 |
| `compare_raw.toml` | `compare_learning.py` | the final runs for raw torque, against `directional_forgetting`'s with the constant, `combined_learning`'s with it but without forgetting, the feedforward alone, the PD alone, and PDs of `feedback_from_scratch`'s grid |
| `compare_inertia.toml` | `compare_learning.py` | likewise, inertia-scaled |

```bash
uv run python experiments/learn_combined.py experiments/feedback_without_constant/<configuration>.toml --workers 5
uv run python experiments/compare_learning.py experiments/feedback_without_constant/compare_<scale>.toml
```

## Runs

Under `results/feedback_without_constant/` in the storage root. Errors are the
noise-free tracking errors at 10,000 trials, on seeds 1 to 5.

| Run | Result |
| --- | --- |
| `20261108-074908-final_concurrent_inertia` | 5 of 5 improve, to 0.69 to 0.77 mm; seed 5 too, which ran away by trial 10 with the constant. Without its feedback, each controller lags 8.8 to 12.4 mm, against a median of 159 mm with the constant. The feedforward's bias on joint 1 rises to 0.54 to 0.61 N m and moves by at most 0.04 N m from trial 5,000 on. |
| `20261108-074908-final_concurrent_raw` | 1 of 5 improves, seed 2, to 0.80 mm. The others run away from trials 3 to 7, raising nothing: seeds 1, 3, and 4, which ran away from trials 2 and 3 with the constant, and seed 5, which held with it. Seed 2 had run away from trial 5,740 with the constant. |
| `20261108-084909-compare_raw` | The final runs for raw torque, against `directional_forgetting`'s with the constant, `combined_learning`'s without forgetting, and the feedforward alone; one of report 005's figures. |
| `20261108-084910-compare_inertia` | Likewise, inertia-scaled. |

The comparisons `20261108-084847-compare_raw` and `20261108-084848-compare_inertia`
came first, with longer labels whose panel titles overlapped; they are superseded.
