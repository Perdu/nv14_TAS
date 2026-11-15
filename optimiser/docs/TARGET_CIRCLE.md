# Circular earliest-arrival splice goals

A population splice with `objective = "earliest-arrival"` can use a circular
arrival area instead of `target_region`. The circle is centred on player
**position** `(x,y)` and includes the boundary, using Euclidean distance.

```toml
[local]
search = "population"
target_frame = 442
objective = "earliest-arrival"
target_circle = "305,237,12"  # x, y, radius
```

Omit the radius to use 10 pixels:

```toml
target_circle = "305,237"
```

TOML arrays, such as `target_circle = [305, 237, 12]`, also work. The CLI
accepts `--target-circle 305,237,12` for Local population and endpoint Auto.
`--goal-config` imports the same condition into Auto, Hybrid and named splice
searches, including multi-splicer and `check`.

Use **exactly one** of `target_region` and `target_circle` for earliest-arrival.
Radius must be a positive finite number. Other constraints, such as interaction
requirements, enemy simulation and the arrival frame window, still apply.
The native scanner checks a real circle, not its bounding box.

**Native rebuild required after applying this patch:**

```bash
python3 build_native.py --force-cython --force
```
