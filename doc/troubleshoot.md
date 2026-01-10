# Troubleshoot

- I bypassed the [Ruffle crash on startup when using an nvidia card](https://github.com/clementgallet/libTAS/issues/656) by using Docker instead
- if savestates-related crashes -> use -g gl
- [inputs are not passed to the game](https://github.com/clementgallet/libTAS/issues/652): build from latest commit (1.4.6 is broken)
- crash after loading a savestate: if running with RUST_BACKTRACE=1 gives an audio crash backlog, try with audio set to Disable (besides of Mute)
- Broken determinism: On one of my machine, there is a random number of lag frames at startup, and the loaded background level at startup is different on each playback. In other words, determinism is broken. [This is a known issue with monotonic](https://discord.com/channels/726811446498820198/726811447262183477/1352571040684969988). Fix: launch ruffle with a game once before opening libTAS so it downloads libopenh264.
