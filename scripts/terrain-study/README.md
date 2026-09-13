# Shacraft terrain composition study

This is an **offline prototype** responding to the first lobby terrain's rectangular platforms and repetitive slopes. The original study did not alter a live world. Its exact height field is now available through the production `shacraft-natural-v1` initial-world profile; it still does not extend the production MCP recipe schema.

## Findings and design decisions

The original recipe combines three correlated octaves of grid-based value noise, then flattens large rectangular areas. It also paints grass on every exposed top step regardless of slope. The screenshots show both geometric platform edges and repetitive green/brown contour bands. Adding more octaves alone cannot remove those platform boundaries.

[Red Blob Games](https://www.redblobgames.com/maps/terrain-from-noise/) explains independent octave sampling, Simplex noise as a way to reduce directional artifacts, ridged transformations, and elevation redistribution. The study uses seeded OpenSimplex2S with distinct fields for broad relief, ridges, coordinate warping and fine detail.

[libnoise tutorial 5](https://libnoise.sourceforge.net/tutorials/tutorial5.html) separates the terrain-type control map from mountain and lowland height fields. Here explicit curved mountain corridors provide artistic control: north is the main skyline, side ranges are lower, and the central valley stays comparatively calm. Mountain detail is weighted by those corridors instead of covering the entire map uniformly.

[FastNoiseLite's documentation](https://github.com/Auburn/FastNoiseLite/wiki/Documentation) provides fBm, ridged fractals, octave weighting and domain warping. The prototype uses two independent low-frequency fields to displace X/Z coordinates before evaluating terrain, producing irregular ridge paths and water margins. This is a modest 27-block warp, not unlimited distortion.

There are no rectangular plateau features in the study. Broad smooth hills leave space for architecture without committing to enormous flat pads. Later construction should flatten only the actual footprint and blend the foundation into the slope. Natural terrain alone does not guarantee walkable routes; those need a separate route/grade pass after the silhouette is selected.

The lakes and connected river paths share Y=48. Shorelines arise from the intersection between the computed ground and that water plane. River cuts are curved and variable in width. The shape is authored and noise-modulated; it is **not** a drainage or hydraulic erosion simulation. Small remaining angular changes around path vertices should be replaced by spline sampling in a production implementation.

## Prototype parameters

- Broad lowland field: scale 220 blocks, amplitude 11, 4 octaves.
- Mountain ridge field: scale 85, 5 octaves, gain 0.48, lacunarity 2.07, weighted strength 0.7.
- Warp fields: scale 165, 3 octaves, displacement 27 blocks.
- Fine detail: scale 17, amplitude about 1.2–4.4 depending on mountain influence.
- Comparison palette: slope-dependent rock/grass and depth-dependent water, **identical for both versions**. This isolates geometry; it is not a Minecraft material or shader preview.

## Reproduce

From the repository root, with the project Java 25 runtime on PATH:

```bash
mkdir -p .runtime/terrain-study
javac -cp terrain-world-plugin/target/terrain-world-plugin-0.1.0-SNAPSHOT.jar -d .runtime/terrain-study \
  scripts/terrain-study/NaturalTerrainStudy.java
java -cp .runtime/terrain-study:terrain-world-plugin/target/terrain-world-plugin-0.1.0-SNAPSHOT.jar \
  NaturalTerrainStudy examples/terrain/shacraft-lobby-world.json .runtime/terrain-study
python3 scripts/terrain-study/render.py
```

Rendering requires numpy and matplotlib. The binary samples are 768×768 big-endian float32, row-major Z then X. No upsampling, erosion or post-sculpting is hidden in the renderer. Perspective views sample every fourth column and use true vertical scale.

Outputs: `docs/references/shacraft-terrain-study-plan.png`, `shacraft-terrain-study-perspective.png`, and `shacraft-terrain-study.json`. These are computed previews, **not screenshots**. The original comparison images predate the version 2 world. The production height field is tested against the SHA-256 of all 589,824 original prototype float samples.

## Third-party source

`../../terrain-world-plugin/src/main/java/io/github/minecraftbuilder/terrainworld/noise/FastNoiseLite.java` is upstream Java source with only a package declaration added from [Auburn/FastNoiseLite](https://github.com/Auburn/FastNoiseLite), pinned to commit `785f37a9ad76e283586a379675085f2063ae03f7`. Its MIT license and copyright notice are preserved at the top of the file. The MIT notice is also bundled in the production jar under `META-INF/LICENSE-FastNoiseLite.txt`.
