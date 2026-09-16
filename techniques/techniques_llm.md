# N v1.4 TAS techniques — compact LLM reference

This is a TAS-search reference. **Never lower a technique because it is hard for a human, RTA-rare, subpixel, frame-perfect, or TAS-only.** Precision only changes the search method (targeted state/coordinate search vs broad enumeration).

## Legend / notation

Each technique uses four fixed fields:

- `M` — **mechanics**: simulator behavior that makes the technique work.
- `S` — **search rule**: states/geometry the TAS solver should generate or target, plus true feasibility constraints. Precision or RTA difficulty is never a negative factor by itself.
- `G` — **gain**: possible instantaneous velocity/vector or angle effect. This is not the same as guaranteed time saved; validate candidates by replay to the next objective/exit.
- `E` — **example**: `demo-key@frame` or `demo-key@start-end`. Frames are **0-based input ticks**. A range means the technique spans several ticks. If no frame is shown, the demo is known but the exact tick was not verified. Full raw demo strings are in the **Demo data** appendix of this document.

Math/state notation:

- Coordinates: `+x` right, `+y` down. Upward velocity is therefore negative `vy`.
- `v=(vx,vy)=pos-oldpos`: implicit per-tick velocity.
- `C=(cx,cy)`: collision/depenetration correction applied to `pos`; unless later logic resets a component, this also contributes `Δv=C`.
- `Δv`: instantaneous change to implicit velocity.
- `n=(nx,ny)`: collision/floor normal.
- `h`: horizontal input (`-1`, `0`, `+1`).
- `r`: ninja collision radius.
- `jump(jx,jy)`: simulator jump transform described below.
- Angles are described relative to the horizontal when useful; “upward” means toward negative `y`.
- `1f`: one frame/tick. `BB`: bounceblock. `LP`: launchpad. `WJ`: walljump. `CJ`: corner jump. `RCJ`: reverse corner jump. `PJ`: perpendicular/reverse slope jump. `BWJ`: backwards walljump. `BBBWJ`: bounceblock backwards walljump. `BBCD`/`BBCT`: bounceblock corner double/triple.
- Demo suffixes: `SR` = the `Speedrun` entry in `level_data.yml`; `HS` = the `Highscore` entry. These labels identify which stored demo is being referenced; they do **not** imply human execution or change TAS search priority.
- Example `14-4-SR@354` = use the `14-4-SR` raw demo below and inspect input tick 354 for the referenced interaction.

## Global solver model

- Coordinates: +x right, +y down. `v=(pos-oldpos)`. A collision correction `C` applied to `pos` therefore immediately adds `C` to implicit velocity.
- Candidate value: rank by **reachable/surviving feasibility + possible route-time gain**. A narrow valid state interval is not negative evidence if it can be targeted exactly. Computational branching may justify a more directed optimizer, not suppressing the technique.
- Jump transform: for `jump(jx,jy)`, first set `vx=0` if `vx*jx<0` and `vy=0` if `vy*jy<0`; then `vx+=jx`, `vy+=3*jy`. This reset/accumulate rule is essential for RCJ/PJ, repeated BB jumps, chimney jumps, and LP+WJ.
- Ground jump selection: if `h*floor_n.x < 0`, call `jump(0,-0.7)` => `(0,-2.1)` term; otherwise call `jump(floor_n.x,floor_n.y)` => `(nx,3ny)`. **Neutral `h=0` takes the normal/surface branch.**
- World collision: any single correction with magnitude `>sqrt(0.8)*r≈8.944 px` kills. Object correction has no generic size kill test, but objects can have their own death rules.
- `G` is instantaneous speed/vector capability, not guaranteed time save. Always score by replay to the next objective/exit.
- `E` frame pointers are hints for locating a demonstrated state, not claims that the same technique must occur on the same relative tick in another route.

## 1. Depenetration

`M` Collision resolution translates `pos` without translating `oldpos`; therefore each correction `C=(cx,cy)` is added to implicit velocity. World corrections with `|C|>sqrt(0.8)*r≈8.944` kill; object corrections do not use that generic size test.

`S` Generate at corners/slopes/moving objects whenever a reachable, surviving correction points usefully toward the next objective. Reject only if collision is unreachable/lethal or replay proves the detour costs more than the boost.

`G` `Δv=C`; direction=`C`; angle change is whatever follows from `v'=v+C`.

`E` `49-2-SR@358`. Raw demo: see **Demo data** appendix.

## 2. Walljump

`M` Airborne `near_wall` + jump trigger calls `jump(wall_n.x*1.5,-0.7)` normally. If already `WALLSLIDING` and pressing away, it uses `jump(wall_n.x*1.0,-0.5)`.

`S` Enumerate at every useful wall contact, including one-frame contacts. Sustained wallslide is only useful if its positioning benefit exceeds friction loss.

`G` Normal added jump displacement `(±1.5,-2.1)`, 54.46° above horizontal; reduced `(±1,-1.5)`, 56.31°. Component reset rules in the global jump equation apply.

`E` `01-4-SR@21`. Raw demo: see **Demo data** appendix.

## 3. Stumble

`M` A one-frame floor contact cannot immediately ground-jump: landing from `FALLING/JUMPING` first changes state to `RUNNING/SKIDDING` and returns; the contact may disappear next tick. The collision correction still modifies velocity.

`S` Allow/seek one-frame contacts when their correction/path is faster than avoiding the surface. Do not treat a stumble itself as a failure state.

`G` No fixed impulse beyond collision correction: `Δv=C`. A non-slowing stumble can preserve tangent speed while changing position/normal component.

`E` `49-2-SR@358`. Raw demo: see **Demo data** appendix.

## 4. Corner jump (CJ)

`M` After a corner/angled floor contact has survived long enough to reach a ground state, a normal ground jump uses `jump(nx,ny)`. Actual added displacement is `(nx,3ny)` because of the +2 y-bias.

`S` Enumerate exposed corners whenever their normal can improve path, x-speed, y-speed, or launch angle. Two consecutive floor-contact ticks are normally required from an airborne approach.

`G` Before reset rules, added vector `J=(nx,3ny)`. For a 45° normal: `(±0.707,-2.121)`, added-vector angle 71.57° above horizontal.

`E` `03-2-SR@223`. Raw demo: see **Demo data** appendix.

## 5. Reverse corner jump (RCJ)

`M` A reverse CJ is a corner-normal jump used to reverse horizontal travel. Neutral input or input with `h*nx>=0` selects `jump(nx,ny)`; if incoming `vx*nx<0`, `jump()` erases inherited x velocity before adding `nx`, producing the reversal. Continuing with `h*nx<0` would instead select the pure-vertical branch.

`S` Target corner normals opposite incoming `vx` when an immediate direction reversal/route change is valuable. Precision is not a penalty; solve the contact coordinates directly.

`G` If `vx*nx<0`, post-jump x becomes `vx'=nx` (plus later physics), i.e. angle can change across 90° instantly. y follows the normal-jump equation, usually `vy'=3ny` when landing while falling.

`E` `05-4-SR@551`. Raw demo: see **Demo data** appendix.

## 6. Perpendicular/reverse slope jump (PJ)

`M` On a slope, releasing horizontal input (`h=0`) or pressing so `h*nx>=0` selects the surface-normal jump `jump(nx,ny)`. Holding the direction with `h*nx<0` selects the special `jump(0,-0.7)` branch instead. Because y is multiplied by 3, the actual movement vector is y-biased rather than exactly geometrically perpendicular.

`S` Try when the slope normal gives a better x direction/angle than the pure-vertical branch, especially when it can reverse x or create a strong diagonal launch.

`G` Normal branch adds `(nx,3ny)` with component resets. For a 45° slope normal: `(±0.707,-2.121)`; if it opposes incoming x, x is reset then becomes `nx`.

`E` `08-2-SR@86`. Raw demo: see **Demo data** appendix.

## 7. Corner kick (CK)

`M` A CJ reached from a falling approach. First contact converts `FALLING` to a ground state; the next valid contact can jump. Large approach/depenetration effects can make the resulting launch unusually horizontal/fast.

`S` Search falling trajectories into corners when the two-contact sequence is reachable and surviving. High incoming fall speed is useful when collision correction redirects it without triggering the world-correction or impact death tests.

`G` `v` first receives corner correction(s), then the CJ jump transform. Horizontal speed may exceed normal running speed through correction + same-direction `nx`; vertical fall speed is usually reset by upward `ny` before the jump term.

`E` `17-2-SR@702`. Raw demo: see **Demo data** appendix.

## 8. Bounceblock backward walljump (BBBWJ)

`M` Bounceblock collision resolves along the shallow axis: ninja receives `0.2*penetration`, block receives `0.8*penetration`. A side correction sets `near_wall`, allowing an immediate walljump. High/low/side BBBWJ are setup geometries, not different physics.

`S` Enumerate **high, low, and side** contacts whenever a bounceblock side is reachable and the resulting walljump/correction helps the route. Do not lower side-BBBWJ value because its valid coordinate interval is narrow; use targeted coordinate/phase search.

`G` Same-frame effect is `C_bb + WJ`, where `C_bb=0.2*penetration` on one axis and WJ is usually `(±1.5,-2.1)`. Subsequent block spring motion can add further corrections. Exact outgoing angle uses the summed vector and inherited velocity.

`E` `90-0-SR@50 (high)`; `00-0-SR@54 (low)`; `14-4-SR@354 (side)`. Raw demo: see **Demo data** appendix.

## 9. Thwump BWJ

`M` A side thwump collision applies the full overlap correction to the ninja and sets a wall normal; jumping that tick adds a walljump. Thwump movement can make the correction much larger than a bounceblock correction. Leading-side crush logic can kill.

`S` Search every reachable thwump phase where a surviving side correction + WJ points usefully. Exact phase precision is a search-targeting issue, not a reason to suppress the technique.

`G` `v'` receives full thwump correction `C` then WJ. Example `06-4@302` has a large left correction immediately before the walljump, yielding far more x-speed than WJ alone.

`E` `06-4-SR@302`. Raw demo: see **Demo data** appendix.

## 10. Thwump push

`M` Same thwump correction mechanism without jumping.

`S` Search when the thwump can push directly toward the next target or create a better later interaction. Reject crushing/route-worsening phases only.

`G` `Δv=C_thwump` on the resolved axis; no fixed jump term. Multiple successive corrections can compound.

`E` `17-1-SR@399-401`. Raw demo: see **Demo data** appendix.

## 11. Clipping through one-ways

`M` One-way collision is directional. Corners, downward depenetration, bounceblocks, thwumps, or rare floating-point boundary states can move the ninja to the nominally blocked side without a conventional allowed crossing.

`S` Whenever crossing the one-way backwards removes route length, test reachable geometry/object depenetrations and exact boundary states. Do not discount a solution because it is RTA-impractical; only simulator feasibility and route gain matter.

`G` No intrinsic impulse: movement gain is the enabling correction/push; strategic gain is route reachability/shorter path.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 12. Multiple bounceblock jumps

`M` Repeated contact with a moving/returning bounceblock can create new jumpable contacts. When already moving upward, another upward jump does **not** reset `vy`; its y term accumulates, which is why repeated jumps can build extreme vertical speed. Repeated side contacts can similarly chain walljumps.

`S` Enumerate repeated contacts while the block remains reachable. Use targeted timing/phase search rather than limiting count because of human difficulty; stop only when another jump cannot improve the route or is physically unreachable.

`G` Top normal jump can add `-3` to already-negative `vy` each accepted jump; side walljumps can add another `-2.1` and `±1.5` each, plus BB corrections. Four-jump sequences are present in the corpus.

`E` `10-2-SR@81-89`. Raw demo: see **Demo data** appendix.

## 13. Bounceblock corner double (BBCD)

`M` A top bounceblock jump sequence followed by a side BBBWJ exit, combining vertical accumulation with a horizontal walljump.

`S` Search when one block can replace separate height-building and redirection steps.

`G` Top jump(s) can add `-3` to existing upward `vy`; side exit adds BB correction + WJ `(±1.5,-2.1)`.

`E` `19-1-SR@211-219`. Raw demo: see **Demo data** appendix.

## 14. Bounceblock corner triple (BBCT)

`M` BBCD with one additional accepted top jump before the side BBBWJ exit.

`S` Search whenever the extra top jump remains reachable and additional height/upward speed improves the route. Narrow timing is not a negative by itself.

`G` Relative to BBCD, one more normal top jump can contribute another `-3` to already-upward `vy`, then the side WJ contributes its usual vector.

`E` `33-2-SR@694,698,703`. Raw demo: see **Demo data** appendix.

## 15. Chimney jumps

`M` In a narrow shaft, alternating `near_wall` contacts allow walljumps every ~2 ticks. With `vy<0`, each new walljump y term accumulates rather than resetting, rapidly increasing upward speed.

`S` Detect narrow two-wall corridors and enumerate alternating jump triggers at the shortest reachable cadence. Feasibility limits are wall reach, lethal world correction, and crush/geometry—not human execution.

`G` Each normal WJ can add `-2.1` to already-negative `vy` and flip/add `±1.5` x. `02-4@35-51` grows from about `vy=-4.5` to `-18.2`.

