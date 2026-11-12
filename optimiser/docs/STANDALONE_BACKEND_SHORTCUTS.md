# Standalone named-splice shortcuts (patch 104)

`tas.py auto LEVEL NAME`, `tas.py local LEVEL NAME`, and
`tas.py hybrid LEVEL NAME` are **search-backend shortcuts**, not requests to
run the multi-splicer campaign. A configured `multi-splicer.toml` no longer
changes which backend, seed schedule, or iteration budget these commands use.

- **Auto** runs the regular `optimize_replay.py auto INPUT --goal-config NAME.txt`
  endpoint campaign, with its ordinary detailed `[auto:parallel]`,
  `[auto:checkpoint]` and per-worker output. It uses `[auto]` iterations and
  `--auto-runs`, **not** `[multi-splicer] iterations` or `runs`.
- **Local** runs the regular `optimize_replay.py local INPUT --config NAME.txt`
  command. Window search remains window search; population search remains
  population search. Its stagnation settings come from the goal file or
  Local defaults; `TAS_STAGNATION_LOCAL` can explicitly override them.
- **Hybrid/Both** invoke the existing single-goal `hybrid`/`both` command.
  These backends already use the named-stage coordinator internally, but only
  that goal is searchable, and inherited merge/repair/retiming is disabled
  **during** the search.

All standalone searches retain their normal `--output` and `--replay-output`
paths and their original progress text. After the standalone process ends,
Auto/Local population results are independently checked against the named goal;
only a strict improvement is published to `wip/LEVEL_NAME.ltm`, `.txt`, and
`.frontier.json`. This extra publication does not change search seeds or
modify the direct run output. A normal interruption (exit 130) also attempts
to publish the most recently saved direct result. Existing Hybrid/Both
single-goal runs already publish named checkpoints through their own writer.

If the level has a route TOML with `merge-bests`, `merge-retime-gains`, or
`merge-repair-at-end` enabled, a separate merge/repair command runs **after**
standalone search and publication, never before. It may take additional time
and may improve the completed run. Use `--no-propagation` to skip this post-pass
while retaining the saved named checkpoint:

```bash
python3 tas.py auto 87-1 end --auto-runs 100 --no-propagation
```

Note that `tas.py` defaults `TAS_RUNS_AUTO=10`; the direct example with
`--auto-runs 100` is **ten times larger** in total rounds. Pass the same
`--auto-runs`, `--workers`, seed, and other search flags when comparing results.
`tas.py multi LEVEL` is unchanged and still performs full named-stage search,
including its configured startup merging.
