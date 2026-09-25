# TOML configuration

`optimize_replay.py` accepts defaults from a TOML file selected with
`--config`. The mode and `INPUT` remain positional:

```bash
python optimize_replay.py auto run.txt \
  --config examples/config/highscore.toml \
  --output run_next.txt
```

The effective order is built-in defaults, legacy top-level TOML keys,
`[common]`, the selected mode table, then explicit scalar command-line options.
Repeatable command-line options append as described below.

## Tables and key names

The supported tables are `[common]`, `[auto]`, `[local]`, `[jump-pattern]`,
`[dump-player]` and `[encode-video]`. Underscores may replace hyphens in those
table names, but the two spellings cannot both appear. Non-selected known mode tables may
coexist in one file and are ignored until their mode is selected.

Keys may use argparse destinations (`auto_objective`) or long-option spelling
(`auto-objective`). A mode prefix may be omitted inside its own table, so these
are equivalent inside `[auto]`:

```toml
objective = "highscore"
auto_objective = "highscore"
auto-objective = "highscore"
```

Every applicable root, `[common]` and selected-mode key is validated. Unknown
sections, unknown keys, invalid types and wrong-mode settings are errors rather
than silently ignored. For example, `iterations` requires `search = "population"`
under `[local]`, and `seed` is invalid under `[jump-pattern]`.

## Common paths and LTM options

Video comparison settings belong in `[encode-video]`, for example:

```toml
[encode-video]
secondary_replays = ["other.txt", "third.txt"]
replay_alignment = "exit" # "start" is the default
secondary_colors = ["#3568a8", "#689ec9"] # optional; one per secondary
```