`E` `02-4-SR@35-51`. Raw demo: see **Demo data** appendix.

## 16. Corner shove

`M` Entering a wall/ceiling corner can produce downward world corrections after/around a jump, converting upward motion into downward displacement/velocity.

`S` Search only when downward speed or a faster drop is route-positive; exact corner timing is acceptable if reachable.

`G` Variable `C`, principally positive `Δvy` (down). No fixed jump-specific gain; angle is set by summed corrections and any jump term.

`E` `11-1-SR@93-102`. Raw demo: see **Demo data** appendix.

## 17. Corner pushes

`M` Use collision correction without necessarily jumping. Common cases: upward bump while moving along a ledge/corner; downward corner push/ledge grab; falling bounce with large correction.

`S` Enumerate natural corner grazes and intentional impacts where correction points toward the next objective. Bounces deserve targeted search when high fall speed can convert to useful horizontal/vertical speed while surviving.

`G` `Δv=C`. Direction follows the resolved contact normal; magnitude is penetration correction, bounded for each world correction by the ~8.944 px death threshold.

`E` `17-3-SR@379`. Raw demo: see **Demo data** appendix.

## 18. Getting squeezed

`M` Two opposing/converging contacts in one tick can apply multiple corrections; moving objects (especially thwumps) can repeatedly force penetration, producing large summed velocity changes.

`S` Search moving-object/geometry pinch states whenever the escape vector helps. Evaluate exact simulator survival; do not reject merely because the state is precise.

`G` `Δv=sum(C_i)` before any later jump transform. Individual world corrections can kill if >8.944 px; thwumps have separate crush logic. `88-4@658-661` demonstrates opposing thwump/world corrections.

`E` `88-4-SR@658-661`. Raw demo: see **Demo data** appendix.

## 19. Launchpad + walljump (LP+WJ)

`M` Launchpad `launch()` resets both velocity components, then sets `v=(nx*s, ny*s*yFactor)`, `s=5.142857`; upward pads use `yFactor=2`. A walljump on the same tick/next available wall contact can then add its jump vector; because upward `vy` is already negative, WJ y normally accumulates.

`S` Whenever an LP trajectory intersects a wall immediately, test same-tick/earliest walljump variants and both useful wall normals.

`G` Upward LP alone: `(0,-10.285714)`. Same-tick normal WJ gives about `(±1.5,-12.385714)`, added-vector trajectory ~83.09° above horizontal. Other pad orientations use the exact launch vector formula.

`E` `00-0-HS@26`. Raw demo: see **Demo data** appendix.

## 20. Angled LP+WJ

`M` Same composition as LP+WJ for non-axis pad normals or geometry that preserves/adds a strong x component.

`S` Enumerate when LP orientation + wall normal can reinforce the desired route vector instead of cancelling it.

`G` `v_after_launch=(nx*s, ny*s*(1+|ny| if ny<0 else 1))`, then apply WJ jump transform. Example 45° pad launch is about `(-3.6365,-6.2080)` before WJ.

`E` `29-1-SR@276`; `29-1-SR@29 (axis LP, angled result via wall)`. Raw demo: see **Demo data** appendix.

## 21. 1-frame wallslide

`M` The tick that changes state into `WALLSLIDING` returns before wall friction is applied. Friction is applied only if a later tick begins/stays wallsliding while not pressing away.

`S` Use single-tick wallslide states for alignment, ledge/corner control, or object interaction when keeping downward speed is useful.

`G` No fixed positive impulse. Benefit is preserving `vy` that a continued wallslide would reduce by `0.13*|vy|` on each friction tick; collision corrections still apply normally.

`E` `73-1-SR`. Raw demo: see **Demo data** appendix.

## 22. Taking only one stacked object

`M` Object/static collider processing is ordered and hitboxes need not coincide exactly. A one-tick trajectory can intersect/remove one stacked object without intersecting or triggering the other.

`S` Enumerate when stacked gold/switch/door/trapdoor objects have different desired states and selective contact shortens the route.

`G` No direct movement impulse; route/state gain only. Any speed change comes from the chosen trajectory, not collection itself.

`E` `00-1-SR`. Raw demo: see **Demo data** appendix.

## 23. Clipping

`M` At sufficiently large per-tick displacement, discrete collision tests can skip thin geometry/objects because the path between old and new positions is not continuously swept.

`S` Whenever current or attainable speed can cross an obstacle thickness in one tick and bypassing it saves route length, explicitly test clip trajectories. Human impracticality/novelty is irrelevant; require only simulator validity and useful exit state.

`G` No intrinsic impulse; it preserves the incoming high velocity while changing reachability. Potential route gain can be large, but feasibility is strongly geometry/speed dependent.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 24. Backwards walljump (BWJ)

`M` Walljump eligibility depends on `near_wall`, not facing. The fallback wall probe samples `r+0.1`, so a jump can be accepted while the ninja is already moving/turning away from the wall or has not visually penetrated it.

`S` At every close wall pass, test jump triggers across the whole valid ~0.1 px probe band, including states moving away from the wall. Use direct subpixel targeting; do not penalize narrow windows.

`G` Same WJ transform. If incoming `vx` and WJ x have opposite signs, x is reset then becomes `±1.5`; if same sign, `±1.5` accumulates. Angle may therefore reverse sharply or flatten.

`E` `07-2-SR`. Raw demo: see **Demo data** appendix.

## 25. Slope jump: neutral/opposite-input behavior

`M` For any ground normal with `nx!=0`: `h*nx<0` selects `jump(0,-0.7)`; `h=0` selects normal `jump(nx,ny)`. Thus a neutral tick is a distinct useful action and is **not** the same as the pure-vertical branch.

`S` For every slope/corner jump candidate, enumerate `h=-1,0,+1` on the trigger tick; do not collapse neutral with either held direction.

`G` Vertical branch adds `(0,-2.1)`; neutral/normal branch adds `(nx,3ny)`, with jump component-reset rules. Compare resulting route angle by simulation.

`E` `08-2-SR@30 (vertical branch)`; `08-2-SR@86 (normal/reverse branch)`. Raw demo: see **Demo data** appendix.

## 26. Walljump optimization

`M` `near_wall` fallback probes at `r+0.1`, so the ninja may be up to ~0.1 px from a solid wall and still walljump.

`S` For every route-relevant walljump, locally optimize the pre-jump x position across the valid probe interval; this is cheap once the route contains the jump.

`G` Up to ~0.1 px positional gain normal to the wall; WJ velocity vector itself is unchanged. This can convert to one frame at a later threshold.

`E` `07-2-SR`. Raw demo: see **Demo data** appendix.

## 27. Jumping through launchpad / LP walljump

`M` A wall probe can expose `near_wall` while a launchpad does not launch: LP activation requires radial overlap **and** its normal-side test `along_normal>=0`. This permits walljumping on the wall behind/through a pad without accepting the pad's velocity reset.

`S` **Always generate this candidate when a vertical-surface launchpad is mounted against/near a wall and blocks the desired line.** Search the wall-probe band and the LP backside/edge states (`along_normal<0` or no overlap). Also use it whenever bypassing any LP preserves a superior incoming trajectory.

`G` Successful case gets the normal WJ transform while preserving incoming velocity subject to jump reset rules; avoided LP would otherwise replace velocity with its fixed launch vector. Therefore gain can be much larger than the WJ vector alone. In `65-4@202`, the ninja walljumps beside the LP without any launch event.

`E` `65-4-SR@202`; `65-4-SR@238`. Raw demo: see **Demo data** appendix.

## 28. Exit-door hitbox optimization

`M` Completion occurs on circle overlap; with player radius 10 and exit radius 12, first-contact time depends on approach vector, so a jump/height adjustment can touch the 22 px combined radius earlier than center-to-center routing.

`S` At the final approach, enumerate nearby jump/no-jump timing and approach height/angle; score by earliest completion tick.

`G` No intrinsic speed gain; geometric reach is up to the hitbox-radius advantage along the chosen approach direction. Optimize completion frame directly rather than a fixed velocity target.

`E` `00-0-SR`. Raw demo: see **Demo data** appendix.

## 29. Jumping to maximize horizontal travel

`M` Ground/air use different acceleration and ground state transitions can add skid/stand/surface losses. The net advantage is sequence-dependent; there is no single constant 'air speed bonus' in the simulator.

`S` On long horizontal segments, enumerate jump timing against pure running and keep the trajectory with earlier arrival at the next required interaction. Include landing setup in the objective.

`G` No fixed `Δv`; compare simulated arrival. Angle cost is the vertical excursion needed to preserve/improve x progress.

`E` `00-0-SR`. Raw demo: see **Demo data** appendix.

## 30. Turnaround optimization

`M` At ledges, acceleration, skid friction (`vx*=0.92` in skidding), and the exact tick floor contact disappears determine the outgoing fall vector.

`S` Enumerate short input sequences around every route-critical reversal/ledge rather than using a fixed turnaround template.

`G` Per ground-control tick, attempted accel is ±0.15 while eligible; skid ticks scale x by 0.92. Gain is a better outgoing `(vx,vy)`/edge position, not a special impulse.

`E` `19-0-SR`. Raw demo: see **Demo data** appendix.

## 31. Stuttering to stay grounded

`M` Short alternating/neutral inputs can change running/skidding transitions enough to retain a marginal floor contact for another tick.

`S` Generate only where the simulator shows near-loss of floor contact and one extra grounded tick enables a better jump/acceleration state. Precision is fine; the prerequisite is a marginal contact.

`G` No fixed boost; trades x-control for retaining `floor_n`/ground-jump eligibility.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 32. Angled CJ on downward-facing corners

`M` Some downward-facing corner geometry can still report a floor normal (`ny<0`) for the player on a specific contact. If so, ordinary CJ rules apply; otherwise it is only wall/depenetration contact.

`S` Enumerate when such a corner lies on/near a useful line and exact collision classification yields `ny<0` for two needed contact ticks.

`G` Same as CJ: correction(s) + jump `(nx,3ny)` with reset rules; angle from the resulting vector.

`E` `17-3-SR`. Raw demo: see **Demo data** appendix.

## 33. 1f wallslides to push bounceblocks without slowing

`M` A bounceblock side contact can both move the block and set `WALLSLIDING`; alternating/away input on the next tick exits before wall friction. This lets the solver repeatedly reposition a block while preserving fall speed better than sustained wallslide.

`S` Search when BB phase/position matters for a later jump or squeeze. The valid sequence may be exact; target it rather than suppressing it.

`G` Each BB contact gives ninja `0.2*penetration` and block `0.8*penetration`; avoided wall-friction preserves up to `0.13*|vy|` per would-be friction tick. `73-1@193-197` alternates 1f wallslides while pushing the block.

`E` `73-1-SR@193-197`. Raw demo: see **Demo data** appendix.

## 34. Delaying drone detection

`M` Think/visibility work is staggered by the object manager. Interactions that alter manager scheduling can shift which tick a drone performs its visibility update.

`S` When enemy timing blocks a faster route, test nearby object interactions that perturb scheduling; evaluate whether detection/shot timing moves enough to keep the faster movement line.

`G` No direct `(vx,vy)` gain. Benefit is temporal enemy-state change that permits a faster route.

`E` `19-1-SR@0-30`. Raw demo: see **Demo data** appendix.

## 35. Locked-door walljump

`M` The supplied technique is an exact walljump from a locked-door side. Treat it as a wall-contact feasibility problem in the door/edge-override collision model.

`S` Whenever a locked door face lies on a materially shorter line, target the exact wall-probe/contact states and test a WJ. Do not down-rank because it is TAS-only; down-rank only if the simulator cannot reproduce it or route gain is negligible.

`G` If accepted, normal WJ transform `(±1.5,-2.1)` (or reduced branch) plus any door-related correction. No current TAS-corpus example identified.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 36. NaN-corrupted rockets

`M` A rocket state can become NaN under special conditions described in the source notes. This is not a finite movement primitive; emulator/simulator fidelity must be established before route search can trust it.

`S` Enable when a level contains a relevant homing rocket **and** a regression reproduces the original-game NaN behavior. Precision is not the reason to exclude it; unverified simulation fidelity is.

`G` Ordinary speed/angle metrics are undefined once relevant state is non-finite. Evaluate only by reproducible downstream game state/time.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 37. Half-tile airjump

`M` At the exact positive-x endpoint of a compatible vertical-normal half tile, projection can report wall normal `(0,0)`. `ny==0` marks `near_wall`, so an airborne jump executes `jump(0,-0.7)` and gives a pure vertical airjump without correction.

`S` Whenever an exposed compatible half-tile endpoint is reachable and an airjump can remove meaningful route length, target the exact coordinate directly. Float-perfect precision is not a priority penalty.

`G` Jump term `(0,-2.1)`; x is preserved because `jx=0`; added-vector angle 90° upward. No current TAS-corpus example identified.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 38. Pause glitch

`M` Known pause/input aliasing exists, but the supplied notes found no reproducible useful pause-buffer/jump-every-frame movement exploit.

