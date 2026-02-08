# Unused glitches

## Pause glitch

Pressing shift on the frame after the game is unpaused (with p) causes further shift press to be tied to pause. The same is true if we press shift and p for the same amount of frames. [This does no seem to allow for any kind of pause-buffering glitch](code_digging.md#why-we-cant-jump-on-every-frame).

Similar effects can be obtained by configuring pause to use the same key as shift.

In case that ever becomes relevant: we can pause-unpause in only 2 frames with the `Escape - p` sequence.

Note that pressing Space and p on the same frame will do nothing (probably because [pause is immediately escaped](../external/n_v14_codedump.as#L23632), or because pressing p somehow removes other inputs).