`--secondary-replay` and `--secondary-color` append to their configured lists.
Explicit `--replay-alignment` overrides the scalar default. Paths use the
current working directory, as with other configured paths. See
[video encoding](VIDEO_ENCODING.md#comparing-multiple-replays-v408) for primary
world ownership, mixed input formats, timing and validation.

`input`, `mode` and `config` are reserved for the command line. The main output,
optional packed replay output and v2.70 LTM source options may be configured:

```toml
[common]
workers = 8
simulate_enemies = false
output = "recording_optimised.ltm"
replay_output = "recording_optimised.replay"
levels_file = "external/N v1.4 + NReality levels.txt"
level_id = "00-0"
ltm_postroll = 3
```

`levels_file`, `level_id` and `ltm_postroll` correspond to their hyphenated CLI
options and are valid only when positional `INPUT` ends in `.ltm`. `level_id`
must look like `00-0`. The level options can usually be omitted when the movie
name begins with its level ID, either exactly (`00-0.ltm`) or with a
delimiter-separated label (`00-0_rta.ltm`, `00-0_hs.ltm` and similar names),
and the database can be discovered. Version 3.21 ignores old optimiser JSON
and never embeds level data; these rules apply to later passes too. Explicit
`levels_file` selects the database. Automatic database lookup
also checks `external/N v1.4 + NReality levels.txt` below both the current
working directory and its parent, along with the other documented LTM-relative
and optimiser-relative locations.

For an LTM, the default replay boundary removes every trailing row with no
Left, Right or Left Shift input. In Auto mode, those finite inferred rows are
also simulated before the source is declared incomplete, so a route may coast
or fall into the exit after its final held input. This also supports a route
whose whole post-Space movie is N-neutral. A successful completion is cropped
to the canonical neutral-sentinel boundary before retiming, range validation
and search; no neutral rows beyond those recorded in the movie are invented.

Set `ltm_postroll = N` to treat exactly the final `N` active-input rows as
padding instead: `0` keeps every row after the first Space frame. `N` must be
non-negative, must leave at least one replay row, and the excluded rows are
preserved unchanged even if they contain input. This explicit boundary remains
authoritative in Auto and is not probed. Use the override on later passes too
when the exact boundary is needed; output movies do not embed a tick count.

An LTM input requires an `.ltm` main output. A combined text input requires a
text main output and cannot create a movie without an LTM template. All TOML
paths are interpreted relative to the process working directory, not to the
configuration file.

Common options genuinely apply to every selected mode. Do not put Auto-only
values in `[common]` if the same file must also work with Local or jump-pattern.

## Mode examples

```toml
[common]
workers = 8
retime = ["whole:-1", "120:+1"]

[auto]
objective = "highscore"
parents = ["parent-b.ltm", "parent-c.ltm"]
runs = 0
stagnation_runs = 20
checkpoint = "/mnt/nv14-checkpoints/campaign.json"
resume = true
iterations = 10000
beam = 64
beam_repair_revisit_limit = 2
splice_repair_revisit_limit = 3
splice_plans_per_pair = 2
auxiliary_beam_seeds = 1
seed = "random"
require_reference_gold = true

[local]
target_frame = 300
range = ["90:105", "250:280"]
objective = "min-distance"
target_object = "exit:0.door"
window = 6
window_shape = "mixed"
require_interaction = ["gold:0", "exit:0.switch"]
avoid_interaction = ["trapdoor:any"]
python_resimulate = false

[jump-pattern]
target_frame = 300
range = "220:300"
jumps = [2, 3]
jump_length = [1, 8]
fixed_jump_frames = [242, 273]
python_resimulate = false
```

Auto accepts one inclusive mutation seam/start range. For example,
`range = "100:"` in `[auto]` (CLI `--range "100:"`) starts at frame 100
and follows the end of each current verified replay or highscore search
workspace. An omitted end stays open through initial trimming, different
starting parents, later rounds and checkpoint resume; surrounding whitespace
is accepted. `"0:"` and `":"` cover the whole current workspace. This is
fixed in v4.20; earlier CLI versions froze an omitted end at the original
input length. Numeric endpoints such as `"100:200"` remain fixed, and the
start and any explicit end must fit the verified workspace. The completion
sentinel is not editable. As before, the range bounds mutation seams/starts;
suffix edits can affect later frames.

For population search, select `search = "population"` in `[local]` and
use `iterations`, `beam`, `rounds`, `stagnation_rounds`, `checkpoint` and
`resume` there. Position/velocity windows, diverse outputs and earliest-arrival/earliest-interaction
examples are documented in [Local population search](LOCAL_POPULATION.md).
Do not combine explicit window-only controls such as `window`, `passes` or
`restarts` with that strategy. The ready-to-edit configurations are
`examples/config/local-population.toml`, `examples/config/local-arrival.toml`
`examples/config/local-interaction.toml` and `examples/config/local-jump-region.toml`.

In v4.28, population searches accept `require_jump_region` as
`"XMIN:XMAX,YMIN:YMAX"` or `[XMIN, XMAX, YMIN, YMAX]`. It requires a real
`Player.jump()` originating inside the inclusive rectangle by the endpoint.
Optional `require_jump_frames` is `"START:END"` or `[START, END]`, with bounded,
zero-based, inclusive indices. It defaults to the first editable frame through
`target_frame`, independently of `arrival_start`, and requires a jump region.
Both options work with every population objective and are rejected for other
search strategies. See [the detailed semantics](LOCAL_POPULATION.md#required-intermediate-jump).

In v4.21, `objective = "earliest-interaction"` reuses `target_object`, for
example `target_object = "switch:0"` or `"gold:any"`. The deadline remains
`target_frame`; `arrival_start` defaults to the first editable frame. Selectors
support gold, exit switches, locked-door switches, trapdoor triggers and exit
completion (`exit:0.door`). A fresh event must occur in the eligible interval,
with every constraint satisfied on that same tick. An interaction consumed
earlier does not qualify later. This objective requires population search and
rejects `target_point` and `target_region`.

In v3.15, `[local].secondary_objective` (CLI `--secondary-objective`) optionally
breaks earliest-arrival frame ties (also earliest-interaction in v4.21) using `"max-x"`, `"min-x"`, `"max-y"`,
`"min-y"`, `"max-vx"`, `"min-vx"`, `"max-vy"` or `"min-vy"`.
It requires `search = "population"` and
`objective = "earliest-arrival"` or `"earliest-interaction"`; omit it to retain the original edit-count
tie-break. The signed value is measured at the first qualifying endpoint frame.
Primary arrival time always takes precedence, and secondary gains at tied
arrival time reset `stagnation_rounds`. CLI values override TOML as usual.
`min-*` prefers smaller signed values and `max-*` prefers larger ones;
`min-vx` favours leftward velocity and `min-vy` favours upward velocity.

`runs = 0` makes an Auto campaign indefinite until Ctrl+C. Set a positive
value or override it on the CLI for a bounded run.

`stagnation_runs = N` corresponds to `--auto-stagnation-runs N` and stops the
campaign normally after `N` consecutive fully completed rounds without a
significant gain. An objective-level improvement always resets the counter. At
the same objective, exit distance must improve by at least `0.5` px relative to
the immediately preceding committed round checkpoint; a smaller global-best
gain remains durable but increments the counter. `0` is the default and
disables this limit; when both a positive run count and a positive stagnation
limit are configured, the first one reached ends the campaign.

`checkpoint = "FILE"` corresponds to `--auto-checkpoint FILE` and atomically
saves the full campaign after each completed worker/splice/population round.
`resume = true` corresponds to `--auto-resume`: a compatible existing file is
restored, while a missing file starts a new campaign. Put the file on durable
storage when using spot instances. Resume requires the same optimiser build,
input and parent replays, level, resolved seed, worker count, run limit,
stagnation limit and complete Auto configuration, and canonically re-emulates
every survivor. The consecutive stagnant-round count is restored, so a
checkpoint already at the limit exits without starting another round. With
`seed = "random"`, an existing checkpoint's resolved seed is restored before
configuration validation.

`parents` supplies additional generation-0 Auto replays and corresponds to the
repeatable `--auto-parent FILE` option. Explicit CLI parents append to this
array. The positional input remains required and is not part of the array: it
owns the output template, reported baseline and reference-gold mask. All
parents must contain exactly the same serialized level. Auto applies the same
configured `retime` sequence to each, canonically verifies and trims every
replay through the zero-iteration path, collapses canonical duplicates, ranks
the unique founders under the selected objective, and divides round-one worker
searches evenly between them.

`beam_repair_revisit_limit` and `splice_repair_revisit_limit` are positive
per-campaign limits on visits to the same eight-frame failure region. Their CLI
forms are `--auto-beam-repair-revisit-limit` and
`--auto-splice-repair-revisit-limit`. Splice repair has no separate total
attempt limit; it continues within `campaign_local_steps` and the normal
progress, replay-deduplication and editable-region stopping conditions.
Junction splices may additionally search fresh callable jump insertions or
retriggers, coherent input-transition retimes and short held-direction
intervals farther before the observed failure. The enabled families share one
effective per-repair allowance without a fixed candidate slice, roll unused
simulation work forward, and compare their proposals against the same repair
target. This strategic tier uses the configured `range`, `repair_window`,
`repair_lookback`, `lookahead`, `max_retime`, `repair_local_steps`,
`campaign_local_steps`, `frame_ahead_repair_multiplier` and splice revisit
limit; it has no strategic-patch-count or separate total-attempt ceiling. A
zero local or campaign limit keeps its existing unlimited meaning.

`splice_plans_per_pair` (also accepted as the argparse-style
`auto_splice_plans_per_pair`) corresponds to
`--auto-splice-plans-per-pair`. It is a positive maximum on all ranked plans
attempted for each ordered recipient/donor pair and defaults to `2`. At most
one slot may be a prospective short junction; raw hybrid simulation must
validate it against a stable recipient suffix before repair begins. All
remaining selected slots are normal corridor plans.
Raising the value can reach known productive but lower-ranked corridor sections
without widening the donor population or admitting additional junctions, but
can proportionally increase raw-splice and repair work for every pair.

`auxiliary_beam_seeds` (also accepted as `auto_auxiliary_beam_seeds`)
corresponds to `--auto-auxiliary-beam-seeds`. It defaults to `1` and bounds the
promising rejected splice-repair candidates carried from all ordinary and
junction pairs for each exact surviving recipient. The recipient's first child
re-simulates those frame-only candidates as normal macro evaluations and keeps
them reserved in its beam until each has been sampled once. Their recorded
stable suffix is revalidated against the child's recipient rather than trusted
across a process or checkpoint boundary. The effective count is
`min(auxiliary_beam_seeds, beam - 1)`, preserving at least one ordinary beam
slot. Set it to `0` to disable carrying rejected splice frontiers. Increasing
it raises only bounded next-child simulation and beam occupancy; existing
splice repair limits continue to govern candidate discovery.

`python_resimulate` is a Local/jump-pattern diagnostic and defaults to `false`.
The normal path adapts native terminal snapshots directly and verifies packed
output with the independent native engine. Setting it to `true` replays every
returned native result and packed output through the Python reference emulator
and requires exact parity. It is not valid in `[auto]`; Auto already evaluates
its candidates and finalists natively.

## Arrays, repeatable options and precedence

TOML arrays are used for repeatable `parents`, `retime`,
`require_interaction` and `avoid_interaction`. Repeating the corresponding CLI
option appends to the configured list rather than replacing it.

Local also accepts a string array for disparate mutable frame ranges, as above.
The CLI equivalent is `--range 90:105,250:280`. Overlapping or adjacent
intervals are coalesced; contiguous windows do not cross excluded gaps, while
sparse windows draw from the union. Auto and jump-pattern accept only one
continuous interval. A CLI `--range` is scalar and replaces a configured Local
range array.

Structured CLI values may remain strings or use convenient TOML arrays:

```toml
[local]
target_point = [470.0, 432.0]
x_window = [0.0, 500.0]
immutable_jumps = ["42:both", "73:start"]

[jump-pattern]
jumps = [2, 3]
jump_length = [1, 8]
fixed_jump_frames = [42, 73]
```

TOML has no null value. Use strings for open-ended values, for example
`x_window = ":500"` or `jump_length = "1:"`. `workers` is either the string
`"auto"` or a positive integer; numeric zero is not accepted.

For store-false command-line switches, the positive destination name is often
the clearest TOML form:

```toml
[auto]
deterministic = false
all_input_repair = false
require_reference_gold = true
```

## Typed mode configuration

After command-line and TOML defaults are merged, values are materialised into
typed configuration objects. `auto` uses frozen `AutoConfig`; `local` uses
`LocalConfig`; and `jump-pattern` uses `JumpPatternConfig`. Mode-specific
cross-field rules are validated before search begins. Shared source values,
including `levels_file_path`, `level_id` and `ltm_postroll`, are held by
`CommonConfig`.

The public parser remains compatible with callers expecting an
`argparse.Namespace`. Its `_mode_configs` attribute contains the resulting
`ModeConfigs` bundle. Programmatic callers with an existing parsed namespace
can use `build_mode_configs(namespace)`. Search algorithm function signatures
remain backward compatible. `optimise_autonomous_campaign()` accepts optional
keyword-only `parent_frames=()` for additional founders and
`checkpoint_path`, `resume` and `level_identifier` for durable campaign state;
Local and jump-pattern retain the optional keyword-only
`python_resimulate=False` diagnostic control.

See the README's complete option reference for every supported key and default.