`S` Do not spend TAS search on it unless new evidence establishes a movement/state advantage; this exclusion is based on zero demonstrated gain, not execution difficulty.

`G` No verified movement gain.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 39. Tile walljump

`M` Ordinary WJ where a tiny exposed tile feature satisfies the `r+0.1` wall probe/contact instead of a full wall.

`S` Enumerate all small exposed wall faces near useful trajectories. Narrow geometry is a reason for targeted coordinate search, not lower technique value.

`G` Same WJ transform `(±1.5,-2.1)` normally, plus inherited velocity/corrections.

`E` `06-2-SR`. Raw demo: see **Demo data** appendix.

## 40. Tile reverse corner jump

`M` No special simulator branch: this is RCJ/CJ behavior on a small angled tile feature. Exact contact geometry determines `floor_n`; neutral/aligned input gets normal jump, `h*nx<0` gets vertical branch.

`S` Fold into generic corner-contact search over small/angled tiles; if the feature creates a route-improving normal, target the exact contact state.

`G` Normal branch `(nx,3ny)` with resets; vertical branch `(0,-2.1)`. No confirmed current TAS example from the supplied notes.

`E` No confirmed example in the current TAS corpus identified from the supplied technique notes.

## 41. Angled walljumps on downward-facing corners

`M` When the ninja moves past an exposed lower/downward-facing tile corner, collision can resolve as a large horizontal world correction `C=(Cx,0)` and set `wall_n=(s,0)`, where `s=sign(Cx)`. A same-tick WJ uses `jump(1.5s,-0.7)`. Let `vx_preWJ` be x velocity after the correction. If `vx_preWJ*s>=0`, the WJ does not reset x, so the depenetration boost and `±1.5` WJ term stack; otherwise x resets and the boost is lost.

`S` For every exposed lower corner crossed while airborne, especially while ascending, search exact position/input states that produce a surviving horizontal correction in the desired WJ direction and trigger jump on that tick. This is particularly valuable in fast upward chains where an ordinary WJ would leave only `|vx|=1.5`. Reject only if the contact is unreachable/lethal or the resulting direction/route is worse.

`G` Compounding case: `vx_out=vx_preCollision+Cx+1.5s`; while already ascending, `vy_out=vy_preWJ-2.1`. A pure-x world correction survives while `|Cx|<=sqrt(0.8)*r≈8.944`, so the geometry-limited horizontal correction + WJ contribution can approach `10.444 px/tick` before other constraints. Outgoing angle is `atan2(|vy_out|,|vx_out|)`. In `13-3-SR@424`, `Cx=-4.0328`, pre-WJ `v=(-2.7569,-7.5327)`, and out `v=(-4.2569,-9.6327)`: `66.16°` above horizontal, versus `81.15°` at the same `vy` with conventional `|vx|=1.5`.

`E` `13-3-SR@424`. Raw demo: see **Demo data** appendix.

## Search policy summary

Generate technique candidates from local geometry/object state rather than a human-risk priority list. High potential-gain exact states (side BBBWJ, downward-corner angled WJ, thwump boosts/squeezes, clips, locked-door WJ, half-tile airjump, LP bypass) deserve targeted searches whenever their prerequisites exist. Only suppress a technique when its prerequisite geometry/object is absent, exact simulation proves it unreachable/dead, fidelity is unverified for that glitch, or its best reachable result is slower than the competing route.

# Demo data

Raw `demo` fields copied from the supplied `level_data.yml`. Each string is stored once and keyed exactly as used by `E`. Embedded map names/authors are part of the original demo serialization; no separate name/author metadata is required by this reference.

## 49-2-SR

```text
$49-2 deceptive#metanet##00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000011111111000000000000000001000010000000000000000010000100000000000000010111101000000000000000100000010000000000000001000010100000000000000010100101000000000000000101000010000000000000001010000100000000000000010111101000000000000000101000010000000000000001010000100000000000000010100101000000000000000101111010000000000000001000000100000000000000010000001000000000000000101111010000000000000001010010100000000000000010100101000000000000000101001010000000000000000010000100000000000000000100001000000000000000111111110000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000|5^540,36!11^396,36,564,144!0^180,180!0^156,180!0^156,156!0^180,156!0^180,132!0^156,132!0^168,144!0^168,168!0^168,192!4^252,210,1!6^444,84,0,0,0,2!6^252,156,0,0,0,0!6^108,228,0,0,0,3!2^768,276,-1,0!2^24,276,1,0!2^24,324,1,0!2^24,372,1,0!2^24,420,1,0!2^24,468,1,0!2^24,516,1,0!2^24,564,1,0!2^768,324,-1,0!2^768,372,-1,0!2^768,420,-1,0!2^768,468,-1,0!2^768,516,-1,0!2^768,564,-1,0!0^720,228!0^720,204!0^720,180!0^720,156!0^720,132!0^720,108!0^720,84!0^720,60!0^72,228!0^72,204!0^72,180!0^72,156!0^72,132!0^72,108!0^72,84!0^72,60!12^24,36!12^768,36!12^768,204!12^24,204!12^24,96!12^24,144!12^768,96!12^768,144!0^420,156!0^420,132!0^396,132!0^372,132!0^372,156!0^396,156!0^408,144!0^384,144!6^372,180,1,0,0,3!6^588,252,1,0,0,0#492:35791394|35791394|35791394|35791394|35791394|17896226|17895697|17895697|17895697|17895697|17895697|89480465|17895697|273|33694240|35791394|35791394|35791394|35791394|35791394|35791394|237117986|40265318|17895697|17895697|17895697|4369|35791394|219222306|89478485|17913173|17895697|35787025|35791394|107880994|40265318|35791394|17830434|17895697|17895697|17895697|17895697|17895697|17895697|17895697|33554449|35791394|107882094|107374182|89478470|89474388|89478485|17896789|17895697|17895697|17895697|89478493|89478485|97587473|18175317|114364689|237397606|107374182|40265318|35791394|35791394|35791394|107374306|107374182|107374182|226#
```

## 01-4-SR

```text
$01-4 steps#metanet##0001110000000000000000000011140000000000000000000:1114000000000000000000011114000000000000000000011114000000000000000000:1111400000000000000000011111400000000000000000011111400000000000000000:1111140000000000000000011111140000000000000000011111140000000000000000:1111114000000000000000011111114000000000000000011111114000000000000000:11111118;000000000000001111111110000000000000001111111100000<000000000:11111110000010000000000111111100000=0000000000011111100000000000000000:1111100000000000000000011111000000000000000000011110000000000000000000:1110000000000000000000011100000000000000000000011000000000000000000000:10000000000000000000000180000100010001000100000000000000000000000000000000000000000000000000000|5^732,564!11^36,84,60,252!9^468,60,0,0,28,23,1,0,0!0^108,108!0^180,156!0^252,204!0^324,252!0^396,300!0^468,348!0^540,396!0^612,444!0^684,492!2^216,576,0,-1!2^24,408,0.707106781186547,-0.707106781186547!6^36,564,1,0,0,0!6^756,36,5,1,0,2!2^204,324,-0.707106781186547,-0.707106781186547!0^708,180!0^708,156!0^708,276!0^708,252!0^708,348!0^708,372!0^672,564!0^660,564!0^648,564!0^636,564!0^612,564!0^624,564!0^600,564!0^588,564!0^576,564!0^564,564!0^552,564!0^540,564!0^528,564!0^516,564!0^492,564!0^504,564!0^480,564!0^468,564!0^456,564!0^444,564!0^432,564!0^420,564!0^396,564!0^408,564!0^384,564!0^372,564!0^360,564!0^348,564!0^336,564!0^636,468!0^564,420!0^492,372!0^420,324!0^348,276!0^276,228!0^204,180!0^132,132#824:17895697|17895697|30478609|107374190|107374182|107374182|89478610|89478485|107374305|107374182|107374182|97609318|89478485|89478485|89478485|89478469|89478485|89478485|18175317|17895697|2237201|35791394|35791394|35794466|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35652130|17965602|17895697|17895697|17895697|17895697|17895697|89478493|89478485|89478485|89478485|17896789|17895697|17895697|17895697|89478493|89478485|89478485|89478485|89478485|22369621|17895697|17895697|34672913|2236962|35791394|35791394|17965602|17895697|17895697|17895697|1118481|0|0|0|0|35840512|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|107405858|40265318|35791394|35791394|35791394|107374190|107374182|36071014|35791394|35791394|35791394|107405858|97674854|89478485|22369621|17895697|17895697|17895697|17961233|89478493|89478485|72701649|17895765|17895697|17895697|89510161|89478485|89478485|89478485|89986389|89478485|22369621|17895697|17895697|17895697|69905#
```

## 03-2-SR

```text
$03-2 rise over run#metanet##90000000000000000061906000000000000000000710000011@000000000100015000000>D0000000002400000000000B@000000000240000000000>D0000000000240000000000B@000000000024000000000>1100001400002100000000000000061000000000000000000000010000000000010000000007100000000000100000100015000000000002400001LH000000000000000240000FJLH000000000000002400000FJLH000000100000021100000FJLH0000E0000000000000000FJ1000P0000000000000000001000P0000000000000000000000P000000100000000000000?A000000100000310014000N000000?E00003500002400N000000CA00035000000100C00000?E000150000000000E00000CA000000000000000P0000?E0000000000000000P0000CA000000000000000?A0000100000000GK100000N000001000000GKMI000000N0000000000GKMI00000000N00080000001I0000000000C807|5^36,540!11^708,564,756,180!9^300,300,0,0,15,23,1,-1,0!2^252,336,0,-1!2^444,432,0,-1!2^564,252,-0.707106781186547,-0.707106781186547!3^396,444!3^684,108!3^108,84!0^132,120!0^156,132!0^180,144!0^204,156!0^324,72!0^348,96!0^372,120!0^396,144!0^528,132!0^552,120!0^576,108!0^600,96!0^624,84!0^648,72!0^672,60!0^588,204!0^516,372!0^324,204!0^300,204!0^300,60!0^276,60!0^696,60!0^732,204!0^720,228!0^708,252!0^696,276!0^684,300!0^672,324!0^588,564!0^564,564!0^540,564!0^516,564!0^492,564!0^564,420!0^204,300!0^84,348!0^120,372!0^144,396!0^168,420!0^192,444!0^216,468!0^84,444!0^84,60!0^372,516!0^396,516!0^420,516!0^504,504!0^576,492!0^672,480#503:219222289|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|107306530|107365990|107882084|107374182|88431910|124151125|18175317|17895441|89478493|89478485|89478485|89480469|107373909|107374182|89548390|40334678|139810|35791392|35791394|35791362|35791394|237109794|35791462|115483170|107374182|107365990|36071014|35791394|34742818|2236962|33694240|139810|17895696|17830161|17895697|18944273|16847410|17895697|16847121|17895697|17895697|17891601|17895697|17895697|17895697|36700433|35791394|35790882|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791586|107374306|107374182|107374182|35792486|35791392|12722722#
```

## 05-4-SR

```text
$05-4 castle/basement#metanet##00000000000100001000011000000001001000010000110000000011110111100000000000100000100000001000000001111001000000010000000010000010000000100000111100100111111111110000101001001000000000000000010010010000000000000010100100100111111100000101001001001111111000001010000010000000000000010111100100000000000000001000001011111111110001010010010000000010000010100100100000000100000101001001001100001000111010010010001000110000010100100100010000000000101001001000100000000001010010011111111111000000100000100000000000000101111001000000000000011110000010000000000000000100110100001101100000001001001000010001000000011110010000100010000000100100100001000100000000001111000011111000000000000010000000000000000000000000000000000|5^36,36!9^636,204,1,0,1,9,1,0,-1!9^60,276,0,0,25,19,1,-1,0!9^348,96,1,0,14,4,0,0,-1!9^540,96,1,0,22,4,0,0,-1!9^228,96,1,0,9,4,0,0,-1!9^540,240,1,0,22,9,0,0,0!9^348,240,1,0,14,9,0,0,0!9^300,240,1,0,12,9,0,0,0!9^156,240,1,0,6,9,0,0,0!9^756,348,1,1,31,12,0,0,0!11^60,396,612,132!6^156,132,0,1,0,3!6^564,252,1,1,0,0!6^252,348,0,0,1,0!2^372,504,0,-1!12^444,48!12^444,480!12^420,360!12^84,576!12^108,288!6^636,444,0,0,1,0!9^684,492,1,0,6,16,1,0,0!9^492,372,1,0,5,16,1,0,0!9^204,324,1,0,4,16,1,0,0!4^156,474,1!4^492,378,1!4^348,138,1!9^252,204,1,0,24,9,1,0,0!0^660,492!0^636,492!0^684,468!0^684,444!0^396,204!0^420,204!0^444,204!0^468,204!0^492,204!0^612,204!0^612,180!0^636,180!0^684,204!0^684,180!0^708,204!0^564,132!0^204,132!0^492,132!0^468,132!0^264,132!0^288,132!0^444,132!0^468,84!0^228,204!0^204,204!0^60,252!0^36,276!0^324,468!0^324,492!0^324,516!0^204,492!0^204,516!0^204,540!0^372,444!0^372,420!0^372,396!0^372,372!0^372,348!0^708,396!0^684,396!0^612,540!0^636,540!0^132,372!0^156,372!0^108,372!3^756,36!1^756,468#656:1118481|0|0|107880448|107374182|107374182|35791462|35791394|35791394|35791394|35791394|35791394|35791394|35791394|107405858|107374182|107374182|107374182|40265318|35791394|35791394|17900066|17895697|17895697|17895697|17895697|35840274|35791394|35791392|35791394|35791394|2105890|34|4096|2097408|16847104|17899793|17895697|17895697|1|17895696|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17891601|35852561|35791394|237399586|107374182|17895734|17895697|17895697|17895697|17895697|17895697|7082001|89985297|18175317|219222289|106255701|89474389|17895701|35721488|35791394|19014178|17895697|17891601|17895697|17895697|17895697|17895697|17895697|89478477|36767061|115483170|107374182|105277030|89478470|106255701|89986389|89478485|89478485|89478485|89478485|89478485|36509269|35791394|35791394|35783202|34#
```

