# List of all techniques for N

## Common in RTA

### stumbles
### cj
### rcj
### bbbwj (high and low) (+optimization)
### thwump bwj (+optimization)
### thwump push (+optimization)
### Clipping through oneways using corners
### Double bb
### Triple bb
### Double bb w/ bwj
### Triple bb w/ bwj
### Sideways double/triple bb
### chimney jumps
### ceiling push
### ceiling shove (?)
### Getting squeezed (by thwumps mostly)

## Rare in RTA

### Clipping
### bwj

## TAS-only (/optimization)

### cj optimization
### Slope jump optimization
### Clipping through oneways
### Supercharged lp
### lpwj (jumping through lp)
### wj optimization
### Surviving high-speed chimney jumps
### Exit door hitbox optimization
### Jumping to maximize speed
### Turnarounds optimization

### Delaying drone detection

As explained [in the tutorials](https://edelkas.github.io/n/index/docs/tutoC.html#section1), drones do not detect on a fixed frame. The actual frame depends on how busy the objects manager is:
> (D) visibility queries/AI updates
>
> Casting rays through the world is a fairly costly process. in order to maintain a fast framerate, we implemented "staggered" AI updates; any object which requires costly updates (such as raycasts for visibility) can subscribe to the Think event. Each time the simulation is ticked, SOME of the objects are allowed to Think(); this way, the cost of the raycasts/etc. is spread over several frames. The tradeoff is that objects don't respond instantly; there are a few frames between a change in visibility (i.e. the ninja becoming visible to an enemy) and the corresponding change in logic (the enemy being aware of the change in visibility). However, since the game is ticked at 40hz, a delay of even 10 ticks is short enough to not make a substantial difference. 

As a result, it is occasionnaly possible to delay drone detection by interacting with objects. This includes:
- touching bounce blocks
- (todo)

(todo: gif with the beginning of 19-1)

## Other info

(such as directional keys
being blocked after a certain speed)
