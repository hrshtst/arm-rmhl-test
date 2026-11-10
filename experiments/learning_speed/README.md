# Learning speed

Does the feedforward make the reward-modulated feedback reach a useful tracking
error in fewer reaches than the feedback needs alone? The earlier reports compare
how closely each controller tracks at the end. This experiment asks how soon. A
learner that needs few trials could matter where trials are expensive, such as on
a robot, although this study stays in simulation. This belongs to RQ1 of the
[project README](../../README.md#research-questions).

The stored runs already suggest an answer. Inertia-scaled, the combined controller
of report [005](../../reports/005-feedback-without-constant/README.md) stays closer
than the PDs of 20, 28 and 40 rad/s (12.7, 6.3 and 3.1 mm) from reaches 11, 25 and
99. The feedback tuned alone of report
[001](../../reports/001-feedback-from-scratch/README.md) does so from reaches 1,020
and 3,020, and never for the third, in 10,000. Three things keep this from being a
fair test:

1. Report 001's feedback was tuned for its error at 1,000 reaches. It was never
   tuned to learn fast.
2. Report 001's feedback has a constant torque, and report 005's combined one has
   none.
3. The staged schedule, the feedforward first and the feedback after it, has not
   been run since report 003, without directional forgetting and with the
   constant.

## Setup

Everything shared is as in the earlier reports: the arm, the reach, the weak PD, the
reward, and the seeds of the final runs, 1 to 5.

Three arms are reused, as run:

- **Combined, concurrent**: `feedback_without_constant`'s final runs (report 005).
- **Feedforward alone**: `directional_forgetting`'s final runs of it (report 004),
  at the same setting of the feedforward. It has no noise, so it is one training.
- **Feedback tuned alone**: `feedback_from_scratch`'s runs of 10,000 reaches
  (report 001), the decorrelated rule.

Three arms are new. Each changes one thing against an arm above:

- **Combined, staged**: the combined controller of report 005 on the staged
  schedule. The feedforward learns the first 100 reaches alone and is then frozen,
  and the feedback learns from the rest. The feedforward's setting is kept. The
  feedback's learning rate and amplitude are tuned, since the concurrent schedule's
  need not suit it: in report 003 the two schedules' settings differed widely.
- **Feedback alone, without the constant**: report 001's feedback at its tuned
  setting, without the constant. Inertia-scaled, this setting is also the one of
  report 005's combined controller (a learning rate of 50 with 8 rad/s^2), so the
  feedforward is the only difference. With raw torque the settings differ.
- **Feedback alone, tuned for speed**: report 001's feedback, with the constant,
  tuned for its error at 300 reaches instead of 1,000.

## Protocol

1. **Tuning**, on seed 0, as in the earlier reports: by hand, in rounds.
   1. The staged schedule, for 1,000 reaches: the feedback's learning rate and
      amplitude, for raw torque and inertia-scaled, as in report 003, whose budget
      the concurrent schedule's setting was tuned for.
   2. The feedback alone for speed, for 300 reaches: its learning rate and amplitude,
      around report 001's tuned setting and toward larger values.
2. **The final runs**, on seeds 1 to 5, which the tuning never saw: the staged
   schedule and the feedback without the constant for 10,000 reaches, and the
   feedback tuned for speed for 3,000. Each is evaluated after every reach up to 100
   and after every 20th from then on, as the combined runs were.
3. **The comparison**, for raw torque and inertia-scaled:
   1. the noise-free tracking error of every arm over the reaches, against the weak
      PD alone and the PDs of `feedback_from_scratch`'s grid;
   2. the reaches to each level, of the PDs of 20, 28 and 40 rad/s: the first reach
      from which the median over the seeds stays closer than that PD, and the same
      for each seed;
   3. the seeds that improve and those that run away.

The question is answered by the inertia-scaled runs. It is answered yes if the
combined controller passes each level in fewer reaches than every arm of the
feedback alone, and the seeds' ranges do not overlap. It is answered no if the
feedback tuned for speed passes the levels in about as many reaches. The raw-torque
runs are reported beside them. At report 005's setting, 4 of 5 seeds of the combined
controller ran away, so they test that setting more than the speed.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `tune_staged_inertia.toml`, `tune_staged_raw.toml` | `learn_combined.py` | the staged schedule's feedback, over a grid of learning rates and amplitudes, seed 0, 1,000 trials |
| `tune_feedback_short_inertia.toml`, `tune_feedback_short_raw.toml` | `learn_feedback.py` | the feedback alone for speed, over a grid of learning rates and amplitudes, seed 0, 300 trials |
| `tune_staged_<scale>_round2.toml` | `learn_combined.py` | round 2: larger amplitudes, around round 1's best learning rate, whose amplitude lay on the grid's edge |
| `tune_staged_<scale>_round3.toml` | `learn_combined.py` | round 3: larger amplitudes still, as round 2's best lay on the grid's edge again |
| `tune_feedback_short_inertia_round2.toml` | `learn_feedback.py` | round 2: a finer grid around round 1's best, which is report 001's setting |
| `tune_feedback_short_raw_round2.toml` | `learn_feedback.py` | round 2: larger amplitudes, around round 1's best learning rate, whose amplitude lay on the grid's edge |
| `final_staged_inertia.toml` | `learn_combined.py` | the staged schedule, the feedback at 50 with 32 rad/s^2; seeds 1 to 5, 10,000 trials |
| `final_staged_raw.toml` | `learn_combined.py` | likewise for raw torque, at 16 with 51.2 N m. The amplitude is still on the grid's edge, and the search stops there: it is about 20 times the 2.5 N m peak torque the reach needs |
| `final_feedback_no_constant_<scale>.toml` | `learn_feedback.py` | report 001's feedback alone at its tuned setting, without the constant; seeds 1 to 5, 10,000 trials |
| `final_feedback_short_inertia.toml` | `learn_feedback.py` | the feedback alone tuned for 300 trials, at 35 with 11 rad/s^2; seeds 1 to 5, 3,000 trials |
| `final_feedback_short_raw.toml` | `learn_feedback.py` | likewise for raw torque, at 5 with 6.4 N m |
| `compare_inertia.toml` | `compare_learning.py` | the final runs for inertia-scaled exploration: the combined controller, concurrent (report 005) and staged, the feedforward alone (report 004), and the feedback alone, tuned in report 001, without its constant, and tuned for speed, against the PD alone and PDs of `feedback_from_scratch`'s grid |
| `compare_raw.toml` | `compare_learning.py` | likewise, raw torque |

```bash
uv run python experiments/learn_combined.py experiments/learning_speed/tune_staged_<scale>.toml --workers 24
uv run python experiments/learn_feedback.py experiments/learning_speed/tune_feedback_short_<scale>.toml --workers 24
uv run python experiments/compare_learning.py experiments/learning_speed/compare_<scale>.toml
```