## 08-2-SR

```text
$08-2 artifact#metanet##10111150210111500150000101500000201500001000005010000000010000050000300100000000500000000031005000000000000000003500000000000000000000350300000000000000000035001000000000000000003500010000000000000000350000100000000000000035001002000000000000003500000000000000114000350000000000000001110035000000000000000002100100000000000001400001000000000000000011110000000000000000000111100000000000000000001500001000000000000000000000310010000000000000000011100240000000000000000115000240001000000000000000000240000000000000000000000240000000000000000000000240001000000000000000000240000000000000000000000240000000000000000000000240200040000000000000000240000100000000000000000210001400000000000140000200011140003140031114000|5^48,540!6^636,564,3,1,0,3!6^276,564,2,1,0,3!6^492,564,3,1,0,3!7^420,372,3!7^396,372,3!7^444,420,3!7^372,420,3!7^396,468,3!7^420,468,3!7^444,516,3!7^372,516,3!7^540,540,3!7^276,540,3!9^684,564,0,0,2,2,1,0,0!11^732,84,36,276!9^132,564,0,0,2,2,1,-1,0!9^36,60,0,0,2,11,1,0,0!6^396,204,1,0,1,0!0^444,84!0^432,84!0^420,84!0^408,84!0^396,84!0^384,84!0^372,84!0^372,72!0^384,72!0^396,72!0^408,72!0^420,72!0^432,72!0^444,72!0^492,180!0^504,180!0^516,180!0^516,168!0^504,168!0^492,168!0^492,156!0^504,156!0^516,156!0^420,252!0^408,252!0^396,252!0^396,264!0^408,264!0^420,264!0^420,240!0^408,240!0^396,240!0^324,180!0^312,180!0^300,180!0^300,168!0^312,168!0^324,168!0^324,156!0^312,156!0^300,156!12^348,300!12^348,276!12^468,276!12^468,300!2^408,360,0,-1!2^756,276,-0.707106781186547,-0.707106781186547!2^48,240,0.707106781186547,-0.707106781186547!2^324,324,-0.707106781186547,-0.707106781186547!2^492,324,0.707106781186547,-0.707106781186547!2^756,396,-0.707106781186547,-0.707106781186547!1^564,108!1^252,108!0^36,420!0^36,396!0^60,420!0^84,420!0^36,408!0^48,420!0^48,408!0^84,60!0^108,60!0^132,60!0^96,276!0^180,540!0^204,540!0^228,540!0^588,516!0^516,444!0^420,444!0^396,444!0^444,396!0^372,396!0^372,492!0^444,492!0^540,516!0^276,516#869:35791393|35791394|35791394|107374306|107376166|107374182|107374182|107374182|40265318|40265326|35791394|35791394|89480482|107435349|107374182|107374182|36071014|35791394|35791394|35791394|35791394|35791394|17895698|17895697|36770065|35791394|35791394|35791394|35791394|35791633|35790882|35791394|35791394|2236962|35791394|219275810|89478485|17895765|17895697|17895697|17895697|17895697|17895697|97587473|89478485|17913173|17895697|17895697|219222289|17895697|34672913|17895697|235999505|35791394|35791394|107374190|107374182|107374182|35791394|107376162|107374182|107374182|107374182|35791462|35791394|35791394|237397730|89478758|89478485|17912917|219222289|17895701|219222289|89478485|89478485|89478485|17895765|17895697|17895697|17895697|17895697|17895697|30478609|35791406|35791394|35791394|35791394|17895731|17895697|17895697|1118481|17895697|17895697|17895697|17895697|17895697|17895697|47255825|35791406|52568610|1118481|115414481|107374182|107374182|107374182|35791396|35791394|35791394|35791394|35791394|35791394|35791394|19014178|98705954|107373909|35791398|35660322|237117986|107374182|107374182|40265318|35791470|35791394|35725856|2#
```

## 17-2-SR

```text
$17-2 cache#metanet##5211521150111150000000240210015031500000000000140100103110000311114001101001011100035000211011010?E011500350000015011010NP011000100000010011010NP015000100000000011010>D010000240000000011010010100000240000000110100B0100000010000000110100N0100000010000000110100N0240000350000000150100N0024003500000000500100C00021150000000000001001000000000000000003010?E000000000000000001010NP000000000000000001010NP000000000000000001010>D00000000000000000101@0100000000000000000101D010000000040000000010B1010000000010001400010>E0100000030100011000100001000000101400150301@0001000000101110103101D000100000010111010110114031000003101110101101111110000315011101011021111500031503115010210000000001150311503140240000000011431114311140|5^84,84!9^744,552,0,0,4,23,1,0,0!9^48,240,0,0,26,21,1,-1,0!9^48,48,0,0,4,8,1,0,0!9^744,432,0,0,25,15,1,-1,0!9^60,144,0,0,25,19,1,-1,0!11^264,372,744,312!1^228,516!1^468,516!1^348,516!3^432,192!3^108,444!12^276,180!12^324,180!12^372,168!12^228,168!12^108,168!12^84,168!6^156,132,2,0,0,0!1^288,468!1^408,468!1^408,396!1^408,300!1^480,324!0^132,84!0^276,84!0^204,84!0^444,36!0^660,36!0^516,36!0^588,36!0^252,204!0^228,204!0^180,204!0^168,204!0^156,204!0^240,204!0^660,372!0^648,372!0^636,372!0^684,468!0^672,468!0^660,468!0^684,516!0^672,516!0^660,516!0^180,324!0^168,324!0^156,324!0^756,228!0^756,216!0^756,204!0^744,228!0^732,228!0^744,216#1558:17895697|89985297|17896789|17895697|35794193|35791394|35791394|35791394|35791394|115483170|107374182|40265318|36577826|35791394|107374190|35791398|35791394|107374190|35791398|35791586|107880994|35791394|35791394|35791394|17895970|17895697|17895697|17895697|17895697|89510161|89478485|89478485|17895701|34672913|97587744|89478485|89478485|17896789|17895697|89985297|17895701|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|115478801|35791462|35791394|35790882|35791394|107880994|35808870|35791394|35791394|115483170|107374182|107374182|107374182|40265318|35791394|35791394|35791394|107405858|107374182|107374182|237118054|97641062|89478485|89478485|89478485|89478485|89510229|89478485|22369621|35791409|35791394|107405858|107374182|107374182|35791462|35791394|35791394|35791394|107405858|107374182|107374182|107405926|35792486|107405858|35791462|35791394|546|17895697|17895697|17895697|16847121|89480465|89478485|89478485|17913173|17895697|35787025|17895699|17895697|89510161|89480469|89478485|89478485|17895765|89478609|22369621|17895697|17895709|17895697|17895697|237764609|107374182|40265318|35791394|40265442|35791394|35791394|48374306|18031138|17895697|17895697|36770065|17965602|35787025|33694242|35791394|35791394|35791394|35791394|35791394|107880994|107374182|35808994|237117986|35791394|35791394|35791394|29360162|89478493|89478485|17895697|17944849|17895697|17895697|17895697|89478609|105280853|107374306|35791394|35791394|35791394|35791394|35791394|115483170|35792486|107880994|107374182|17949218|17895697|17895697|17895697|17895697|219222289|17895697|89480465|89478485|89478485|106255701|35784294|35791406|35791394|35791394|35791394|35791394|237117986|107374182|107374182|36071014|107405858|36071014|35791394|17895906|17895697|17895697|17895697|17895697|17895697|18175325|219222289|17913173|17904162|16847121|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|219533585|107374305|107374182|236349030|107374182|107374182|35791462|35791394|35791394|35791394|8738#
```

## 90-0-SR

```text
$90-0 self-inflicted#metanet##50000015000000000000000000000100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001000000000000000040000014000000000000000|5^756,156!1^660,180!1^588,180!1^516,180!1^444,180!1^132,180!1^204,180!1^276,180!1^348,180!12^768,228!12^768,276!12^768,324!12^768,372!12^768,420!12^768,468!12^768,516!12^768,564!12^756,252!12^756,300!12^756,348!12^756,396!12^756,444!12^756,492!12^756,540!12^24,228!12^24,276!12^24,324!12^24,372!12^24,420!12^24,468!12^24,516!12^24,564!12^36,252!12^36,300!12^36,348!12^36,396!12^36,444!12^36,492!12^36,540!0^156,180!0^168,180!0^180,180!0^228,180!0^240,180!0^252,180!0^300,180!0^312,180!0^324,180!0^636,180!0^624,180!0^612,180!0^564,180!0^552,180!0^540,180!0^492,180!0^480,180!0^468,180!0^420,180!0^408,180!0^384,180!0^372,180!0^396,180!11^744,156,48,156!12^696,180!12^96,180!12^132,204!12^204,204!12^276,204!12^348,204!12^444,204!12^516,204!12^588,204!12^660,204#304:17895697|17896797|17895697|17895697|17895697|17895697|17895697|17891793|17895697|17895698|18944529|17896913|17895698|17895697|17895697|89510177|18175317|17895697|17895697|17895697|18944273|17895709|1118481|107374306|107374182|35808870|35791394|35791394|35791394|35791394|81928738|107374182|35722854|35783202|35791394|1052706|81928738|107374149|107374182|35717157|35791394|35791394|35791394|290#
```

## 00-0-SR

```text
$00-0 the motherlode#metanet##9000000000000000000000080000000000000000000000111111<0000000000000000111111100003111LH000000119696100001110FJLH000011087010000111000FJ10001=01101000011100000500?900:=01000021500000000C000000100000000000000?1000000=00000000000000C1000;<0000003140000000110001100000011100000001100011000000111000000011000:=0000001110000000210000000000021100000000200000<0000002100000000000000=0000000100000000000000000000001000000;<00000<000040001000000:=00000=0000100050000000000000000005000000000000000000000000000000000;<00000<0000000000000001100000=0000000000040001100000000000000000100011000000000000400001000:=00004000000310000500000000010000021100000000000400100000000000000;<0001001000000000000001100010014000000000000711807|5^60,516!11^588,492,168,156!7^180,156,0!7^300,228,3!7^324,228,3!7^348,228,3!7^252,252,3!7^228,252,3!7^228,396,3!7^252,396,3!7^540,372,3!7^564,372,3!7^708,372,3!7^732,372,3!1^588,228!1^408,264!1^384,492!1^480,444!1^300,444!1^84,252!0^36,48!0^60,48!0^48,48!0^48,36!0^36,60!0^36,72!0^36,84!0^36,96!0^36,108!0^48,60!0^48,72!0^48,84!0^48,96!0^48,108!0^60,108!0^60,96!0^60,84!0^60,72!0^60,60!0^60,120!0^60,132!0^60,144!0^60,156!0^48,156!0^36,156!0^36,144!0^36,132!0^36,120!0^48,120!0^48,132!0^48,144!0^156,84!0^144,84!0^132,96!0^144,108!0^156,120!0^144,132!0^132,144!0^144,156!0^168,84!0^180,84!0^300,84!0^324,84!0^396,132!0^420,132!0^468,108!0^492,108!0^564,108!0^588,108!0^660,84!0^684,84!0^708,84!0^732,84!0^756,84!0^744,72!0^720,72!0^696,72!0^672,72!0^468,228!0^492,228!0^516,228!0^588,396!0^612,396!0^636,396!0^660,396!2^636,288,0,-1!2^36,576,0,-1!2^204,300,0.707106781186547,-0.707106781186547!0^276,516!0^300,516!0^324,516!0^132,564!0^156,564!0^180,552!0^204,540!0^228,528!0^252,516!0^396,564!0^444,564!0^492,564!0^540,564!0^588,564!0^636,564!0^684,564!0^732,564!0^756,564!0^756,540!0^744,552!0^744,528!0^732,540!0^720,552!0^708,564!0^756,516!0^756,444!0^732,444!0^756,420#335:17895697|17895697|17895697|81858833|105268292|107243110|107374182|115476070|35791394|19014178|17900065|17895696|89480465|89478485|89478485|89478485|219222289|90457429|89474405|89478485|89478485|17895701|17895697|17895697|35791121|35840546|17900066|17944849|35787025|35791394|35791394|57890|2236961|34734114|35790882|35791394|2236962|35659778|35791394|17895697|17895697|17895697|33624337|35791394|35791394|35791394|35791394|2236962#
```

