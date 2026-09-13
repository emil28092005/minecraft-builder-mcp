#!/usr/bin/env python3
"""Compile concealed station lighting against an explicit observed snapshot.

No world I/O. Each fitting replaces full cubes only: brown glass forms a flush
floor tile or a recessed ceiling lens, with glowstone hidden directly behind it.
The caller applies and independently verifies the resulting checked recipe.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / ".runtime/station-stage07"
GLOW = "minecraft:glowstone"
LENS = "minecraft:brown_stained_glass"
WOOD = "minecraft:spruce_planks"
CREAM = "minecraft:smooth_sandstone"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


survey = _module("station_lighting_survey", ROOT / "scripts/foundation-survey.py")


def compile_lighting(before, station):
    if station["scope"] != before.scope:
        raise ValueError("Station metadata and observed snapshot have different scopes")
    footprint = {tuple(p) for p in station["footprint"]}
    inside = {(x, z) for x, z in footprint
              if all((x + dx, z + dz) in footprint
                     for dx in range(-2, 3) for dz in range(-2, 3))}
    targets = {feet: {(t["x"] + dx, t["z"] + dz)
                      for t in station["interior"]["navigation"][str(feet)]["named_targets"]
                      for dx in range(-1, 2) for dz in range(-1, 2)}
               for feet in (99, 113)}
    # Keep both cabin landings, controls, doorway and immediate approach unchanged.
    lift_exclusion = {(x, z) for x in range(-11, 0) for z in range(-125, -112)}
    changes = {}
    fixtures = []

    def full(state):
        return state.split("[", 1)[0].removeprefix("minecraft:") in survey.FULL

    def put(x, y, z, value, group):
        if (x, z) not in inside or not 97 <= y <= 124:
            raise ValueError(f"Lighting write outside authorized volume: {(x, y, z)}")
        old = before.state(x, y, z)
        if not full(old) or not full(value):
            raise ValueError(f"Lighting may replace full cubes only: {(x, y, z)} {old}")
        if old == value:
            return
        p = (x, y, z)
        if p in changes and changes[p]["block"] != value:
            raise ValueError(f"Lighting layers disagree at {p}")
        changes[p] = {"x": x, "y": y, "z": z, "expected": old,
                      "block": value, "group": group}

    for feet, ceiling in ((99, 110), (113, 123)):
        public = {(p["x"], p["z"]) for p in station["interior"]["walk_points_by_floor"][str(feet)]}
        public &= inside
        candidates = {"floor": set(), "ceiling": set()}
        for x, z in sorted(public - lift_exclusion):
            # Existing flooring mosaics and green/brass bands are not recoloured.
            if (x, z) not in targets[feet] and before.state(x, feet - 1, z) == CREAM:
                neighborhood = {(x + dx, z + dz) for dx in range(-1, 2) for dz in range(-1, 2)}
                if neighborhood <= public and all(
                    before.state(xx, y, zz) in survey.AIR
                    for xx, zz in neighborhood for y in range(feet, feet + 4)
                ) and full(before.state(x, feet - 2, z)):
                    candidates["floor"].add((x, z))
            # Plain spruce cells only: beams, chains, chandeliers, panels and lift
            # geometry are excluded by the observed material and air-column tests.
            if (before.state(x, ceiling, z) == WOOD
                    and full(before.state(x, ceiling + 1, z))
                    and all(before.state(x, y, z) in survey.AIR for y in range(feet, ceiling))):
                candidates["ceiling"].add((x, z))

        for kind in ("floor", "ceiling"):
            chosen = set()
            # A common architectural grid; a maximum two-block adjustment avoids
            # a column, mosaic or ceiling beam without creating dense bright rows.
            for gx in range(-69, 40, 9):
                for gz in range(-139, -83, 9):
                    nearby = [(x, z) for x in range(gx - 2, gx + 3)
                              for z in range(gz - 2, gz + 3)
                              if (x, z) in candidates[kind]]
                    nearby.sort(key=lambda p: ((p[0] - gx) ** 2 + (p[1] - gz) ** 2,
                                                abs(p[0] - gx) + abs(p[1] - gz), p))
                    selected = next((p for p in nearby if all(
                        (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= 36 for q in chosen)), None)
                    if selected is None:
                        continue
                    x, z = selected
                    chosen.add(selected)
                    lens_y, emit_y = (feet - 1, feet - 2) if kind == "floor" else (ceiling, ceiling + 1)
                    group = f"station-lighting:{feet}:{kind}"
                    put(x, lens_y, z, LENS, group)
                    put(x, emit_y, z, GLOW, group)
                    fixtures.append({"floor_walk_y": feet, "kind": kind,
                                     "lens": [x, lens_y, z], "emitter": [x, emit_y, z],
                                     "grid_anchor_xz": [gx, gz]})

    recipe = {"version": 1, "scope": before.scope,
              "blocks": [changes[p] for p in sorted(changes)]}
    metadata = {
        "version": 1, "scope": before.scope, "world_writes": 0,
        "status": "checked lighting candidate; live application and visual review pending",
        "style": "Sparse warm floor tiles and small concealed ceiling lenses on a nine-block grid",
        "grid_spacing": 9, "maximum_anchor_adjustment": 2,
        "minimum_same_layer_fixture_distance": 6,
        "owned_y": [97, 124], "perimeter_setback": 2,
        "changed_states": len(changes), "fixtures": fixtures,
        "fixture_counts": dict(sorted(Counter(f"{f['floor_walk_y']}:{f['kind']}" for f in fixtures).items())),
        "changed_materials": dict(Counter(row["block"] for row in changes.values())),
        "checks": {"only_full_cube_replacements": True, "no_new_collision_obstructions": True,
                   "existing_mosaic_bands_preserved": True, "lift_landings_and_doorway_excluded": True,
                   "floor_fixtures_outside_named_target_neighborhoods": True,
                   "floor_fixtures_have_clear_three_by_three_surrounds": True,
                   "ceiling_lenses_replace_only_plain_spruce": True,
                   "decorative_furniture_and_diorama_preserved": True},
        "limits": "Fixture geometry does not predict the client's final rendered brightness. Review actual Minecraft images after applying and waiting for lighting updates.",
    }
    return recipe, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=STAGE / "after.json.gz")
    parser.add_argument("--station-metadata", type=Path, default=STAGE / "compiled/station.metadata.json")
    parser.add_argument("--output", type=Path, default=STAGE / "lighting")
    args = parser.parse_args()
    recipe, metadata = compile_lighting(survey.load_snapshot(args.before), json.loads(args.station_metadata.read_text()))
    metadata["compiled_at_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["inputs"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (args.before, args.station_metadata, Path(__file__))}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, doc in (("lighting.json", recipe), ("lighting.metadata.json", metadata)):
        destination = args.output / name
        if destination.exists():
            raise FileExistsError(f"Preserve the previous candidate: {destination}")
        destination.write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps({"recipe": str(args.output / "lighting.json"), "changed_states": len(recipe["blocks"]),
                      "fixture_counts": metadata["fixture_counts"]}))


if __name__ == "__main__":
    main()
