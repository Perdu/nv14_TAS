# List of all techniques for N

Todo: detail all techniques, ideally with gifs, similar to what can be found [here](https://tasvideos.org/GameResources/NES/Rockman). Gifs were produced using method described [here](notes.md).

Links:
- [Thread on air speed](https://forum.droni.es/viewtopic.php?f=20&t=10336&sid=569eab4beeecd814135f67b0fa574a3a)
- [Stumbles](https://discord.com/channels/197765375503368192/199460839252688896/1431062811903266957)
- [Hitboxes sizes](https://discord.com/channels/197765375503368192/199460839252688896/1437946735665352714)
- [Finding coordinates for tile bwj](techniques/bwj.md)
- [Drone detection](https://discord.com/channels/197765375503368192/199460839252688896/1458621494224490527)
- [Metanet tutorial on N physical collision system](https://edelkas.github.io/n/index/docs.html)
- [Nclone, Python emulator of the N++ engine (some parts are similar to N v1.4)](https://github.com/SimonV42/nclone)
  - [Nclone: Part handling ceiling crushing](https://github.com/SimonV42/nclone/blob/842190b2a216579b5b5c551e0a0b4505fc3381cc/nsim.py#L299-L302)
- [Float-precise trick giving pj on flat ground in N++](https://discord.com/channels/197765375503368192/199460839252688896/1469859845107876041)
- [Slipping through one-ways](https://forum.droni.es/viewtopic.php?f=17&t=9096). [Map](https://www.nmaps.net/218275). [Additional findings on right and down-facing one-ways](https://discord.com/channels/197765375503368192/199460839252688896/1537543614190583818).
- [Superpowered launchpads + surviving falls from launchpad height](https://discord.com/channels/197765375503368192/199460839252688896/1477389682181668915)
- [In-between-tile slope jumps](https://discord.com/channels/197765375503368192/199460839252688896/1483352718503444581)
- [2-frames depenetration](https://discord.com/channels/197765375503368192/199460839252688896/1486849823285051565)
- [Locked-door walljump](https://discord.com/channels/197765375503368192/199460839252688896/1488577463406690394)
- [Triple jump on 4-tile/8-tile sections](https://discord.com/channels/197765375503368192/199460839252688896/1510699050075164835)

## Depenetration

@todo: this is not correct

The game handles speed in a weird way. Instead of storing a speed value for the player, it computes it on every frame based on difference of position in the last frame. Since collision with surfaces displace the player, we can exploit this to gain speed when hitting curved surfaces and corners. More specifically, maximizing theorical penetration inside a tile will lead the game to maximize its depenetration and give a speed boost. As such, when speed is needed (a.k.a most of the time), we try to get the maximize theorical tile penetration on corners and slopes to get speed boosts.

## Walljump
In this game, you can jump on walls! Woop woop!

## Stumbles

In order for a jump to be valid, the player must be touching a surface for a minimum of 2 frames. This means a player landing on a surface and being immediately ejected will not be able to jump. This makes surfaces like downwards-curved slopes chaotic as this ejection depends on depenetration, which a player can't predict in real time. Hitting a surface for a single frame is called a stumble, and pretty much a pain for rta players in this version of the game when unintentional.
Stumbles are not necessarily bad, however, as some of them can be used to get speed boost using depenetration. The final run also contains a lot of them, because some stumbles do not slow the player down despite what is visually intuitive, and therefore constitute the best trajectory, better than avoiding the stumble altogether.

49-2 (non-slowing stumble)

## Corner Jump (cj)

Corner jumps are the process of jumping on the corner of a tile. This jumping possibility is pretty much what makes this platforming game more interesting than other platforming games as they allow players to be creative with possible trajectories. By maximizing depenetration, they can be used to get a speed boost.
A player must touch the corner for 2 subsequent frames or the cj will fail.

![Corner jump](gifs/cj_03-2.gif)

## Reverse Corner Jump (rcj)

A rcj is the same as a cj, but the directional key is either released or the opposite directional key is pressed. This leads the player to jump in a direction that is the one that would be obtained with a regular cj, leading to another set of possible routing.

![Reverse Corner jump](gifs/rcj_05-4.gif)

## Perpendicular (reverse) Jump (pj)

A pj is the process of jump with a released or opposite directional key when running on a slope. This leads to a jump perpendicular to the slope.

![Perpendicular (reverse) Jump](gifs/pj_08-2.gif)

## Corner kick (ck)

A corner kick (ck) is a jump on a corner when falling on it. This jump is pretty horizontal and can get a high speed if depenetration is maximised

![Corner kick](gifs/ck_17-2.gif)

## Bounceblock Backward Walljump (bbbwj) (high and low) (+optimization)

A bbbwj visually looks like a corner jump on a bounceblock. It is, however, just a walljump on a bounceblock, as corner jumps are not possible on bounceblocks. The player is however jumping on the side of the bounceblock opposite to them, giving them a speed boost. This is a pretty precise trick but very doable RTA. Since bounceblocks get displaced by the player when near them, it is not difficult to do in a TAS, and requires much less precision then similar jumps on hard surfaces.

There are several brands of bbbwj.

If the player if coming from the top of the bbbwj, it's a high bbbwj and looks like a corner kick.

High: ![Bounceblock Backward Walljump (high)](gifs/bbbwj_high_90-0.gif)

If the player comes from beneath the bb, it's a low bbbwj and it appears like the player is jumping on the bottom corner of the bb, like a bwj.

Low: ![Bounceblock Backward Walljump (low)](gifs/bbbwj_low_00-0.gif)

If the player arrives from the bottom of the bb and the opposite side of the bb in a way that it doesn't displace it horizontally, then it's a side bbbwj. This brand of bbbwj is much more precise than other ones because the player must land on the exact 0.1 pixel range allowing the jump on the side of the bb without benefitting from bb displacement and was therefore never seen RTA.

Side: ![Bounceblock Backward Walljump (side)](gifs/bbbwj_side_14-4.gif)

## Thwump bwj (+optimization)

bwj are also possible on thwumps. Since thwumps are also moving, the possible displacement they give to the player if greater than hard surfaces, which can lead to immense speed boosts.

![Thwump bwj](gifs/thwump_bwj_06-4.gif)

## thwump push (+optimization)

A thwump push is the same as a thwump bwj, but without jump. The player just benefits from the depenetration displacement, without jumping. Even without jumping, this can give large speed boosts.

![Thwump push](gifs/thumpw_push_17-1.gif)

## Clipping through oneways

A very well-known trick in RTA runs. While oneways supposedly only allow the player to go through them in one direction, geometry can in many situations be abused to force passage in the opposite direction.
One method is to jump on a corner of a well is above the oneway.
Another way is to use the level geometry to get depenetrated at the other side of the oneway by a downwards corner push.
Finally, bounceblocks and thwumps can be abused to get pushed through a oneway.
Additionally to these common techniques, abusing float rounding can extremely rarely be used to go through a oneway. This only works if the oneway is in a position that is a power of 2 and is never used anywhere in the TAS.

## Multiple bounceblock jumps
Bounceblocks are the funniest object in the game. Player displace them from their center when pushing them, up to a point where the bounceblock will return to their center, pushing the player back. With the right timing, players can get a speed boost from this mechanism, as if the "bounced" on it.
Jumping when the bb is returning to its center can lead the bounceblock to give the player a speedboost, then touch them again, making another jump possible. This is called a double bb jump, very easy to do in real time and very common in RTA runs.
But this is not all. With the correct timing, the player can subsequently jump up to 4 times in a row on the same bb. Triple bb jumps are harder but doable RTA, while quad bb jump require precise timing and initial positioning on the bb, which is probably TAS-only.

![Quadruple bbwj](gifs/quad_bbwj_10-2.gif)
Slowed: ![Quadruple bbwj](gifs/quad_bbwj_10-2_slowed.gif)

18-4

Multiple bb jumps can be done on both the top and side of bounceblocks.

## Bounceblock Corner Double (bbcd)

bbcd are pretty much the combination of a bbbwj and a double bbj. While doing a double bbj, leaving the bounceblock on the right timing can lead to a jump on its side instead of its top, giving the player both a vertical and horizontal speed boost.

![Bounceblock Corner Double](gifs/bbcd_19-1.gif)

## Bounceblock Corner Triple (bbct)

Same as bbcd, but with one additional jump on the top of the bb before leaving it. This is a double bbj followed by a bbbwj, giving both a horizontal and a large vertical speed boost. This is a precise trick and probably TAS-only.

![Bounceblock Corner Triple](gifs/bbct_33-2.gif)

## Chimney jumps

Chimney jumps are the process of jumping repeatedly in a small upwards corridor. In common 1-tile-tall chimneys, a jump is possible every 2 frames, giving a very quick vertical speed boost. This usually requires careful speed management, since high speeds have a high chance of crushing the player on the walls, because it gets penetrated too much inside the surface, which the game reacts to by killing the player. Note that this is not the same logic as falling on the floor, which purely checks if the player vertical speed if bigger than 7.

![Chimney jumps](gifs/chimney_jumps_02-4.gif)
![Chimney jumps (slowed)](gifs/chimney_jumps_02-4_slowed.gif)

## Corner shove

Jumping in a corner of a wall and a ceiling gives the player a downwards boost.

![Corner shove](gifs/corner_shove_11-1.gif)

## Corner pushes

Similarly to corner jumps, jumping or falling into a corner can lead to speed boosts of various sizes. We distinguish several cases:
- A player can use a corner (or end of a tile) place above it when running to get a small horizontal speed boost due to depenetration. This is called an upwards corner push, or a bump.
- when a player is falling, approaching a downwards slope or a corner to get pushed by it to gain some negative vertical speed is called a downwards corner push.
Ledge grabs (wallsliding for 1 frame near the end of a surface) are probably functionally equivalent to downwards corner pushes.
- Falling into a corner to get pushed by it due to depenetration is called a bounce. Since falling can easily get high speed, the depenetration and thus the speed boost obtained from a bounce can be huge and visually impressive.

![Corner push (sideway, moving upwards)](gifs/corner_shove_17-3.gif)

Sideway (moving downwards) (bounce) : 25-2, 57-0 but there are better ones

Downwards : 27-2
(ledge grabs are probably just downwards corner pushes)

upwards (bump): 10-2

## Getting squeezed

Being squeezed in-between two surfaces, two objects or and object and a surface will lead to depenetration that can lead to huge speed boosts.
The most common situation is to be squeezed by a thwump into a surface or another thwump, since thwumps are moving objects with jumpable sizes.

![Thwump squeeze](gifs/thwump_squeeze_88-4.gif)

Sometimes, bounceblocks can be exploited for squeeze as well, although with less effectiveness due to their adjustment to the player's presence.
While it's possible to be squeezed between hard surfaces for large speed boost, this is mostly done in demo levels designed for that purpose and (almost?) not seen in this run.

## lp+wj

Jumping on a wall after a launchpad launch is a very common RTA trick to get a large vertical speed boost

![Launchpad + Walljump](gifs/lpwj_00-0hs.gif)

## Angled lp+wj

When positioned correctly, a wj straight after a lp launch (or on the same frame?) lead to an horizontal speed boost, additionally to the large vertical speed boost of a regular lp+wj

![Angled launchpad + walljump](gifs/angled_lpwj_00-0hs.gif)

While less common, that can also be done on non-horizontal launchpads

![launchpad + wall on a 45 degree lp](gifs/45angled_lpwj_29-1.gif)

## 1f wallslide
Wallslides only start decreasing the player's speed if they are held for at least 2 frames. Holding a wallslide for a single frame can be useful to correct the position of a downards corner push (ledge grab), or to push a bounceblock away without losing speed.


## Taking only 1 stacked object

If several objects are stacked on top of one another, hitting their hitbox for only one frame can lead to only the top one being collected. Also, their hitbox may not overlap perfectly, making it possible to collect one and not the other one. Since hiding locked doors or trapdoor switches behind gold is common, this is a common RTA technique in highscore runs to collect the golds anyway. It's also used for instance in 00-1 to collect the door switch without triggering the underlying switch to open a trapdoor and close the way to the exit door.

00-1 but visibility is not the best

## Clipping

Similarly to many games, getting a large enough speed can be exploited to clip through objects and wall, due to the collision logic not checking every step in the way.
Clipping through walls is extremely rare as the necessary speed to clip through a 1-tile-size wall is hardly reachable. Clips through smaller surfaces are sometimes possible, although usually mostly shown in demo levels.
Clips through objects such as trapdoor are easier, although mostly seen in cheated runs, demo levels, or when the level geometry makes it doable to get large speed RTA.

## Backwards walljump (bwj)

RTA-rare

The game does not check whether the player is facing a surface to jump on it. It only checks whether the player is within a 0.1 pixel range from the surface. Thus, with precise positioning, it's possible to jump off a tile while going in the opposite direction. This is an extremely precise trick and almost TAS-only, except in rare levels where the setup makes it easy to pull off RTA.
However, a very easy version of it is to simply turn one frame before jumping off a wall when falling next to it. This can sometimes save a frame.

07-2

19-2

Tile: ![backwards walljump on special tiles](gifs/bwj_tile_08-3.gif)

Turning 1 frame before jumping off the wall (slowed): ![Backwards walljump (turning while falling)](gifs/bwj_turn_01-4.gif)

Upwards: middle of 27-1

Tiles: 08-2, 18-3

### Tile wj

@RTA-rare

@todo: better name
With precise positioning, you can do a normal walljump on a extremely small tile.

![Walljump on small tiles](gifs/tile_bwj_06-2.gif)

### Tile rcj

@RTA-rare

@todo not sure about that one, possibly move to cj but verify what I meant
Corner jumps are not only possible on 45-degree corners, but on any kind of angled surface. On small-angle ones, this can require very tight positioning

## Slope jump neutral jumps
@todo

## Walljump optimisation

@TAS-only

Since walljumps are valid within a 0.1 pixel range from the wall, being as far away from the wall within that range can lead to up to a 0.1 pixel gain from that walljump, which can occasionally be the missing 0.1 pixel you need to save a frame.
An easy way situation to do this is to turn 1f before jumping from a wall to do a bwj (see [bwj](bwj)).

## Jumping through lp / Launchpad Walljump (lpwj)

@RTA-rare @TAS-only

Walljumps are valid within 0.1 pixel away from the wall. Launchpads, however, only trigger if the player directly touches them. As a consequence, there is a very small gap that allows a player to jump on a wall even if there is a launchpad against it. It is extremely rarely done RTA as the precise positioning to get this requires a precise setup (such as in the 89-2 speedrun 0th) or an insane amount of luck.

65-4, 89-2

## Exit door hitbox optimisation.
The player's hitbox is a 10-pixel circle, while the exit door's one a 12-pixel one. As a consequence, running straight into the exit door is not the faster way to reach it. A precisely timed jump can get a trajectory that touches the hitbox slightly earlier, which can lead to a frame save. Similarly, when coming from the top, getting into the right position can occasionally save a frame.

## Jumping to maximize speed
Running is not the fastest way to travel horizontally without using depenetration-based techniques in N. Airspeed is slightly faster than running speed (although that depends on the exact time spent in-air, see graph here @todo), which means that it is usually faster to maximize time spent in-air rather than running on the ground. Roughly 1 pixel (?@todo) can be saved off a full-level horizontal traversal by jumping as much as possible, which can occasionally save a frame.

## Turnaround optimization
A turnaround is simply the process of slowing down near the edge of a surface in order to go to the opposite direction after falling from it. This is surprisingly hard to optimise manually. Usually, an optimised turnaround looks visually different, as instead of floating off the surface, the player seems to be sticking then falling from it.

![Optimized turnaround](gifs/optimized_turnaround_19-0.gif)

## Stuttering to stay grounded
@todo

## Angled cj on downards-facing corners
@todo, found by the optimiser

## Using 1f-wallslides to push bbs without slowing down
@todo, found by the optimiser

73-1

See also 29-0, used to setup a quad bb

## Delaying drone detection

As explained [in the tutorials](https://edelkas.github.io/n/index/docs/tutoC.html#section1), drones do not detect on a fixed frame. The actual frame depends on how busy the objects manager is:
> (D) visibility queries/AI updates
>
> Casting rays through the world is a fairly costly process. in order to maintain a fast framerate, we implemented "staggered" AI updates; any object which requires costly updates (such as raycasts for visibility) can subscribe to the Think event. Each time the simulation is ticked, SOME of the objects are allowed to Think(); this way, the cost of the raycasts/etc. is spread over several frames. The tradeoff is that objects don't respond instantly; there are a few frames between a change in visibility (i.e. the ninja becoming visible to an enemy) and the corresponding change in logic (the enemy being aware of the change in visibility). However, since the game is ticked at 40hz, a delay of even 10 ticks is short enough to not make a substantial difference. 

As a result, it is occasionnaly possible to delay drone detection by interacting with objects. This includes:
- touching bounce blocks
- (todo)

(todo: gif with the beginning of 19-1)

## Locked door walljump

@TAS-only

With extremely precise positioning, it's possible to jump off the side of a locked door.

![Locked door walljump](gifs/locked_door_wj_customlevel.gif)

```
$###00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000|5^370.9,333.7797758985!9^348,348,1,0,14,14,1,0,-1#999:36573457#
```

## NaN-corrupted rockets

@TAS-only

Discussed [here](https://discord.com/channels/197765375503368192/199460839252688896/1537289891619274752), found by Raif using ChatGPT.

@todo
Generally the conditions to trigger the glitch end up with the ninja inside the rocket, but it identified depenetration by thwumps or one-ways, or getting launched by a launchpad as ways to get outside the radius of the rocket

![Nan-corrupted rockets explanation by ChatGPT](nan_corrupted_rockets.webp)

Example levels:
```
$homing NaN probe#synthetic##00001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000|5^296,110!10^130.4407378886105,110!2^192,125.15,1,-1#45:17895697|17895697|17895697|17895697|17895697|17895697|273#

$homing NaN thwomp probe#synthetic##00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000|5^214.51985059900008,40!10^218.11324323834063,419.77413270312553!8^215.98,293.4123378107756,1#70:0|0|0|0|0|0|0|0|35791394|35791394#

$homing NaN one-way probe#synthetic##00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000|5^214.51985059900008,40!10^218.11324323834063,419.77413270312553!7^215.98,296.4123378107756,3#70:0|0|0|0|0|0|0|0|35791394|35791394#
```

## Half-tile airjump

@TAS-only

Discussed [here](https://discord.com/channels/197765375503368192/199460839252688896/1537877832401817610), found by Raif using ChatGPT.

Requires float-perfect positioning.

Only works on the right side of exposed horizontal half-tiles

(AI-generated explanation)
> Explanation: Zero-normal half-tile airjump
> The faulty branch is in ProjCircle_Half, original 4863–4883. Use a half tile with vertical normal (signx=0) and put the player centre exactly at the tile's positive-x side midpoint:
> player centre = (tile.cx + 12, tile.cy)
> Because cell ownership is floor(position/24), the point belongs to the cell on the right and reaches the half tile as a horizontal neighbour with oH=+1, oV=0. The endpoint vector has length zero. The fallback incorrectly assigns:
> vx = signx / sqrt(2) = 0
> vy = oV    / sqrt(2) = 0
> It then calls ReportCollisionVsWorld(0,0,0,0,t). That does not move the player, but ny==0 is classified as a wall (original 10041–10068), producing NEAR_WALL=true and wallN=(0,0) while still airborne. A jump trigger while falling reaches the walljump branch (10919–10932) and calls Jump(0,-0.7), giving an immediate 2.1 px pure vertical displacement.
> Verified state:
> half tile centre: (156,156), TID_HALFd
> player centre:    (168,156)
> without jump:     alive, IN_AIR, NEAR_WALL, wallN=(0,0), no correction
> with JTRIG:       y=153.9, state=JUMPING
> The negative-x endpoint belongs to the half tile's own cell and takes the central-tile path; in isolated geometry it produces a large correction and explosive death. The asymmetry is therefore essential. The useful orientation is one where the vertical escape moves away from solid geometry.

```
$Half-tile airjump - normal start#OpenAI##000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000N1000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001000000000000000000000010000000000000000000000100000000000000000000001|5^486.22300650983,46.82412288866287!7^486.22300650983,68.82412288866287,3#300:35791394|35791394|35791394|17895970|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|17895697|47255825|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|35791394|34|0|0|0|0|0|0|0|0|0|0|0|0|0#
```

# Unused glitches

## Pause glitch

Pressing shift on the frame after the game is unpaused (with p) causes further shift press to be tied to pause. The same is true if we press shift and p for the same amount of frames. [This does no seem to allow for any kind of pause-buffering glitch](code_digging.md#why-we-cant-jump-on-every-frame).

Similar effects can be obtained by configuring pause to use the same key as shift.

In case that ever becomes relevant: we can pause-unpause in only 2 frames with the `Escape - p` sequence.

Note that pressing Space and p on the same frame will do nothing (probably because [pause is immediately escaped](../external/n_v14_codedump.as#L23632), or because pressing p somehow removes other inputs).

# Other info

@todo

When the player's horizontal speed exceeds 14 (? @todo), directional key presses are not registered anymore, making it impossible to navigate the player at high speed.

# Demo validation
TAS has been made level-by-level, and saved in the form of demo strings. These demo strings can be replayed within the game, which makes for an easy in-game validation of the TAS, eliminating any possible issue with emulation.
This does not 100% guarantee that the TAS is console-verified, though. Due to a bug in the demo strings parsing logic, demos containing impossible jump-on-every-frame sequences (which we call "jjj") are accepted and replaced as valid runs. We have found no pause-buffering bug to produce these sequences in the live game. We, however, made sure no jjj sequence was present in the final TAS.