## 14-4-SR

```text
$14-4 industrial zone 3#metanet##50001000000000000000211000050000000000000000210000000000000003100000200000311111111115000000000001500000000000000000000010000000000310000000003100000000001500000000011000000000010000000000150011000000100003100000000210000001000011000000000100000010000100000000001000000100001000000000010000001000010000000000100000010000100000000031000000100001000000001110000031000000000000010000000150000030000000100000001000000100000001000000000000000000000010000000000000000014003100000000010000000110011000000003100000001000000000000015000000010000000000000100000000140000000000001000000002100000000000010000000001000000000000100000000014000031140031000000000111111500111110000000000000000000000000000340000000000000000000031|5^708,288!11^288,564,216,108!9^432,360,0,0,15,23,1,0,0!9^684,192,0,0,15,23,1,-1,0!9^672,384,0,0,14,23,1,-1,0!9^132,300,0,0,13,23,1,-1,0!3^312,288!10^420,228!1^192,504!1^132,540!1^408,504!1^492,540!1^660,516!6^60,108,3,0,1,0!0^348,228!0^336,228!0^324,228!0^312,228!0^300,228!0^288,228!0^276,228!0^492,180!0^480,180!0^468,180!0^456,180!0^444,180!0^432,180!0^420,180!0^60,180!0^60,204!0^60,228!0^60,252!0^60,276!0^60,300!0^60,324!0^60,348!0^60,372!12^36,156!12^84,228!12^36,300!12^84,372!1^636,288!1^564,348!1^180,348!1^324,372!4^108,570,1!4^708,570,1#552:1118481|0|107376173|107374182|107374182|107376166|124151398|17913173|16847121|17895697|17895697|17895697|219222289|17913173|17895697|17895697|17895697|35791409|35791394|17895714|1118481|17895697|89985297|89478485|107369813|107374182|35792486|35660322|35791394|35791394|19014178|17895697|17895697|17895681|17895697|17895697|17895697|17895697|17895697|17895697|35791121|35791394|35791394|35791394|35790882|35791394|35791394|35791394|35791394|36577826|36577826|35791394|35791394|35791394|35791393|35791394|35791394|35791394|35791394|97640994|107304277|40265318|107405934|107374182|89990758|35804501|35791394|35791394|17895697|17895697|17895696|17895697|1118481|17895697|17895697|17895697|17895681|17895697|1118493#
```

## 06-4-SR

```text
$06-4 the gauntlet#metanet##00000000000000001100000000000000000000011000000000000000000000110000000000000000000001100000000000004000000011000000000000010000000110000000000000100000001100000000000001000000011000000000000010000000110000000000000100000001500000000000001000000010000000000000010000000100000000000000100000001000000000000001000000010000000000000010000000100000000000000100000001000000000000001000000010000000000000010000000100000000000000100000001000000000000001000000010000000000000010000000100000000000000100000001000000000000001000000010000000000000010000000100000000000000100000001000000000000001000000010000000000400010000000500000000001000100000000000000000010001000000000000000000100010000000000000000001000100000000000000|5^47.6846448661045,500.259948983262!0^756,564!0^756,540!0^732,564!0^492,468!0^444,468!0^396,468!0^732,180!0^708,156!0^708,204!0^732,204!0^684,204!0^756,204!0^156,132!0^204,132!0^252,132!12^36,156!12^36,180!8^756,252,1!8^252,252,1!8^204,252,1!8^156,252,1!3^564,252!3^444,252!3^324,252!2^36,408,0,-1!11^756,108,396,348!4^276,210,1!1^564,156!10^36,132!4^252,570,1#473:35791394|35791394|35791394|35791394|35791394|35791394|35791586|35791394|35791394|35791394|35791394|237117986|107374182|107374182|40265318|35791394|35791394|35791394|35791394|35791394|35791394|107374306|107374182|107374182|107882086|107374182|107374182|89474391|97604949|89478485|22369621|17895697|17895697|17895697|17895697|17895697|17895697|17895697|106255825|107374182|72705638|22365525|89478493|89478609|115430741|35791398|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|237117986|107374182|107374182|107374182|107374182|35791462|35791394|35791394|107376162|35792486|35791394|35791394|35791394|8738#
```

## 17-1-SR

```text
$17-1 timing#metanet##50215000000000215021110000000000000000100000000001000000000001000000000010000000000010000000000100000000000100000000001000000000001000000040310000000000010000000111100000000000100000001111000000000001000000050210000000000010000000000100000000000100000000001000000000001000000000010000000000010000000000100000000000100000000001000000000001000000000010000000000010000000000100000000000100000000001000000000001000000000010000000000010000000000100000000000100000000001000000000001000000000010000000000010000000000100000000000100000000001000000000001000000000000000000000010000000000100000000000100000000001000000000001000000000010000000000010000000000100000000000000000000001000000000000000000040314000000000000000003|5^132,372!0^660,324!0^588,300!0^516,324!0^444,300!0^372,324!0^300,300!0^228,324!0^156,300!0^84,324!8^204,564,3!8^180,564,3!8^156,420,1!8^132,420,1!8^108,564,3!8^84,420,1!8^564,420,1!8^540,420,1!8^516,564,3!8^492,564,3!8^468,420,1!8^444,420,1!12^552,564!12^456,564!12^228,564!12^144,564!11^84,372,30,564!6^156,84,3,0,1,0!6^84,84,3,0,1,0!6^708,84,3,0,2,0!6^636,84,3,0,2,0!9^48,564,1,0,25,4,1,0,-1!9^60,564,1,0,2,4,1,0,-1!0^336,540!0^336,516!0^336,468!0^336,444!0^372,492!0^372,480!0^372,468!0^372,504!0^372,516!0^300,492!0^300,480!0^300,468!0^300,504!0^300,516!0^312,528!0^324,540!0^348,540!0^360,528!0^360,456!0^348,444!0^324,444!0^312,456!0^324,492!0^324,480!0^324,504!0^348,504!0^348,492!0^348,480#569:35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|237117986|107374182|107374182|107374182|107374182|35791462|35791394|35791394|35791394|35791394|35791394|35791394|2|65536|17825792|17895697|72699153|106255701|89478485|89478485|17895697|17895697|17895697|219222289|18175317|17895697|17961233|17895697|17895697|17895697|17895713|17895697|17895697|35794205|115483138|219503910|107374421|107374182|107374182|35791394|33694242|35790882|35791470|35791394|35783202|35783202|35791394|35791394|35791394|35791394|35791394|40125634|89478609|89478485|89478485|89478485|17913173|17895697|17895697|16847121|17895697|17895697|17895697|16847121|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17#
```

## 10-2-SR

```text
$10-2 don't look down#metanet##50015000000150000000002000100000001000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003000000000000000000000010000000000000000000000200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000300000000000000000000001000000000000000000000020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000030000000000000000000000100000000000000000000002000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001000000001000000040000014000000014000003|5^84,540!2^396,552,0,-1!2^588,552,0,-1!2^204,552,0,-1!1^540,372!1^444,372!1^348,372!1^252,372!1^156,372!1^60,372!1^636,372!1^636,252!1^540,252!1^444,252!1^348,252!1^252,252!1^156,252!1^108,336!1^684,216!1^636,132!1^540,132!1^444,132!1^348,132!1^252,132!1^156,132!1^108,120!0^636,36!0^636,48!0^540,48!0^540,36!0^444,36!0^444,48!0^348,48!0^348,36!0^252,36!0^252,48!0^156,48!0^156,36!0^156,156!0^156,168!0^252,156!0^252,168!0^348,156!0^348,168!0^444,156!0^444,168!0^540,156!0^540,168!0^636,156!0^636,168!0^636,276!0^540,276!0^444,276!0^348,276!0^252,276!0^156,276!11^48,84,48,276#155:17895697|17895681|17895697|97587473|115528021|107374182|107374182|2236962|35791394|35791394|35791394|23986208|80813597|17895697|17895697|219222289|105145668|107374180|107374182|107374182|17896914|17895697|1#
```

## 19-1-SR

```text
$19-1 les islots B#metanet##0011111119000000000000600:1111110000000000000700006111100000;<000;11100000:1110000011000111100000061100000:=000:1110000000:180000000000006000000006111<0000000007000000000:11100;<0000;1000000000061100110000:100000000000:=0011000006000000000000000:=00000700000000000000000000;1100000000000000000000:11000000000000000000000060000000000000000000000000000000000000000;<00000000000000000000011000000000000000000000:=000000000000000000000000000800000000000000000000001<0000000000000000;11101=0000000000000000:11109000000000000000000619000000000000000;<0000100000000000000001100001000000000000;<0011000010000000000001100110000100000000;<00110011800010000000011001187111<0010000;<001187111111110010000118711111111111187187|5^36,48!11^660,564,756,60!9^420,60,0,0,21,23,1,-1,0!0^36,252!0^48,252!0^60,252!0^72,252!0^84,252!0^96,252!0^108,252!0^120,252!0^132,252!0^144,252!0^156,252!0^156,264!0^144,264!0^132,264!0^120,264!0^108,264!0^96,264!0^84,264!0^72,264!0^60,264!0^48,264!0^36,264!0^36,276!0^48,276!0^60,276!0^72,276!0^84,276!0^96,276!0^108,276!0^120,276!0^132,276!0^144,276!0^156,276!6^468,564,2,0,1,2!6^420,492,1,0,1,0!1^420,132!1^372,204!1^468,204!1^420,276!1^324,324!1^516,324!9^744,480,0,0,22,23,1,0,0!12^576,444!12^588,324!12^636,228!12^684,132!0^696,336!0^684,336!0^672,336!0^660,336!0^648,336!0^720,240!0^708,240!0^696,240!0^744,144!0^48,564!0^48,540!0^48,552!0^48,528!0^48,516!0^48,492!0^48,504!0^36,504!0^36,528!0^36,552!0^60,552!0^60,528!0^60,504!0^168,564!0^168,552!0^168,540!0^180,552!0^156,552!0^264,564!0^264,552!0^264,540!0^276,552!0^252,552!12^108,360!12^240,384!12^108,480!12^216,528!12^312,504#534:35791394|35791394|107374190|35791398|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|17895730|107374305|36071014|35791394|237904418|89510626|107379733|107374150|89478487|89478485|51450197|35791394|35791394|35791394|17900066|17895697|35791377|35791394|107374306|107437350|107374182|107374182|107374182|35792470|35791394|35791394|115483170|17966694|22369629|17895697|17891601|35787025|2101794|17830144|16847105|2232577|35791394|35791394|35791394|35791394|35791394|35791362|35791394|107376162|40265318|18883106|17895697|89985297|89478485|89478485|17913173|17895697|16847121|17895697|34672913|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|226#
```

## 33-2-SR

```text
$33-2 stratego#metanet##11111111111111111111111500000000000000000000020000000000000000000000040000000000000000000003114031111403111111111111110111111011111111111111101150110111500000002111011001101110000000001110110011011100000000011101100110111000000000115021001102150000000005000010015000000000000000000100000000000000000000001000000000000000030000010000000000000311100000100000000000001111000001000000000000021110000010000000000000002100000100003000000000001000001000010000000000010000010000100000000000200000100001000000000000000001400310000000000000000011111100000000000300000111111000000000311000001111150000000001110000011150000000000021100000111000000000000002000001110000000000000000000011100000000000000040003111400000000000003|5^84,540!11^204,204,708,252!9^732,84,0,0,6,11,1,-1,0!9^516,84,0,0,10,11,1,0,0!12^336,96!12^384,144!12^468,144!12^552,144!12^612,144!12^660,144!12^744,144!12^768,108!12^768,60!12^684,48!12^636,84!12^576,120!12^552,60!12^456,48!12^420,96!12^312,48!12^384,120!12^492,144!6^108,372,3,1,0,3!6^60,348,3,1,0,1!2^396,480,0,-1!2^468,276,-0.707106781186547,-0.707106781186547!3^552,324!2^636,504,0,-1!2^720,576,0,-1!0^324,564!0^312,564!0^300,564!0^288,564!0^276,564!0^264,564!0^252,564!0^240,564!0^228,564!0^216,564!0^204,564!0^336,552!0^324,552!0^312,552!0^300,552!0^288,552!0^276,552!0^264,552!0^252,552!0^240,552!0^228,552!0^216,552!0^204,552!0^192,552!0^540,564!0^552,564!0^564,564!0^576,552!0^564,552!0^552,552!0^540,552!0^528,552!3^204,396!1^540,444!1^468,372!1^264,468!4^540,258,1!0^564,240!0^564,228!0^564,216!0^564,204!0^564,192!0^552,180!0^552,192!0^552,204!0^552,216!0^552,228!0^552,240!0^552,252!6^108,108,3,1,0,3#767:35791394|35791394|17895696|17895697|22369745|107376173|107374182|107374182|89510246|89478485|89478485|89986389|73819477|107374182|107374182|35792486|35791394|35791394|35791394|237117986|35791394|107376162|107374182|35792486|35791394|35791394|35791394|35791394|35791394|35791394|107405858|40265318|35791394|35791394|35791394|18682402|17895697|17895697|17895697|17895697|17895697|97587473|89478485|89478485|17896789|17895697|17895697|17895697|17895697|17895697|48304401|17896226|17830161|17895697|89985297|17895701|17895697|17895697|4369|0|0|0|35794464|35791394|35791394|35791394|35791394|35791394|107374306|35791462|107376162|107374182|35791462|35791394|35791394|1188386|17895697|17895697|17895697|115478801|107374182|107374306|107374182|107374182|107374182|107374182|107374182|89480486|17913173|17895697|17895697|17895697|17895697|17895697|35787025|35791394|35791394|35791394|17895697|30478801|89510161|89478485|89478485|18175317|17895697|17895697|17895697|17895697|17895697|4369#
```

