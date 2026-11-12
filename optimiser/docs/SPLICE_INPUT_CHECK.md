# Read-only named-splice feasibility checking

From `optimiser/`:

```sh
python3 tas.py check 91-2          # every primary and alternate-route goal
python3 tas.py check 91-2 442      # one goal, including without multi-splicer.toml
```

The underlying optimiser also accepts `check` directly. If no
`--splice-config` is provided, it discovers
`../splices/LEVEL/multi-splicer.toml` relative to the LTM input:

```sh
python3 optimize_replay.py check ../n_levels/91-2.ltm
python3 optimize_replay.py check ../n_levels/91-2.ltm 442
```

Or through the existing `auto` argument parser:

```sh
python3 optimize_replay.py auto ../n_levels/91-2.ltm \
  --splice-config ../splices/91-2/multi-splicer.toml --check-splices
python3 optimize_replay.py auto ../n_levels/91-2.ltm \
  --splice-config ../splices/91-2/multi-splicer.toml \
  --check-splices --check-splice 442
```

The command reads **only the positional input replay** and the named goal files.
It does not load saved best checkpoints, merge, repair, retime, search, or write
output files. For each named goal it uses the same native endpoint evaluator,
constraints and per-stage `simulate-enemies` policy used by the multi-splicer.
When a replay ends before the target-frame, its implied neutral inputs are
materialised for the check (just as for normal endpoint search). A checkpoint
can be feasible even if the replay dies later. Named goals are independent;
not reaching an earlier helper does not automatically invalidate a later one.

Output prints `[check:feasible]` or `[check:infeasible]` for each stage followed
by `[check:summary]` with a feasible/total count. Exit code 0 means all checked
goals are feasible; exit code 1 means at least one failed. Missing/invalid goals
or configuration are command errors. With a single named goal, a
`multi-splicer.toml` file is not required; its `.txt` or `.toml` goal file is.
