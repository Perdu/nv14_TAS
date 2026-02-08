# Information extracted from code digging

## Shift held and triggered

Internally, jump is considered differently if jump was just triggered, or maintained pressed. This can be used to produce glitched demo strings that attempts to jump once per frame (which does not allow for one jump per frame, however).

I digged into the code to check whether this can be done with inputs, but it's not the case. [Relevant part of the code](../external/n_v14_codedump.as#L11709-L11711):
```
var v3 = inList[PINPUT_J];
inList[PINPUT_J] = Key.isDown(this.KEYDEF_J);
inList[PINPUT_JTRIG] = inList[PINPUT_J] && !v3;
```

Manual tests have shown that this code is only called once per frame. Increasing the framerate to 80 or 120 fps does not allow to reset `inList[PINPUT_J]`.

## L+R = nothing

We've been wondering for a while if holding left and right in a frame is strictly the same as doing nothing. [It is](../external/n_v14_codedump.as#L12176-L12178):

```
if (inList[PINPUT_L] && inList[PINPUT_R]) {
    inList[PINPUT_R] = false;
    inList[PINPUT_L] = false;
}
```

## Why we can't jump on every frame

There are two layers of protections against jumping on every frame:
- when registering inputs ([here]() and [here in demos](../external/n_v14_codedump.as#L12208))
- when using inputs to estimate whether to jump or not: logic returns if ninja is already in the jumping state ([here](../external/n_v14_codedump.as#L10908))

The consequence of this is that even if we found some kind of pause-buffering trick to bypass the first layer, we would still be blocked by the second layer. One frame has to pass for the ninja state to change.

Even if we remove these 2 protections through hacks, chimney jumps are still not possible on a one-jump-per-frame basis because the walls are too far away.