## 02-4-SR

```text
$02-4 (don't) go for the gold#metanet##00400000000000000000000001H00000000000000000000011111111111111111110000000000001010000000100211110001010101111101000>10101110101010000010000101010001010101110100001010111010101010101000010100010101010101010000101011101010111010100001011100010100000101000010000011100011111010000101111100011100000100001010000011100011101000010101110100011101010000101010111011100010100001000100010000011101000011111010111110100010000100000100000101010100001011111011101110101000010100010001000001010000101010111010111010100001010100010101010101000010101011101010101010000101010101010101110100001010101000101000001@00010111011111011111111400100000000000000000000001111111111111111111000000000000000000000F10000000000000000000000200|5^756,564!9^468,396,1,0,4,3,1,0,-1!9^612,252,0,0,27,14,1,0,0!9^564,396,1,0,12,13,1,0,-1!9^636,156,0,0,19,20,1,-1,0!9^228,396,0,0,27,8,1,0,0!9^372,252,1,0,12,5,1,0,-1!9^204,444,1,1,4,9,0,0,0!9^564,252,1,1,4,5,0,0,0!0^564,228!0^396,204!0^588,444!0^564,444!0^540,444!0^204,444!0^276,444!0^276,420!0^276,396!0^276,372!0^372,444!0^180,204!0^180,228!0^228,204!0^228,180!0^252,156!4^108,306,1!11^36,60,132,204!0^132,180!0^564,252!0^156,108!0^180,108!0^204,108!0^228,108!0^252,108#2103:17895697|17895697|17895697|97587473|22369621|202116108|12632256|71584780|16794692|17896797|17895697|17895697|17895697|17944849|219222289|18175317|17895697|35791394|546|17895424|17891601|17895697|17898769|35791395|35791394|35791394|35791394|35791394|107405858|36071014|19014178|35852561|35790882|35791394|35791394|35791394|35791394|35791394|237904418|35840738|35791394|35791394|2236962|17891600|17895697|17895697|17895697|17895697|17895697|97587473|89986513|89478485|35853653|8738|0|0|33694242|35791394|107880994|52568614|17895697|33|16777216|17830161|17895697|17895697|18682129|17895697|35791121|17895681|17895697|17895697|17895697|17895697|17895697|115544337|237907494|36102882|35791394|237429358|35792486|48374306|107882094|107374182|35791398|17900066|17895697|2097152|35791394|35791394|35791394|2236962|17945298|17895697|238096657|48423526|89986670|89478485|17895765|35787025|17895714|17895697|18682129|17895697|35791121|17895699|17895696|17898769|17895697|35791377|139810|1118480|17895697|17895697|17895697|17895697|17895697|89510161|35791121|48391906|237907502|35791394|35791394|35791394|219021570|17895697|219222289|17895697|69905|0|33554432|35791392|35791394|35791394|35791394|35791394|35791394|107374306|107374182|107374182|107374306|35808870|115532322|40267302|35791394|35791394|97591842|220011797|40296789|35791394|35791394|35791394|35791394|35808878|115483168|35840738|35791394|35791394|35791394|17898770|17895697|17895697|17895697|17895697|22401297|17895697|237837597|35791398|35791394|35791394|35791394|74274|17898766|17895697|17895697|30478609|17895697|273|35791392|35791394|35791394|35791394|35791586|35791394|237117986|35791394|8738|0|0|0|0|0|17895889|17895697|17895697|17895697|17895697|105783825|35791394|35791394|35791394|16777250|17891601|17895697|17895697|18682129|17895697|33554705|35791392|35791394|35791394|35791394|35791394|35791394|107374306|36071014|40772130|220011805|17896913|17895697|17895697|30478609|35791406|35791394|35791406|2236962|0|0|17895681|17895697|17895697|17895697|17895697|17895697|89480465|89478485|89478485|89480469|22369621|97587473|89478485|89478485|97604949|18175317|97587473|17895765|236785937|97706722|107881813|35791394|35791394|35791394|35791394|107374306|35808870|237904418|107375654|35791394|39178978|35808878|35791394|48374306|17895709|219503889|30527953|35791470|35791394|35791394|221127202|18207185|17895697|17895697|17895697|36077329|35791394|35791394|546|16777216|17895681|17895697|17895709|34672913|17895970|17895697|17895697|17895697|17895697|17895697|219222289|17895697|89510161|17896789|35791586|19005472|17896797|219222289|30527953|22371613|17895697|17895697|273#
```

## 11-1-SR

```text
$11-1 cityscape 2#metanet##00000000000000000000000503111115031111150311110350003503500035035003135000350350003503500315500035035000350350031531111503111115031111153500000000000000000315350111111111111150311535000000000P000000031535000000OOO0P000000311153000000P0000000000000001000000P0000000000N11P05003000QQQP0000000N10P00001000000P0000000N10P000010OOOOOP0000000N10P000050P000000000000N10P000000P000000000000N10P;O0000P000000000000N10P:Q0000P000000000000N10P000000QQQQQQQQQP000N10P000000000000000P000N10P000000000000000P000N10P00000000OOOOOOOP000N10P00300000P0000000000N10P00100000P0000000000O10P00500000P0000000000010P00000000QQPNQQQQP00Q10P0000000000PN0000P00N10P0000000OOOPNOOOOP00N10P0000000P00000000000N10P000;100P00000000000N10P00019|5^348,492!9^276,408,1,0,11,16,0,0,0!9^276,432,1,0,11,18,0,0,-1!11^612,84,60,60!9^756,516,1,0,11,8,1,0,-1!9^468,108,0,0,8,15,1,0,0!9^468,228,0,0,8,14,1,0,0!9^396,84,0,0,10,7,1,0,0!1^372,252!1^372,300!1^324,204!1^324,300!1^276,252!1^228,252!1^228,300!1^372,348!0^660,168!0^684,168!0^708,168!0^588,120!0^612,120!0^636,120!0^732,120!0^756,120!0^612,168!0^636,144!0^636,192!0^636,240!0^588,216!0^588,264!0^612,288!0^636,288!0^756,144!0^732,96!0^732,192!0^732,216!0^756,192!0^756,240!0^756,264!0^636,312!0^684,312!0^732,312!0^756,336!0^576,336!0^552,336!0^552,288!0^528,312!9^420,180,0,0,18,16,1,0,0!0^552,360!0^732,360!0^672,360!0^492,336!6^180,36,2,0,0,1!4^468,570,1#715:35791394|35791394|17895699|219222289|89478485|89478485|89478485|18175061|17895697|219222289|237429077|131261154|35792486|89480498|17896789|34672913|19014178|35791633|107374304|107882086|107374182|107374182|89985638|17895701|17895697|17895697|124653841|89478485|17895697|17895697|17895697|17895697|17895697|17895697|17895697|34672913|18031138|17830161|89480465|219501909|89474389|17895701|34672897|17895699|17895697|17895697|17895697|17895697|30496093|220011805|89478609|89478485|22369621|19017249|859409|0|0|0|0|0|0|0|0|0|0|107374306|107374182|107374182|107374306|40265318|35791394|35791394|2236962|17891328|1118481|0|36102656|35791394|115483170|36071014|107405858|88430182|40197397|107374190|18679398|219222289|89480469|18175317|35791360|35791394|35791394|35791394|35791394|107374190|107374182|107374182|35791394|107376162|35808870|35791394|35791394|35791394|2#
```

## 17-3-SR

```text
$17-3 longest yard#metanet##001015000000215000000000020100000000100000000000001000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000D000001000000000000000010000010000000000000000E00000100000000000000000000001000000000000000000000?E000000000000000000000CP0000000000000000000001A000000000000000000000200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000310000000000000000000001100000000000000000000015000000000000000000000100000000000000000000000000000000?0000000000000000000000C000000000000000000000310000000000000000000GK11|5^72,300!2^372,324,0.707106781186547,-0.707106781186547!2^588,324,-0.707106781186547,-0.707106781186547!2^144,336,0,-1!12^384,396!12^432,408!12^480,408!12^528,408!12^564,396!11^60,564,36,108!9^636,300,0,0,2,4,1,0,0!12^600,576!12^420,576!12^264,576!12^132,576!12^168,540!12^360,516!12^324,468!12^84,432!12^216,504!12^492,480!12^540,528!12^444,528!12^600,432!12^588,492!12^648,516!12^684,420!12^276,408!12^180,432!10^36,36!3^48,384!0^252,180!0^240,180!0^228,180!0^216,180!0^204,180#536:33694242|35791394|35791394|35791394|115483170|107374182|107374182|35791394|35791394|35791394|35791394|35791394|107374306|35792486|35791394|35791394|35791394|35791394|16847122|17895697|17895697|17895697|17895697|89480465|89478485|17895765|17895697|17895697|17895697|17895697|17895697|89506065|89478485|89478485|89478485|18175317|17895697|17895697|17895697|89478609|89478485|89478485|89478485|17913173|17895697|36576529|35791394|115483170|35783206|35791394|35791394|35791394|35791138|35791394|17965346|1118481|16843024|17830145|1118209|1118481|17895873|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|89478609|17895701|17895697|17895697|17895697|17895697|4369#
```

## 88-4-SR

```text
$88-4 Mother Thumping Impossible#blue_tetris##1I2J111MFI0JQI0FQQQMB111@00B1E00000000000000021P00F11000000000000000?1A00?1A003H0GD0GD00000>1H002100>1111111111A00011@001D001A0000FEI100001I003110?100GH000?1@000100?1150F10B111@0N1P00?100B1100010N111P0N1P00N1@00F1P0310N111P0N1A00B150001A0J10>111P0>1000N100031000100111A001000>1H0F1100?1@0B110001400011I0B140N1A0N110031E0001500>1A0N100N11H0B1P00K1000010021@0N1150N1A0021000G10001A0N1100N1000010C11100?100N1100N1000G10>111@0N100N1100N1H00B1L0FM1A0N140>11@0>1E00C11@00100N1D00B1P001A00J111@0100N11LH>1P001000011A0C100>111111A00140001I0011400FFI0FI0031E00?100GK1E0000000000>1500>1000F11H0GOH00GOHC1@0001400?11111111111111A00011@000FE0BM0FQ150FE000G111L0000000000F0000000B1111A0000000000000000GC1111LKOGH000GOOOH003111|5^48,72!12^96,144!12^144,144!12^168,144!12^252,144!12^276,144!12^384,144!12^408,144!12^540,144!12^516,144!12^492,144!12^648,144!12^672,216!12^672,240!12^768,240!12^768,264!12^768,288!12^768,312!12^672,288!12^672,312!12^756,348!12^756,372!12^756,396!12^672,408!12^672,432!12^768,432!12^768,456!12^768,480!12^684,576!12^660,576!12^636,576!12^564,576!12^540,576!12^432,576!12^408,576!12^360,576!12^336,576!12^312,576!12^192,576!12^168,576!12^144,576!12^120,576!12^120,432!12^120,456!12^120,480!12^36,408!12^36,432!12^36,456!12^36,480!12^24,384!12^24,360!12^120,360!12^120,384!12^36,312!12^36,336!12^120,288!12^120,312!12^24,264!12^24,288!12^144,240!12^168,240!12^204,240!12^228,240!12^288,240!12^312,240!12^408,240!12^432,240!12^468,228!12^492,228!12^648,228!12^576,324!12^648,324!12^648,348!12^636,384!12^636,408!12^576,456!12^552,456!12^528,456!12^504,456!12^336,456!12^312,456!12^288,456!12^252,444!12^228,444!12^204,444!12^168,456!12^144,456!12^144,384!12^144,360!12^144,336!12^144,312!12^144,288!12^192,360!12^216,300!12^240,300!12^264,300!12^300,312!12^336,324!12^360,324!12^384,324!12^420,324!12^444,324!12^468,324!6^348,108,3,0,0,0!9^420,120,1,1,21,5,0,0,-1!8^732,516,3!8^708,540,2!8^60,516,0!12^528,228!12^552,228!12^636,264!12^636,288!8^636,60,1!12^288,564!12^264,564!12^516,552!12^456,552!12^72,576!8^612,204,2!8^612,420,3!12^408,444!12^432,444!12^456,444!8^180,420,0!8^516,300,2!9^36,372,1,1,10,18,0,0,-1!11^516,324,360,204!9^360,204,1,1,21,14,0,0,-1!9^360,204,1,1,22,14,0,0,-1!12^540,348!12^528,348!12^552,348!12^552,360!12^576,384!0^96,96!0^120,84!0^144,96!0^288,84!0^312,84!0^396,72!0^420,72!0^420,72!0^600,84!0^624,84!0^648,84!0^684,168!0^744,144!0^696,348!0^696,444!0^564,528!0^552,504!0^528,492!0^504,504!0^492,528!0^492,528!0^348,552!0^324,528!0^300,516!0^276,528!0^252,552!0^96,552!0^96,528!0^96,528!0^96,504!0^60,348!0^84,348!0^60,240!0^84,240!0^204,216!0^228,204!0^252,216!0^396,216!0^420,204!0^444,192!0^576,432!0^552,420!0^528,420!0^504,420!0^480,432!0^336,432!0^312,420!0^288,408!0^288,288!0^324,300!0^372,276!0^444,276!0^468,276#811:35790881|35791394|107374190|35808870|35791394|35791394|35791394|36068898|35791394|35791394|52568610|237117969|36066918|35791394|35790882|35791377|237117986|107374182|107374182|107374182|40265318|35792494|34|33554432|35791394|35791392|35840034|73819361|107373668|107374182|35792486|35791394|17895714|17895697|17895697|17895697|17895953|2232577|1118241|89985570|17895696|35721489|17825826|89985296|89478485|17830161|17961489|65809|17895697|72637698|17896516|17895697|17895697|17|16781312|17829905|80827857|107397205|107374182|89509958|89544021|106287205|107374150|35792486|35791394|35791394|35791570|35791394|35791394|35791394|35791394|35725602|48374306|35791394|35791394|17895698|17895697|17895697|17895697|17895697|17895697|236064785|17900070|273|16777216|17895697|1118481|69905|90463521|89544021|89478485|5653845|17895697|17895696|22401505|17895698|17895697|17895697|17895697|97587473|17961233|1118481|114364416|89985364|105277029|107365990|107374306|107374182|107374182|39216742|35660322|35791394|35794466|35725842|36577826|2236962#
```

