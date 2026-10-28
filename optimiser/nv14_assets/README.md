# Optional N v1.4 video artwork

These assets are extracted from the original `n_v14.swf` supplied with this
project. They are loaded only by the optional video renderer. Importing the
engine or running optimisation does not load them.

The source SWF SHA-256 is
`9db8e7b1e2d15dfa3e378690dd35c17b3818a0cc85dc46e2ae0e9ef4d93b18c1`.
The original SWF, JPEXS and Java are **not** included in this package.
These original game assets remain the property of their respective owners;
this package asserts no new licence over them.

## Contents and registration

`manifest.json` records the source symbol, frame, scale, registration point,
SHA-256 and relative path of each PNG. `pixels_per_unit` means image pixels per
game pixel after applying the original ActionScript MovieClip scale.
`origin` is the image-space location to place at the MovieClip's game position.
It can be fractional or lie outside a cropped image. In particular, the original
door symbol is deliberately offset from its registration point.

The ninja contains original sprite 898 (`testNinjaMCm`) frames 1–104 and frame
106, the first pose of celebration variant 1 used for a completed replay.
Every ninja image uses the same 256 × 256 transparent canvas, origin (128, 128),
and four image pixels per game pixel. Source artwork is scaled to 20%, matching
the original player's MovieClip. Named joint marker positions are also recorded
relative to the player, for future uses; they do not provide ragdoll simulation.
The SWF's full label map is retained as provenance. Labels outside the packaged
frame set are not supported by this initial video exporter.

Object images retain their original registration after transparent cropping.
Their `source_scale` values follow the ActionScript with tile half-width 12:
gold 6%, mine 8%, exit 24%, exit trigger 12%, thwump 18%, launch pad 15%,
bounce block 19.2%, drones 18%, floor guard 12%, turret and rocket launcher 12%,
one-way platform and doors 24%. Locked-door triggers use 7.5%; trap-door triggers
use 5%. Rockets keep their original 100% scale. Dynamic drone eyes are separate
symbols because the game attaches them through ActionScript.

v4.05 adds `particles/`: 28 original MovieClips with 413 frames. The manifest's
`particles.clips` table records each symbol ID, removal frame, per-frame origin,
path and hash. Unlike static objects, these images use unscaled source units
(`pixels_per_unit=2`); `ParticleSystem` supplies the original variable X/Y scale
and rotation at rendering time. The final `removeMovieClip()` frame is excluded.
Gauss frames additionally retain their simple vector line and colour for Flash
hairline behaviour under zero-height/width transforms. The missing
`debugBloodSpurtMC1` export is replaced by the available `debugBloodSpurtMC2`.

v4.06 adds `object_animations/`: **14 clips / 303 frames**, covering gold,
exits, doors, launch pads, gauss body/crosshair, rocket launcher/rocket, drones,
laser blast and static mine/floor-guard/switch timeline states. The manifest's
`object_animations.clips` stores all frames, labels, parsed frame actions,
raw action bytecode and child-symbol types. Gold retains its final frame,
which hides the clip rather than removing it. Stop frames remain packaged.
The extractor rejects independently animated nested children; the laser blast
contains only shapes/morph shapes, all captured in its 13 timeline frames.
The fallback PNGs use `pixels_per_unit=2/source_scale`, applying the source scale once.
Runtime transforms supply rotation and dynamic scaling such as laser blast growth.

v4.07 adds `vectors.json`: **445 original vector frames** (37 static objects,
303 object timeline frames and 105 ninja poses). Each corresponding image
entry has a `vector` key. The sidecar retains ordered solid fills, even-odd
holes, quadratic paths, stroke colours/opacity and original stroke widths in
game coordinates. The manifest records its hash. The renderer applies the
final position, rotation and scale before rasterisation: hairlines remain at
least one output pixel wide, with horizontal/vertical strokes fitted to pixel
centres. This avoids shrinking their thickness by an object's source scale.
Singular source limb transforms remain finite lines. Original PNGs, timeline
actions and particle assets are unchanged and remain usable as a fallback.

## Rebuilding

v4.11 adds `fonts/n_gui.ttf`, copied byte-for-byte from
`n14/fonts/1_n_uni05_53_uni 05_53.ttf` in the supplied `n14.zip` asset export.
This is the game's embedded `n_uni05_53` (`uni 05_53`) GUI font, including its
Western Latin character set; it is used only for optional per-player labels.
The source ActionScript's `ConsoleObject` sets this font at size 8. The font
retains the original game asset ownership described above. To restore it after
rebuilding artwork, copy that TTF into `nv14_assets/fonts/n_gui.ttf`; no font
conversion or system installation is required.

Asset preparation was tested with **JPEXS FFDec 26.3.0**, Java, Pillow and
PyMuPDF. Obtain the official FFDec distribution from:
https://github.com/jindrapetrik/jpexs-decompiler/releases/tag/version26.3.0

```sh
python -m pip install Pillow PyMuPDF
python tools/extract_video_assets.py --swf /path/to/n_v14.swf \
  --ffdec-jar /path/to/ffdec.jar --output nv14_assets
python -m tools.extract_particle_assets --swf /path/to/n_v14.swf \
  --ffdec-jar /path/to/ffdec.jar --output nv14_assets
python -m tools.extract_object_animation_assets --swf /path/to/n_v14.swf \
  --ffdec-jar /path/to/ffdec.jar --output nv14_assets
python -m tools.extract_vector_assets --swf /path/to/n_v14.swf \
  --ffdec-jar /path/to/ffdec.jar --output nv14_assets
```

The tool validates the source SWF hash and exports the selected symbols into a
temporary directory. It does not execute the game's ActionScript. Runtime video
export uses the bundled PNGs and does not require these extraction dependencies.
The base extractor rewrites the manifest, so run the particle extractor after
it, then run the object animation extractor. Both additional extractors can
refresh their own section in an existing compatible base pack. Run the vector
extractor last, and rerun it after refreshing base or object PNG metadata.

The fallback ninja PNGs include one correction to JPEXS raster export. The ninja's original
hairline limbs use transforms with zero height. JPEXS emits an infinite SVG
stroke width and omits those limbs in ordinary PNG export. The extractor follows
the original SVG display list, flattens path coordinates into game coordinates,
and renders Flash hairlines as one game pixel before supersampling at 4×.
It preserves the original limb paths and poses. PyMuPDF rasterises these flattened
SVGs; the resulting antialiasing is not promised to be pixel-identical to Flash.
The tool supports the path subset used by this source ninja, and raises errors
for unsupported transforms or path commands rather than silently guessing.

Object and particle PNG images are exported by FFDec at 2× source resolution.
The vector extractor uses original SVG display lists rather than these PNGs.
It supports the pinned source's solid M/L/Q/Z paths and round strokes, and
rejects unsupported fills, compositing, commands or references. It requires
only Java/JPEXS to rebuild; vector rendering itself requires only Pillow.
Object timeline actions are interpreted only by `nv14_object_visuals.py`.
Particle spawning and removal are implemented separately in the optional
`nv14_particles.py` tracker. Sound, ragdoll physics and general MovieClip actions
are not encoded in the PNGs. See `docs/VIDEO_ENCODING.md` for exact scope,
snapshot-based event reconstruction and deterministic cadence choices.
