"""Small, stateless voxel assets for the Shacraft arrival gardens.

Every public builder returns ``{(x, y, z): full_block_state}`` in local block
coordinates. Origin Y is the first air block above the paving/soil: translate
by Y96 for a paving block at Y95. No builder reads or changes a Minecraft world.
Trees need soil under their trunk; the composer owns foundations, collision
checks, leaf-distance propagation, block connection updates, and placement.
"""

from __future__ import annotations

import json
import math
import random

Position = tuple[int, int, int]
Asset = dict[Position, str]
_DIRECTIONS = ("north", "east", "south", "west")


def _state(material: str, **properties: object) -> str:
    suffix = ",".join(
        f"{key}={str(value).lower()}" for key, value in sorted(properties.items())
    )
    return f"minecraft:{material}" + (f"[{suffix}]" if suffix else "")


def _stair(material: str, facing: str) -> str:
    return _state(material, facing=facing, half="bottom", shape="straight", waterlogged=False)


def _connections(material: str, *directions: str) -> str:
    return _state(material, **{d: d in directions for d in _DIRECTIONS}, waterlogged=False)


def _rotate(asset: Asset, quarter_turns: int) -> Asset:
    """Rotate north to east, including stair backs and fence/bar connections."""
    result: Asset = {}
    direction = {d: _DIRECTIONS[(i + quarter_turns) % 4] for i, d in enumerate(_DIRECTIONS)}
    for (x, y, z), state in asset.items():
        for _ in range(quarter_turns):
            x, z = -z, x
        if "[" in state:
            material, raw = state[:-1].split("[", 1)
            properties = dict(pair.split("=", 1) for pair in raw.split(","))
            properties = {direction.get(k, k): direction.get(v, v) for k, v in properties.items()}
            if quarter_turns % 2 and properties.get("axis") in ("x", "z"):
                properties["axis"] = "z" if properties["axis"] == "x" else "x"
            state = _state(material.removeprefix("minecraft:"), **properties)
        result[x, y, z] = state
    return result


def conifer(height: int = 13, seed: int = 0) -> Asset:
    """A narrow spruce with irregular connected whorls and three clear trunk rows.

    Height is the occupied block count, 11..15. The maximum canopy radius is
    three blocks, and foliage begins at local Y3. Leaves deliberately start at
    distance=7; recompute distances against the composed world before applying.
    """
    if type(height) is not int or not 11 <= height <= 15:
        raise ValueError("Conifer height must be an integer from 11 through 15")
    if type(seed) is not int:
        raise ValueError("Conifer seed must be an integer")
    rng = random.Random(seed)
    phase = rng.uniform(0, math.tau)
    phase2 = rng.uniform(0, math.tau)
    leaves = _state("spruce_leaves", distance=7, persistent=True, waterlogged=False)
    asset: Asset = {}
    for y in range(3, height):
        progress = (y - 3) / (height - 4)
        tier = (0.30, -0.30, -0.65)[(y - 3) % 3]
        radius = max(0.0, 2.95 * (1.0 - progress) ** 0.85 + tier)
        if y == height - 1:
            radius = 0.0
        for x in range(-3, 4):
            for z in range(-3, 4):
                angle = math.atan2(z, x)
                edge = radius + 0.23 * math.cos(4 * angle + phase) + 0.16 * math.sin(3 * angle + phase2)
                edge += rng.uniform(-0.10, 0.10)
                if (x == 0 and z == 0) or math.hypot(x, z) <= edge:
                    asset[x, y, z] = leaves
    # Leave a connected green leader above the last woody branch; overwriting
    # these narrow upper layers with logs creates visible brown pegs at the tip.
    for y in range(height - 5):
        asset[0, y, 0] = _state("spruce_log", axis="y")
    # Angular variation can leave a diagonal-only leaf at a narrow upper tier.
    # Keep the face-connected canopy so no isolated foliage floats beside it.
    connected = {(0, 0, 0)}
    pending = [(0, 0, 0)]
    while pending:
        x, y, z = pending.pop()
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            neighbor = (x + dx, y + dy, z + dz)
            if neighbor in asset and neighbor not in connected:
                connected.add(neighbor)
                pending.append(neighbor)
    return {position: state for position, state in asset.items() if position in connected}