## 00-0-HS

```text
$00-0 the motherlode#metanet##9000000000000000000000080000000000000000000000111111<0000000000000000111111100003111LH000000119696100001110FJLH000011087010000111000FJ10001=01101000011100000500?900:=01000021500000000C000000100000000000000?1000000=00000000000000C1000;<0000003140000000110001100000011100000001100011000000111000000011000:=0000001110000000210000000000021100000000200000<0000002100000000000000=0000000100000000000000000000001000000;<00000<000040001000000:=00000=0000100050000000000000000005000000000000000000000000000000000;<00000<0000000000000001100000=0000000000040001100000000000000000100011000000000000400001000:=00004000000310000500000000010000021100000000000400100000000000000;<0001001000000000000001100010014000000000000711807|5^60,516!11^588,492,168,156!7^180,156,0!7^300,228,3!7^324,228,3!7^348,228,3!7^252,252,3!7^228,252,3!7^228,396,3!7^252,396,3!7^540,372,3!7^564,372,3!7^708,372,3!7^732,372,3!1^588,228!1^408,264!1^384,492!1^480,444!1^300,444!1^84,252!0^36,48!0^60,48!0^48,48!0^48,36!0^36,60!0^36,72!0^36,84!0^36,96!0^36,108!0^48,60!0^48,72!0^48,84!0^48,96!0^48,108!0^60,108!0^60,96!0^60,84!0^60,72!0^60,60!0^60,120!0^60,132!0^60,144!0^60,156!0^48,156!0^36,156!0^36,144!0^36,132!0^36,120!0^48,120!0^48,132!0^48,144!0^156,84!0^144,84!0^132,96!0^144,108!0^156,120!0^144,132!0^132,144!0^144,156!0^168,84!0^180,84!0^300,84!0^324,84!0^396,132!0^420,132!0^468,108!0^492,108!0^564,108!0^588,108!0^660,84!0^684,84!0^708,84!0^732,84!0^756,84!0^744,72!0^720,72!0^696,72!0^672,72!0^468,228!0^492,228!0^516,228!0^588,396!0^612,396!0^636,396!0^660,396!2^636,288,0,-1!2^36,576,0,-1!2^204,300,0.707106781186547,-0.707106781186547!0^276,516!0^300,516!0^324,516!0^132,564!0^156,564!0^180,552!0^204,540!0^228,528!0^252,516!0^396,564!0^444,564!0^492,564!0^540,564!0^588,564!0^636,564!0^684,564!0^732,564!0^756,564!0^756,540!0^744,552!0^744,528!0^732,540!0^720,552!0^708,564!0^756,516!0^756,444!0^732,444!0^756,420#860:17895697|16847105|17895697|113254400|107374182|40265318|89478493|73843029|73749844|38098501|35808878|34672914|51450129|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|107374190|73819750|35791398|35791394|35652129|2171426|35783202|35791394|35791394|35791406|35791378|35791394|107376146|36071013|237113890|107374182|105277030|35792486|16|17895424|97587473|89478485|89478485|107405909|35791398|35791394|35791394|35791394|35791394|220081698|89478485|89478485|89478485|89478485|17895701|17895697|36573457|35791394|35791394|35791394|35791394|237117986|107374182|17895889|17895697|17895697|17895697|17895697|65810|17895697|235995154|35791121|35791394|34611746|17895458|17895697|89510161|89478485|89478485|1119573|17895697|17830161|16847105|17895953|18175441|35787025|35794466|17891874|17898769|35791121|35791394|237117986|107374182|107374182|107370086|40265318|35791394|35791394|35791394|35791394|35791394|35791362|19014178|17895697|35721489|19014178|17895441|17895697|17895697|17895697|17895697|17895697|35791121|35791394|35791394|35791394|35791394|2236962#
```

## 29-1-SR

```text
$29-1 hounds#metanet##50000000000000000001000000000000000000000010000000000000000000000100000000000000000000001011000000000000000000000110000000000000000000000100000000000000000000002000000000000000000000000000000000000000000003100111111111111111111011001500000211500021500114010000000110000010002110100001001100100100001101000010015001001000011010000100000010000003110100031000000100000011101001110000001400003111010002140000311111111150100001111111150000021001400000000000000000000011100000000000000000300000000000000000000001000000000000000000000020000000000000000000000000000000000000000000003000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000020000000000000000000000040000000000000000000003|5^204,552!9^660,540,0,0,4,21,1,-1,0!9^444,60,0,1,16,2,0,-1,0!9^456,60,0,0,10,21,1,-1,0!11^276,60,660,540!6^84,540,2,1,0,3!6^60,564,2,1,0,0!6^36,540,2,1,0,1!6^60,516,2,1,0,2!2^540,552,0,-1!2^468,540,0.707106781186547,-0.707106781186547!2^756,564,-0.707106781186547,-0.707106781186547!0^468,408!0^468,420!0^468,432!0^468,444!0^468,456!0^468,468!0^468,480!0^468,492!0^468,504!0^468,516!0^348,540!0^336,540!0^324,540!0^312,540!0^300,528!0^360,540!0^372,528!12^348,156!12^408,276!12^420,456!12^312,372!10^540,108!3^36,468!2^156,552,0,-1!1^84,324!1^132,276!1^84,228!1^132,180!1^84,132!1^132,84!0^36,60!0^36,84!0^36,108!0^36,132!0^36,156!0^36,180!0^36,204!0^36,228!0^36,252!0^36,276!0^36,300!0^36,324!0^36,348!0^36,372!0^36,396!0^36,420!0^36,444#693:220340770|17895765|17895697|17891601|107374305|107374182|107405926|107374182|107374182|107374182|40265318|35791394|35791394|35791394|35791394|35791394|107374306|107374182|107374182|35794466|17830434|17895697|17895697|17895697|17895697|17895697|17895697|17895697|33624337|35791392|35791394|35791394|35791394|35791394|107374190|35791398|35791393|35791394|35791394|89510434|89478485|89478485|89478485|17913173|17895697|17895697|97587473|89478485|89478485|89478485|17895701|89510161|89478485|17913173|17895697|17895697|17895697|17895441|17895697|35721489|35660322|35790882|35791470|35791394|35791394|34673186|2236962|17891584|34672913|219222289|89478485|18175317|17895697|17895697|17895697|19014161|35791586|17900066|17891601|17895697|17895697|17895697|17895697|17895697|17913297|17895697|17895697|17913297|17895697|17895697|107405585|107374182|107376162|107374182|107374182|107374182|40265318|35791394|35791394#
```

## 73-1-SR

```text
$73-1 frantic#metanet##11111MI00000FJ11E000000111MI000000000000000000A010000000000000000000000E000000000000000000000000000000000000000000000000000000000000000000000000000D000000000000000000000010000000000000000000000E00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000D000000000000D00000000010000000000001000000000E000000000000E0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000D000000000000000000000010000000000000000000000E0000000000000000000000000000000000000000000000000000000000000D00000000000000000000@0100000000000000000000111LH00000000000000000011111LH00000GK11D000000|5^396,372!1^396,252!1^684,252!1^108,252!1^432,324!1^360,324!1^516,276!1^276,276!1^612,132!1^180,132!1^300,120!1^492,120!1^684,180!1^108,180!1^468,204!1^324,204!2^708,96,0,1!2^396,120,0,1!2^588,264,0,1!2^396,432,0,1!2^204,264,0,1!2^84,96,0,1!11^396,396,96,48!0^708,60!0^696,60!0^684,60!0^672,60!0^672,48!0^684,48!0^696,48!0^708,48!0^696,36!0^684,36!0^672,36!3^396,36!3^36,204!3^756,204!3^756,564!3^36,564!1^516,420!1^684,420!1^276,420!1^108,420!1^192,492!1^348,516!1^444,516!1^600,492!0^678,396!0^690,396!0^690,384!0^678,384!0^594,468!0^606,468!0^606,456!0^594,456!0^438,492!0^450,492!0^450,480!0^438,480!0^342,492!0^354,492!0^354,480!0^342,480!0^186,468!0^198,468!0^198,456!0^186,456!0^102,396!0^114,396!0^114,384!0^102,384!0^114,228!0^102,228!0^102,216!0^114,216!0^102,156!0^114,156!0^114,144!0^102,144!0^678,228!0^690,228!0^690,216!0^678,216!0^678,156!0^690,156!0^690,144!0^678,144#203:17895697|1118465|97587473|88364372|73819236|219501670|106194260|220620391|89478485|89478485|89478609|89478485|89478485|89478485|17913173|17895697|17895697|17895697|35791569|35791394|33694242|35790880|33559074|17834530|33559072|35790882|35791394|34742818|35791393#
```

## 00-1-SR

```text
$00-1 cloud city#metanet##000000000000:9006110000000000000000008071=000000000000;<0000:1110000000000000110000011=000000000000;1100000:=00000000000;111100000000000000000;1196100000000000000000119001000000000000000001=0001000000;<00000000010007100000;1100000000;100;1=00000111<0000000:907110000001111000000000011=0000001961000000000011000000010010000000000:=00000;0:00100000000000000000:80001000000000000000000:807=000000000000000000011100000000000000000000:11000000000000000000000:=0000000000000000000000000;<00000000000000000000;110000000000000000000;111000000000000000000011110000000000000000000111100000000000000000;111110000000000000000;11111100000;11111111111119611000;1111111111111110011000:11111111111111=00:=000000000000000000000000|5^108,564!1^612,132!1^516,132!1^420,132!1^180,492!1^540,300!1^60,84!11^708,492,36,396!0^444,372!0^132,180!0^108,204!0^288,84!0^360,156!0^108,372!0^228,396!0^660,372!0^636,396!0^684,108!0^540,468!0^492,396!9^204,204,0,0,1,14,1,0,0!11^372,444,60,60!9^60,60,0,1,15,15,0,-1,0!0^228,576!0^240,576!0^252,576!0^264,576!0^276,576!0^288,576!0^300,576!0^312,576!0^324,576!0^336,576!0^348,576!0^360,576!0^372,576!0^384,576!0^396,576!0^408,576!0^420,576!0^432,576!0^444,576!0^456,576#300:115483170|107374182|107374182|107374182|115500646|107374182|107374182|124150886|89478519|30478613|17895697|17895697|17895697|17895697|97609169|89478485|89478485|89480469|89478485|89478485|89478485|114382165|89478214|17895697|17895697|17895697|35791361|35790882|35791394|35791394|35791394|35791394|107880994|106325606|36071014|35791394|35791394|35791394|35791394|237117986|40265318|17895697|1118481#
```

## 07-2-SR

