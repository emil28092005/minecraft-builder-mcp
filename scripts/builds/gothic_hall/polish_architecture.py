"""Add the architecture polish layer to the finished v1 scene, without I/O.

The input is scene.Voxels after the eighteen finishing corrections.  V1 modules
remain immutable; removed blocks disappear from this sparse voxel composition.
"""


def build(v):
    """Restore the roof silhouette and add restrained Gothic stone/iron detail."""
    stone = "minecraft:stone_bricks"
    trim = "minecraft:polished_andesite"
    dark = "minecraft:deepslate_tiles"
    glass = "minecraft:gray_stained_glass"
    wall = ("minecraft:stone_brick_wall[east=none,north=none,south=none,"
            "up=true,waterlogged=false,west=none]")

    def stair(material, facing, half="bottom"):
        return (f"minecraft:{material}_stairs[facing={facing},half={half},"
                "shape=straight,waterlogged=false]")

    def bars(north=False, south=False, east=False, west=False):
        flags = {"east": east, "north": north, "south": south, "west": west}
        return "minecraft:iron_bars[" + ",".join(
            f"{name}={str(value).lower()}" for name, value in flags.items()
        ) + ",waterlogged=false]"

    def roof_height(x):
        return 43 - (abs(x - 19) * 16 + 13) // 14

    # Use the actual input mask so a material replacement cannot fill an opening.
    # Preserve the six pale blocks of the heraldic cross on the north facade.
    crest = {(19, y, 10) for y in range(23, 27)} | {
        (x, 25, 10) for x in range(18, 21)
    }
    timber = {
        p: block for p, block in v.blocks.items()
        if 9 <= p[0] <= 29 and 28 <= p[1] <= 40 and 15 <= p[2] <= 54
        and (block.startswith("minecraft:dark_oak_log[")
             or block == "minecraft:dark_oak_planks")
    }
    for p, block in tuple(v.blocks.items()):
        if block == "minecraft:polished_diorite" and p not in crest:
            v.set(*p, trim)
        elif block == "minecraft:tinted_glass":
            v.set(*p, glass)
        elif (block == "minecraft:cut_sandstone"
              and 39 <= p[0] <= 41 and 34 <= p[1] <= 37 and 48 <= p[2] <= 50):
            v.set(*p, "minecraft:gold_block")

    # Remove only the ten old dormer envelopes, then reconstruct the same
    # two-cell roof section.  These envelopes exclude both gables and all trusses.
    for z in (18, 26, 34, 42, 50):
        for x1, x2 in ((10, 14), (24, 28)):
            v.clear(x1, 32, z - 2, x2, 40, z + 2)
            for x in range(x1, x2 + 1):
                high = roof_height(x)
                for y in (high - 1, high):
                    if 32 <= y <= 40:
                        block = dark if y < high else stair(
                            "deepslate_tile", "east" if x < 19 else "west")
                        v.box(x, y, z - 2, x, y, z + 2, block)

    # Three narrow, low dormers per slope: a one-by-two recessed light, three
    # blocks of facade width, and a short roof merging into the original slope.
    for z in (22, 34, 46):
        for face, inner, back in ((10, 11, 13), (28, 27, 25)):
            x1, x2 = sorted((face, back))
            near = back - 1 if face < back else back + 1
            v.clear(min(face, near), 33, z, max(face, near), 34, z)
            for dz in (-1, 1):
                v.box(x1, 32, z + dz, x2, 34, z + dz, dark)
                facing = "south" if dz < 0 else "north"
                v.box(x1, 35, z + dz, x2, 35, z + dz,
                      stair("deepslate_tile", facing))
                v.box(face, 33, z + dz, face, 34, z + dz, trim)
                v.set(face, 35, z + dz, stair("stone_brick", facing))
            v.box(x1, 36, z, x2, 36, z, dark)
            v.box(face, 32, z - 1, face, 32, z + 1, trim)
            v.box(inner, 33, z, inner, 34, z, glass)
            v.set(face, 35, z, stone)
            v.set(face, 36, z, wall)

    # The old bright, chunky ridge is now a dark backing for one thin iron rail.
    v.box(19, 43, 14, 19, 43, 55, dark)
    for z in range(14, 56):
        v.set(19, 44, z, bars(north=z > 14, south=z < 55))

    # Replace full-block mullions with slender rods in their original glazing
    # plane.  Connected horizontal bars provide a clear transom without a grille.
    for center in (18, 26, 34, 42, 50):
        for inner, outside in ((8, 6), (30, 32)):
            for y in range(10, 21):
                v.set(inner, y, center, bars())
            for dz in range(-2, 3):
                v.set(inner, 15, center + dz,
                      bars(north=dz > -2, south=dz < 2))
            # A bevel on the underside of each stepped arch reduces square caps.
            for dz, top in ((-2, 19), (-1, 21), (1, 21), (2, 19)):
                v.set(outside, top + 1, center + dz,
                      stair("stone_brick", "north" if dz < 0 else "south", "top"))
    for x in (18, 20):
        for y in range(29, 37):
            v.set(x, y, 14, bars())
    for x in range(16, 23):
        v.set(x, 33, 14, bars(east=x < 22, west=x > 16))

    # Taper the tips, retaining the full support blocks installed by finish v1.
    for x in (6, 32):
        for z in (14, 22, 30, 38, 46, 54):
            v.box(x, 32, z, x, 33, z, wall)
    for x in (7, 31):
        v.box(x, 36, 12, x, 37, 12, wall)
    for x in (35, 45):
        for z in (43, 55):
            v.box(x, 49, z, x, 50, z, wall)

    # Two new dormer centers cross truss planes. Keep every original timber
    # voxel, including the inclined members, instead of cutting a frame for glass.
    for p, block in timber.items():
        v.set(*p, block)
