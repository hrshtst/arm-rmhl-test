# Plain rule

Does the combined controller's speed depend on the decorrelated rule? Report
[006](../../reports/006-learning-speed/README.md) found that, inertia-scaled, the
combined controller of report
[005](../../reports/005-feedback-without-constant/README.md) passed the levels of
the PDs of 20, 28 and 40 rad/s (12.7, 6.3 and 3.1 mm) after 11, 25 and 99 reaches.
The fastest arm of the feedback alone needed 920 and 2,820, and never passed the
third in 10,000. Every feedback of report 006 learned by the decorrelated rule of
burms2015. This experiment asks the same with the plain rule. This belongs to RQ1 of
the [project README](../../README.md#research-questions).

The two rules differ in one step. Each reach sums an eligibility `E`, the feedback's
input times its exploration noise, over the reach's 200 control periods. The plain
rule changes the weights by `eta (R - R_avg) E`. The decorrelated rule changes them
by `eta (R - R_avg) inv(C + I) E`, where `C` sums the input times its transpose over
the reach, and 1 is rclib's ridge term. Report
[001](../../reports/001-feedback-from-scratch/README.md) tuned both, for the
feedback alone. The plain rule learned more slowly, and at its tuned setting ran
away on 2 (raw torque) and 3 (inertia-scaled) of 5 seeds; the others reached 21 to
24 mm at 3,000 reaches.

`C` shrinks with the tracking error, as the feedback's inputs are the joints'
errors in angle and velocity. Under the weak PD alone, at 170 mm, its largest
eigenvalue over one noise-free reach is about 430. Under PDs that track to 12.7 and
6.3 mm, it is 7.1 and 1.9, and the others are below 0.3. With the feedforward, the
error is that small after tens of reaches, so the ridge term would dominate `C`, and
the decorrelated update would be nearly the plain one at the same learning rate. If
so, the plain rule could serve the combined controller where it failed alone. These
eigenvalues come from noise-free reaches under fixed PDs, not from the learning
reaches.

The questions:

1. **Q1.** Does the combined controller learn faster than the feedback alone with
   the plain rule too?
2. **Q2.** Within the combined controller, how does the plain rule compare with the
   decorrelated one: in reaches to each level, final error, run-aways, exploration
   and tuning cost?
3. **Q3.** On the learning reaches themselves, does `C` fall below the ridge term
   within tens of reaches in the combined controller, and much later in the
   feedback alone?

Predictions, written before the runs:

- **P1.** The plain-rule combined controller passes 12.7 and 6.3 mm about as soon
  as the decorrelated one, as the feedforward alone passes them after 20 and 40
  reaches.
- **P2.** Its tuned learning rate is far above report 001's plain one, 0.15 with
  4 rad/s^2, and nearer the decorrelated combined controller's 50 with 8 rad/s^2.
- **P3.** Where it fails, it runs away within the first tens of reaches, while the
  errors, and so `C`, are large.
- **P4.** In the combined controller, `C` has fallen below 1 in all but one or two
  of its four directions within about 100 reaches; in the feedback alone, only
  after about 1,000.

## Setup

Everything shared is as in the earlier reports: the arm, the reach, the weak PD, the
reward, and the seeds of the final runs, 1 to 5.

Four arms are reused, as run in report 006:

- **Combined, concurrent, decorrelated**: `feedback_without_constant`'s final runs
  (report 005).
- **Feedforward alone**: `directional_forgetting`'s final runs of it (report 004).
- **Feedback alone, decorrelated**: `feedback_from_scratch`'s runs of 10,000 reaches
  (report 001).
- **Feedback alone, decorrelated, without the constant**: `learning_speed`'s final
  runs of it (report 006).

Three arms are new, all with the plain rule. Each changes one thing against an arm
above or below:

- **A. Combined, concurrent, plain**: report 005's combined controller with the
  plain rule. The feedforward's setting is kept, and the feedback has no constant.
  The feedback's learning rate and amplitude are tuned, as the decorrelated rule's
  need not suit the plain one.
- **B. Feedback alone, plain, without the constant**: arm A without its
  feedforward, at arm A's tuned setting. With A, it is the matched ablation, as
  report 006's feedback without the constant was for report 005's controller.
- **C. Feedback alone, plain, at report 001's setting**: report 001's final runs of
  the plain rule, its constant included, continued from 3,000 to 10,000 reaches.
  It is the plain feedback alone at its own tuned setting, in case arm A's does not
  suit it. Its first 3,000 reaches must reproduce report 001's runs.

## Protocol

1. **Tuning arm A**, on seed 0, for its error at 1,000 reaches, as in the earlier
   reports: by hand, in rounds of grids of the learning rate and the amplitude.
   While the closest setting lies on a grid's edge, the next round goes past that
   edge. The setting chosen is the closest at 1,000 reaches over all rounds.
   Round 1 is wide, as the learning rate that suits it is unknown by more than two
   decades. It spans report 001's plain setting up to the decorrelated combined
   controller's:
   - inertia-scaled: 0.15, 0.5, 1.5, 5, 15 and 50 with 2, 4, 8 and 16 rad/s^2;
   - raw torque: 0.25, 0.8, 2.5, 8, 25, 80 and 250 with 0.2, 0.4, 0.8 and 1.6 N m.

   Later rounds are finer, by factors of about 1.4 to 2, around the closest.
2. **The final runs**, on seeds 1 to 5, which the tuning never saw, for 10,000
   reaches: arms A, B and C, raw torque and inertia-scaled. Each is evaluated after
   every reach up to 100 and after every 20th from then on.
3. **The mechanism check**, inertia-scaled: report 005's combined controller and
   report 006's feedback without the constant, both decorrelated, are trained again
   for their first 1,000 reaches on seeds 1 to 5. Every learning reach must
   reproduce the stored error exactly. Each records `C` of each learning reach, and
   its eigenvalues give, reach by reach, how many of its four directions lie above
   the ridge term of 1. A script of report 007 records `C` by wrapping the
   training's functions from outside, so neither rclib nor the package changes.
4. **The comparison**, raw torque and inertia-scaled, as report 006's:
   1. the noise-free tracking error of every arm over the reaches, each seed and
      the median over the seeds, against the weak PD alone and PDs of
      `feedback_from_scratch`'s grid;
   2. the reaches to each level, of the PDs of 20, 28 and 40 rad/s: the first reach
      from which the median over the seeds stays closer than that PD, and the same
      for each seed;
   3. the seeds that improve and those that run away;
   4. the exploration's standard deviation in torque on each joint, against the
      reach's peak torque of 2.2 to 2.7 N m;
   5. the tuning's reaches, counted from the stored runs.

The questions are answered by the inertia-scaled runs. Q1 is answered yes if arm A
passes each level in fewer reaches than arms B and C, and the seeds' ranges do not
overlap; no if B or C passes in about as many reaches. For Q2, the plain and the
decorrelated combined controllers differ at a level only where their seeds' ranges
do not overlap, and likewise for their final errors; their run-aways are compared
seed by seed. The raw-torque runs are reported beside them.

## Configurations

| Configuration | Runner | What it runs |
| --- | --- | --- |
| `tune_combined_inertia.toml`, `tune_combined_raw.toml` | `learn_combined.py` | arm A's feedback, over a grid of learning rates and amplitudes, seed 0, 1,000 trials |
| `tune_combined_inertia_round2.toml` | `learn_combined.py` | round 2: smaller learning rates, around round 1's best amplitude, as its learning rate lay on the grid's edge |
| `tune_combined_raw_round2.toml` | `learn_combined.py` | round 2: smaller amplitudes, around round 1's best learning rate and above it, as its amplitude lay on the grid's edge |

```bash
uv run python experiments/learn_combined.py experiments/plain_rule/tune_combined_<scale>.toml --workers 16
```
