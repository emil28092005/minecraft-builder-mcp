# Shacraft layout study

`plan.py` produces a terrain-aware block marking plan and a review image. It reads the approved, big-endian 768 × 768 float height field at `.runtime/terrain-study/natural.f32`; it does not connect to Minecraft or write world blocks.

Run with the terrain study's NumPy / Matplotlib environment:

```sh
.runtime/terrain-study/venv/bin/python scripts/layout-study/plan.py
```

Outputs are `.runtime/layout-study/layout.json` and `layout-preview.png`. The image is a computed planning diagram, not an in-game photograph or a live map. Live world state and safe replacement materials must be checked separately before marking.

The plan retains the Shacraft reference's district order while adapting footprints to the natural valley. A central clock avenue gives spawn a clear destination. The promenade links the station, portals, waterworks, market, gardens and harbor without forcing every trip through spawn. Scenic branches stay subordinate to that main circulation.

The market uses six separate foundations on the calmer southern shoulder. The portal hall is moved north of the lake edge. All building and plaza footprints in the plan lie on dry ground. No route centerline cuts through a building interior by more than a doorway allowance. This is a geometric check, not a human navigation playtest.

JSON coordinates are `[x,z]`, with north in negative Z. Feature polylines and route points are already sampled and rounded. Routes also retain their sparse `waypoints`. `role: bridge` routes have a planned `deck_y` and `abutments` with measured ground height and a future stairs flag. The northeastern bridge needs a substantial east landing stair: its deck is Y86 while that bank is approximately Y69. The three harbor piers and flagship reservation also carry explicit design heights.

Ground contours reserve future buildings; they do not specify large flat platforms. The station and portal hall still span sloped ground, so later architecture should use separate foundations, lower wings and short stairs. The actual terrain, rivers and lake remain the governing geometry. Side trails on mountain shoulders may need stair segments when built.