```text
$07-2 hunted#metanet##90000061190061101900006000;<00:=0;<0:=01000000000:=00000618007100000000000000000:1111=0000008000000000000000000;<001<0000000;<00000000:=000000;<000:=0000000000000000:=000000000000000001=000000000000000000000900000000000000000;<000000000000000;<0000:=000000000000000:=0000000000000;<000000000000000000000:=0000000000000000000000000000000000000000000000000000000;<000000000000000000000:=000000000000000000000000000000000000000000000000000000000000000000000000000000000000;<000000000000000000000:=000000000000000000000000000000;<000000000000000000000:=000000000000000000000000000000;<000000000000000000000:=00000000;<000000000000000000000:=000000000000000000000000000<0080<000000000000000;010010180000000000000710187|5^744,540!11^48,396,756,492!9^192,36,0,0,31,2,1,-1,0!9^762,60,0,0,30,20,1,-1,0!6^108,204,4,1,0,3!6^756,132,5,1,0,1!6^588,276,4,1,0,3!6^204,348,5,1,0,1!0^192,108!0^168,228!0^72,84!0^336,108!0^288,300!0^408,372!0^408,360!0^408,348!0^288,288!0^288,276!0^168,216!0^168,204!0^192,96!0^192,84!0^72,72!0^72,60!0^336,96!0^336,84!0^528,228!0^528,216!0^528,204!0^648,108!0^648,96!0^648,84!0^672,348!0^672,336!0^672,324!0^576,444!0^576,432!0^576,420!0^264,444!0^264,432!0^264,420!0^144,468!0^144,456!0^144,444#684:17895713|17895697|17895697|108859665|107374182|107374182|40265316|89478493|17895701|17895697|17895697|219222289|89478485|89478485|89478485|17895701|17895697|89510161|89478485|89544021|107374289|89417318|89478485|89478485|89478485|90526805|89480469|89478485|89478485|89539925|52241749|35791394|19014178|35783201|107405858|107308646|35791462|35791362|105276898|107374182|35808358|35791394|35791394|35791394|35791138|35791394|35791394|107374190|2254438|35791394|35791394|219222301|34672913|35791394|35791394|17965602|17895697|17895697|17895697|17895697|35782929|35791394|35791394|2236962|35840514|35791394|35791394|35791394|48374306|18175326|17895697|89480465|89478485|89478485|17895701|97587473|89478485|89478229|89478485|22369621|89510145|89478485|17895701|219222289|89478485|17891669|17895697|17895697|17895697|17895697|17895697|17895697|35782658|17965586|35782913|17895698|17895697|921873#
```

## 65-4-SR

```text
$65-4 son of pit of despair#metanet##90006111111111111111111000001111111111111111110000011111111111111111100000111111111111111111000001111111111111111110000011111111111111111100000111111111111111111000001111111111111111110000011111111111111111100000111111111111111111000001111111111111111110000011111111111111190600000:1111111111111=000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000;1111111111111<000000001111111111111118070000011111111111111111100000111111111111111111000001111111111111111110000011111111111111111100000111111111111111111000001111111111111111110000011111111111111111100000111111111111111111000001111111111111111110000011111111111111111180007111111111111111111|5^300,540!8^348,36,1!8^444,36,1!2^336,468,1,0!2^456,468,-1,0!2^456,180,-1,0!2^336,180,1,0!2^336,324,1,0!2^456,324,-1,0!2^456,252,-1,0!2^336,252,1,0!2^336,396,1,0!2^456,396,-1,0!6^36,60,2,0,0,0!6^660,108,3,0,0,0!6^708,132,2,0,0,2!6^156,132,3,0,0,0!11^84,132,708,84!0^84,84!0^108,84!0^132,84!0^156,84!0^180,84!0^204,84!0^228,84!0^252,84!0^276,84!0^300,84!0^324,84!0^468,84!0^492,84!0^516,84!0^540,84!0^564,84!0^588,84!0^612,84!0^636,84!0^660,84!0^684,84!12^352.5,216!12^352.5,288!12^352.5,360!12^352.5,432!12^439.5,432!12^439.5,360!12^439.5,288!12^439.5,216#452:235999505|35791394|35791394|35791394|35791394|18031138|17895697|17895425|17895697|17895697|16847121|35721489|91103778|107370086|107374182|107374182|219440742|107374180|107374182|89510502|89478485|89478485|17895701|115351825|107374182|107374182|107374182|40265318|219222034|89478485|89478469|89478485|89478485|17126741|106325614|107374182|107374182|35791394|35791393|35791394|107880994|107374166|107373926|36071014|35725858|35791394|2236960|35791362|16777762|17895424|17895697|17895697|88461569|88429910|17830146|17891601|17829905|17895697|17895696|219222033|17892693|17895697|17895697|17895697|273#
```

## 19-0-SR

```text
$19-0 superliminal 2#metanet##900000000000000000000060000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000;111111111111111<004000190000000000000000010001000:1111=000:1=0001000100000000000000000710001000;11111111111111=000100010000000000000000001000100000000000000000010;0100000000000000000010101000000000000000000101010000000000000000001010100000000000000000010:010000000000000000001000100000000000000000018071000000000000000000:11118000000000000000000000611111111111111<0000000019000001=000061000000001000000000000010000000018001<00001<00100000000:1111111111=0050000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000080000000000000000000007|5^564,132!11^372,108,588,276!10^384,540!0^468,228!0^444,228!0^420,228!0^396,228!0^372,228!0^348,228!0^324,228!0^300,228!0^300,252!0^300,276!0^300,300!0^324,300!0^348,300!0^372,300!0^396,300!0^420,300!0^444,300!0^468,300!0^468,276!0^468,252!0^444,252!0^420,252!0^396,252!0^372,252!0^348,252!0^324,252!0^324,276!0^348,276!0^372,276!0^396,276!0^420,276!0^444,276!2^444,576,0,-1!2^324,576,0,-1!1^384,456!1^384,336!1^468,396!1^300,396!0^420,324!0^444,324!0^468,324!0^348,324!0^324,324!0^300,324!0^300,348!0^324,348!0^348,348!0^420,348!0^444,348!0^468,348!0^468,372!0^444,372!0^420,372!0^396,372!0^372,372!0^348,372!0^324,372!0^300,372!0^444,396!0^420,396!0^396,396!0^372,396!0^348,396!0^324,396!12^576,456!12^552,384!12^576,312!12^588,228!12^540,228!12^240,408!12^168,252!6^372,156,1,1,0,0!6^396,108,1,1,0,2!6^180,396,1,0,0,1!6^180,276,0,0,0,3!0^588,180!0^576,180!0^564,180!0^552,180!0^540,180!0^204,516!0^192,516!0^180,516!0^168,516!0^156,516!0^612,516!0^600,516!0^588,516!0^576,516!0^564,516#558:35791394|35791394|35791394|35791394|35791394|17895698|17895697|17895697|17895697|17895697|17895441|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|219222289|106287569|107243110|40265318|17896797|115413265|23488102|17895441|17895697|17895697|17895697|35791377|35791394|35791394|17895698|1118481|17895697|17895697|35791394|35791394|16781586|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|97587473|89478485|18175317|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|35791395|107405858|40265318|35791394|35791394|35791394|35791394|2236962|35791394|106769966|237905510|18944466|17965602|17895697|34672913|35791406|35791394|35791394|35791394|35791394|139810#
```

## 06-2-SR

```text
$06-2 space battle#metanet##000000000000000000000000000000000000000000A0000000000000000000000000000000000000000000>000000GOH0000000000000000000?111@000000>@0?A000A000N111P0000000B1E00000000>11100000000>0A000000000FQ000000@0000A00000000000000000P0000000000000000000000000>0000000000000000000000000000000@000000000000000A00000KD00000000000@00000000>1I00000000000P0000000001000000000000000000000K100000000000000000000>1I0000000000004000000001000000000001010000000KI00000000003101400000KI0000000000350002400001000000000001000@01000K10000000000010N0P0100FJ10000000000010>0A01000010N0000000002400035000010N0000000000211150000010N0000000000000000000N10N000A0000000000000000100N000>@0?A0000000000N100N0000B1E00000000000N100N0000>0A000000000000100N00|5^36,564!11^564,252,756,420!9^204,348,0,0,20,10,1,0,0!9^564,84,0,0,14,23,1,-1,0!9^756,564,0,0,19,10,1,-1,0!0^348,84!0^444,132!0^360,96!0^96,180!0^120,192!0^156,192!0^156,240!0^144,252!0^72,384!0^432,372!0^240,540!0^252,480!0^264,468!0^264,480!0^696,264!0^768,204!0^744,300!0^720,24!0^708,36!0^672,36!0^660,36!0^156,36!0^84,48!0^24,72!0^36,84!0^120,456!0^108,468!0^588,420!0^600,408!0^612,432!0^288,168!6^60,156,4,0,2,0!0^756,504!0^744,504!0^732,504!0^720,504!0^708,504!0^696,504!0^684,504!0^660,480!0^648,480!0^636,480!0^624,480!0^612,480!0^600,480!0^588,480!0^660,564!0^648,564!0^636,564!0^624,564!0^612,564!0^600,564!0^588,564!0^564,564!0^576,564!0^552,564!0^540,564!0^516,564!0^504,564!0^504,564!0^492,564!0^480,564!0^468,564!0^468,564!0^456,564!0^444,564!0^432,564!0^420,564!0^696,564!0^708,564!0^432,24!0^24,288!0^120,576!0^696,372!0^708,360!0^708,372!0^720,384#776:35791392|35791394|35791394|35791394|35791394|35791394|35791394|115483170|107374181|107374182|107374306|107374182|107374182|35808870|35791394|35791394|35791394|35791394|107378526|35791462|35791394|35791394|35791394|48374306|107374190|107374182|107374182|107374182|89510502|89478485|89478485|89478485|89478485|89478485|89478485|40267029|17904162|17895697|17895441|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17830161|35840465|35794466|17896242|17895697|17895697|1118481|35791633|35791392|35660322|35791394|35791394|35791394|107880994|107374182|107374182|107374182|107374182|107374182|107374182|35792486|35791394|19014176|35791378|35791394|40265442|17895709|17895697|17895697|17895697|17895697|89510161|89478485|17895765|17895697|17895697|17895697|17895697|17895697|17895696|17895697|35791394|107374306|107374182|107374182|107374182|35791462|35660322|35791394|105213470|89478262|72697173|88425813|17826133|107374306|91645542|107374421|107374182|35791398|35791394|35791394|107405858|2236966#
```

## 13-3-SR

```text
$13-3 crosshairs#metanet##50000000020001500000002000000000000010000000000031100000000500000000040115000000000000001100101500000000000000011401010000000000300000211000500000340001400000210000000031100011400000000000003111000111400000000000311110001111400000000031111100011111400000003111111000111111400000311111110001111111400001111111500021111111000000000000000000000000000000000000000000000000000000000000000000000000011111114000311111110000211111110001111111500000211111100011111150000000211111000111115000000000211110001111500000000000211100011150000000000000211000115000000000400000250001500000310101000000000020000031101014000000000000000115050114000000000000001100002110000000040000000000000000000000100000000040000000030001400000003|5^684,540!1^396,300!6^36,276,2,0,2,0!6^756,324,2,0,2,2!2^120,480,0,-1!2^672,480,0,-1!2^636,348,0.707106781186547,-0.707106781186547!2^756,252,-0.707106781186547,-0.707106781186547!2^720,336,0,-1!2^72,336,0,-1!2^156,348,-0.707106781186547,-0.707106781186547!2^36,252,0.707106781186547,-0.707106781186547!2^240,168,-0.707106781186547,-0.707106781186547!2^552,168,0.707106781186547,-0.707106781186547!2^300,108,-0.707106781186547,-0.707106781186547!2^492,108,0.707106781186547,-0.707106781186547!3^396,156!9^636,564,0,0,6,2,1,0,0!9^612,564,0,0,5,2,1,-1,0!9^138,60,0,0,6,23,1,-1,0!9^150,60,0,0,7,23,1,0,0!11^648,60,168,564!2^396,576,0,-1!0^396,516!0^396,492!0^396,468!0^396,444!0^396,420!0^396,396!0^396,372!0^396,228!0^396,204!0^396,180!0^396,132!0^396,108!0^396,84!0^420,228!0^420,204!0^420,180!0^420,156!0^420,132!0^420,108!0^420,84!0^372,84!0^372,108!0^372,132!0^372,156!0^372,180!0^372,204!0^372,228!0^468,300!0^492,300!0^516,300!0^540,300!0^564,300!0^588,300!0^612,300!0^180,300!0^204,300!0^228,300!0^252,300!0^276,300!0^300,300!0^324,300#502:17895697|17895697|17895697|17895697|17895697|97587473|89478469|17913429|16843008|17830416|17895697|17899793|17895697|17891601|17895697|89478609|107881237|40265318|107374190|419430|89478494|18175317|17895697|17895697|30478609|17830161|89919761|89478469|18175061|17895697|17898769|17895697|18940177|35790866|35791394|35791394|35791394|35791394|35791394|19014178|35660322|17895697|17895441|33624338|35791394|33694241|35791394|35791394|107880994|107365445|107374182|36071014|35791394|35791394|35791394|35791394|35791394|105304610|40199782|72633890|89986389|105272677|107374290|40265318|35791394|35791394|237117986|35790886|35791394|35791394|33694242|419438#
```
