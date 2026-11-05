# Experiments

An experiment is a set of configurations that answer one question. Each has its
own directory here, holding a README that describes it and its configuration
files. The scripts that run the configurations, the runners, are shared by the
experiments and live directly in this directory.

| Experiment | What it studies | Runners | Report |
| --- | --- | --- | --- |
| [`feedback_from_scratch`](feedback_from_scratch/README.md) | RQ1: feedback torques learned from zero for one reach under a weak PD, against the PD alone over a grid of gains | `pd_grid.py`, `learn_feedback.py`, `compare_learning.py` | [001](../reports/001-feedback-from-scratch/README.md) |
| [`feedback_error_learning`](feedback_error_learning/README.md) | RQ1's supervised baseline: a feedforward learned by feedback-error learning with an RLS readout, for the same reach and weak PD | `learn_feedforward.py`, `compare_learning.py` | [002](../reports/002-feedback-error-learning/README.md) |
| [`combined_learning`](combined_learning/README.md) | RQ1: the feedforward of feedback-error learning and the reward-modulated feedback learned together, with ablations of each, for the same reach and weak PD | `learn_combined.py`, `compare_learning.py` | to come |

The runners:

- `pd_grid.py` tracks the reach with the joint PD alone, for every combination of
  a sweep of its gains;
- `learn_feedback.py` learns feedback torques from one reward per reach, for every
  combination of a sweep, over `--workers` processes;
- `learn_feedforward.py` learns feedforward torques by feedback-error learning,
  from a target every control period, likewise;
- `learn_combined.py` learns both together, the feedforward by feedback-error
  learning and the feedback from one reward per reach, likewise; leaving out
  either learner's table gives the other alone;
- `compare_learning.py` draws the noise-free learning of several runs of
  `learn_feedback.py`, `learn_feedforward.py` or `learn_combined.py`, normally one
  per rule, each over its seeds, against joint PDs of a run of `pd_grid.py`.

A `[sweep]` table lists values for settings of a configuration by their dotted
paths, such as `"rule.learning_rate" = [1.0, 3.0]`; every combination of the
values is run (see `arm_rmhl_test.sweeps`).

Run a configuration with its runner:

```bash
uv run python experiments/<runner>.py experiments/<experiment>/<configuration>.toml
```

## Configuration and reproducibility

Every run is described by a human-readable TOML configuration file. It holds
every parameter that affects the result: the arm, the reach, the command, the
learning rule, the trial budget, and the random seeds.

Every runner starts with `start_run` from `arm_rmhl_test.storage`. It loads the
configuration file and creates a run directory, where the runner then writes its
outputs:

```python
config, run_dir = start_run("experiments/<experiment>/<configuration>.toml")
```

The run directory records how the result was produced:

- `config.toml`: an exact copy of the configuration file, including the random
  seeds;
- `run.toml`: the configuration's path, the command, start time, host name, commit
  hash of this repository, and whether the working tree had uncommitted changes.

```toml
# run.toml
config = "experiments/<experiment>/<configuration>.toml"
command = "experiments/<runner>.py experiments/<experiment>/<configuration>.toml"
started = 2026-11-03 12:04:54+09:00
host = "workstation"
commit = "2d5b5670dba4c5855b2fa31830d923ed00ce5b65"
uncommitted_changes = false
```

The goal is modest: running the same configuration again on the same machine
reproduces the same result. Small numerical differences on other machines or CPUs
are acceptable and are not chased. For this, `arm_rmhl_test` limits rclib to one
OpenMP thread (`OMP_NUM_THREADS=1`, unless you set the variable yourself): a
parallel sum is rounded differently depending on how the work is split among
threads. Reproducing a result does not require checking out its recorded commit.
The commit hash is there to investigate why a reproduced result differs, by
showing what the implementation looked like when the result was produced.

## Data and results storage

Run outputs can grow large, so they live in a storage root, usually outside the
Git repository. The storage root is chosen in this order:

1. the `ARM_RMHL_TEST_STORAGE_ROOT` environment variable, if it is set;
2. otherwise, `storage_root` in `storage.toml` at the repository root, if that
   file exists;
3. otherwise, `storage/` in the repository.

```toml
# storage.toml
storage_root = "/path/to/storage"
```

A relative path is resolved against the repository root. Both `storage.toml`
and `storage/` are specific to one machine, so Git ignores them.

Runs are filed by experiment: a run goes into the directory named after the one
that holds its configuration.

```text
<storage root>/
└── results/
    ├── <experiment>/
    │   └── 20261103-120454-<configuration>/   # one directory per run: <date>-<time>-<configuration name>
    │       ├── config.toml
    │       ├── run.toml
    │       └── ...                             # outputs written by the runner
    └── ...
```

A configuration names the runs it builds on by their paths under the storage
root, such as `run = "results/<experiment>/20261103-120454-<configuration>"`. Run
names begin with the time the run started, so they are unique, and a run is also
found by its name alone, such as `results/<run>`, wherever it is filed.

Git tracks only the results behind a specific report. They are copied into that
report's directory (see [Reports](../README.md#reports)).

## Adding an experiment

1. Make a directory here named after the experiment, with a `README.md` that says
   what it studies, which configurations it has and how to run them, and which
   runs are current.
2. Put its configurations in that directory. Reuse a runner if one fits; add a
   new runner here only for a new kind of run.
3. Add the experiment to the table above.