def bench(length: int = 5, facing: str = "north") -> Asset:
    """A 3..5 block overall bench, including its two stone armrests.

    ``facing`` is the seated viewer's direction, not Minecraft's stair-facing
    property: a north-looking seat has a south-facing stair/high back. The
    default occupies X=-2..2, Z=0..1, Y=0; its front opens toward negative Z.
    The fence back has Minecraft's 1.5-block collision height. This is decorative
    seating and does not add a sit interaction.
    """
    if type(length) is not int or not 3 <= length <= 5:
        raise ValueError("Bench overall length must be an integer from 3 through 5")
    if facing not in _DIRECTIONS:
        raise ValueError("Bench facing must be north, east, south, or west")
    first = -(length // 2)
    last = first + length - 1
    asset: Asset = {}
    for x in range(first + 1, last):
        asset[x, 0, 0] = _stair("spruce_stairs", "south")
        asset[x, 0, 1] = _connections("spruce_fence", "north", "east", "west")
    for x in (first, last):
        asset[x, 0, 0] = _state("stone_bricks")
        asset[x, 0, 1] = _state("stone_bricks")
    return _rotate(asset, _DIRECTIONS.index(facing))


def lamp(height: int = 6) -> Asset:
    """A slender warm street lamp with a copper hood and a small brass collar.

    Height is 6..8 occupied blocks. The stone/chain stem occupies one column;
    the 3x3 cross-shaped housing begins at height-3, above pedestrian headroom.
    Its hanging lantern has a full copper block immediately above it. The four
    inward-facing copper stairs form the hood eaves; no trapdoors are used.
    """
    if type(height) is not int or not 6 <= height <= 8:
        raise ValueError("Lamp height must be an integer from 6 through 8")
    collar_y = height - 3
    light_y = height - 2
    roof_y = height - 1
    asset: Asset = {
        (0, 0, 0): _state("chiseled_stone_bricks"),
        (0, 1, 0): _state("stone_brick_wall", east="none", north="none", south="none", up=True, waterlogged=False, west="none"),
        (0, collar_y, 0): _state("gold_block"),
        (0, light_y, 0): _state("lantern", hanging=True, waterlogged=False),
        (0, roof_y, 0): _state("waxed_oxidized_cut_copper"),
    }
    for y in range(2, collar_y):
        asset[0, y, 0] = _state("iron_chain", axis="y", waterlogged=False)
    for x, z, inward in ((-1, 0, "east"), (1, 0, "west"), (0, -1, "south"), (0, 1, "north")):
        asset[x, collar_y, z] = _connections("iron_bars", inward)
        asset[x, light_y, z] = _connections("iron_bars")
        asset[x, roof_y, z] = _stair("waxed_oxidized_cut_copper_stairs", inward)
    return asset


def describe(asset: Asset) -> dict:
    """Compact occupied bounds and ground contact cells for the layout composer."""
    if not asset:
        raise ValueError("Cannot describe an empty asset")
    low = [min(p[i] for p in asset) for i in range(3)]
    high = [max(p[i] for p in asset) for i in range(3)]
    return {
        "blocks": len(asset),
        "min": dict(zip(("x", "y", "z"), low)),
        "max": dict(zip(("x", "y", "z"), high)),
        "size": dict(zip(("x", "y", "z"), (high[i] - low[i] + 1 for i in range(3)))),
        "ground_contacts": sorted([x, z] for x, y, z in asset if y == 0),
        "materials": sorted({state.split("[", 1)[0] for state in asset.values()}),
    }


if __name__ == "__main__":
    print(json.dumps({
        "coordinate_convention": "Local Y0 is first air above paving; add Y96 over paving Y95.",
        "conifer": describe(conifer()),
        "bench_north": describe(bench()),
        "lamp": describe(lamp()),
    }, indent=2))
