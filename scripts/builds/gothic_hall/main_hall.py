"""Main Gothic hall geometry in local coordinates; pure voxel composition, no IO."""


def build(v):
    """Compose the north-facing hall, hollow interior, roof, and attached masonry."""
    stone = "minecraft:stone_bricks"
    ashlar = "minecraft:polished_andesite"
    plinth = "minecraft:andesite"
    pale = "minecraft:polished_diorite"
    dark = "minecraft:deepslate_tiles"
    glass = "minecraft:tinted_glass"
    wood = "minecraft:dark_oak_planks"
    oak = "minecraft:spruce_planks"

    def slab(material="stone_brick", half="bottom"):
        return f"minecraft:{material}_slab[type={half},waterlogged=false]"

    def stair(material, facing, half="bottom"):
        return (f"minecraft:{material}_stairs[facing={facing},half={half},"
                "shape=straight,waterlogged=false]")

    def log(axis="y"):
        return f"minecraft:dark_oak_log[axis={axis}]"

    def roof_height(x):
        return 43 - (abs(x - 19) * 16 + 13) // 14

    def pinnacle(x, z, base, height=8):
        """Square masonry shaft with a cap, taper, and slender stone finial."""
        v.box(x - 1, base, z - 1, x + 1, base, z + 1, ashlar)
        v.box(x, base + 1, z, x, base + height - 3, z, stone)
        v.box(x - 1, base + height - 4, z - 1,
              x + 1, base + height - 4, z + 1, slab())
        v.set(x, base + height - 2, z, ashlar)
        v.set(x, base + height - 1, z, slab())

    def side_window(face, inner, center, bottom, tops, trim_face):
        """Carved pointed aperture with glass one block behind the wall face."""
        half = max(tops)
        lo, hi = sorted((face, inner))
        for dz in range(-half, half + 1):
            top = tops[abs(dz)]
            v.clear(lo, bottom, center + dz, hi, top, center + dz)
            v.box(inner, bottom, center + dz, inner, top, center + dz, glass)
            v.set(trim_face, top + 1, center + dz, ashlar)
        for dz in (-half - 1, half + 1):
            v.box(trim_face, bottom - 1, center + dz,
                  trim_face, tops[half] + 1, center + dz, ashlar)
        v.box(trim_face, bottom - 1, center - half - 1,
              trim_face, bottom - 1, center + half + 1, pale)
        # Alternating vertical/horizontal pieces describe the arch, rather than
        # colouring an arch outline on an otherwise flat facade.
        for dz in range(-half, half + 1):
            top = tops[abs(dz)]
            if dz:
                facing = "south" if dz < 0 else "north"
                v.set(trim_face, top + 2, center + dz, stair("stone_brick", facing))
        v.set(trim_face, tops[0] + 2, center, slab())

    def front_aperture(z_face, z_glass, center, bottom, tops):
        for dx in range(-max(tops), max(tops) + 1):
            top = tops[abs(dx)]
            v.clear(center + dx, bottom, z_face, center + dx, top, z_glass)
            v.box(center + dx, bottom, z_glass, center + dx, top, z_glass, glass)

    # Dense foundations; two genuinely hollow occupied storeys above them.
    v.box(7, 0, 13, 31, 0, 56, plinth)
    v.box(7, 1, 13, 31, 1, 56, ashlar)
    v.box(7, 2, 13, 31, 27, 56, stone)
    v.clear(9, 2, 15, 29, 5, 54)
    v.clear(9, 7, 15, 29, 43, 54)
    v.box(9, 6, 15, 29, 6, 54, wood)
    v.box(17, 6, 15, 21, 6, 53, ashlar)
    for x in (9, 29):
        v.box(x, 6, 15, x, 6, 54, stone)
    for z in (15, 54):
        v.box(9, 6, z, 29, 6, z, stone)

    # Continuous ledges make the raised main floor legible from the courtyard.
    for x in (6, 32):
        v.box(x, 0, 13, x, 1, 56, ashlar)
        v.box(x, 5, 13, x, 5, 56, stone)
        v.box(x, 6, 13, x, 6, 56, slab("smooth_stone"))
        v.box(x, 25, 12, x, 25, 57, ashlar)
        v.box(x, 26, 12, x, 26, 57, pale)
        v.box(x, 27, 12, x, 27, 57, slab())
    for z in (12, 57):
        v.box(6, 5, z, 32, 5, z, stone)
        v.box(6, 6, z, 32, 6, z, slab("smooth_stone"))
        v.box(6, 25, z, 32, 25, z, ashlar)
        v.box(6, 26, z, 32, 26, z, pale)
    # Timber is visible in the short shadow immediately below the roof edge.
    for x in (7, 31):
        v.box(x, 26, 15, x, 26, 54, log("z"))
        for z in range(15, 55, 2):
            v.set(x, 25, z, stair("spruce", "east" if x == 7 else "west", "top"))

    bays = (18, 26, 34, 42, 50)
    piers = (14, 22, 30, 38, 46, 54)
    for center in bays:
        for face, inner, trim in ((7, 8, 6), (31, 30, 32)):
            side_window(face, inner, center, 10, {0: 22, 1: 21, 2: 19}, trim)
            # The recessed central mullion and transom divide four dark lancets.
            v.box(inner, 10, center, inner, 20, center, ashlar)
            v.box(inner, 15, center - 2, inner, 15, center + 2, ashlar)
            v.set(inner, 21, center, wood)
            # A modest three-wide basement window below each high bay.
            side_window(face, inner, center, 2, {0: 4, 1: 3}, trim)
            v.set(inner, 2, center, wood)
            # Deep, bevelled main-window sill; its ends connect to the piers.
            outside = trim - 1 if trim < 19 else trim + 1
            v.box(outside, 8, center - 3, outside, 8, center + 3, slab())
            v.box(trim, 9, center - 3, trim, 9, center + 3, stone)

    # Each buttress has an outward foot and two real setbacks.
    for z in piers:
        for left in (True, False):
            if left:
                foot, middle, shaft, outside = (3, 7), (4, 7), (5, 7), 5
            else:
                foot, middle, shaft, outside = (31, 35), (31, 34), (31, 33), 33
            v.box(foot[0], 0, z - 1, foot[1], 1, z + 1, plinth)
            v.box(middle[0], 2, z - 1, middle[1], 5, z + 1, stone)
            v.box(middle[0], 6, z - 1, middle[1], 6, z + 1, slab("smooth_stone"))
            v.box(shaft[0], 7, z - 1, shaft[1], 11, z + 1, stone)
            v.box(shaft[0], 12, z - 1, shaft[1], 12, z + 1, ashlar)
            v.box(min(outside, 7 if left else 31), 13, z,
                  max(outside, 7 if left else 31), 24, z, stone)
            v.set(outside, 19, z, ashlar)
            v.box(shaft[0], 25, z - 1, shaft[1], 25, z + 1, ashlar)
            v.set(outside, 26, z, slab("smooth_stone"))
            pinnacle(outside + (1 if left else -1), z, 27, 7)

    # Recessed rear lancets, kept separate from the side gallery connection.
    for center in (12, 19, 26):
        front_aperture(55, 56, center, 10, {0: 22, 1: 20})
        for dx in (-2, 2):
            v.box(center + dx, 9, 57, center + dx, 21, 57, ashlar)
        v.set(center, 24, 57, ashlar)
        v.box(center - 2, 9, 57, center + 2, 9, 57, pale)

    # Steep, two-cell-thick stepped roof. Both sides slope to the central ridge.
    for x in range(5, 34):
        high = roof_height(x)
        if x == 19:
            v.box(x, 42, 12, x, 43, 57, dark)
        else:
            v.box(x, high - 1, 12, x, high, 57, dark)
            v.box(x, high, 12, x, high, 57,
                  stair("deepslate_tile", "east" if x < 19 else "west"))
    # A restrained ridge crest uses slabs and piers instead of unsupported fences.
    v.box(19, 43, 14, 19, 43, 55, slab("stone_brick"))
    for z in range(15, 56, 4):
        v.set(19, 43, z, ashlar)

    # Front and rear stepped gables: substantial masonry underneath the coping.
    for z in (12, 57):
        for x in range(6, 33):
            high = roof_height(x)
            v.box(x, 27, z, x, high, z, stone)
            v.set(x, high, z, ashlar)
            if x != 19:
                v.set(x, high + 1, z, stair("stone_brick", "east" if x < 19 else "west"))
        v.box(19, 44, z, 19, 46, z, ashlar)
        v.box(18, 47, z, 20, 47, z, stone)
        v.set(19, 48, z, slab())

    # Tall north facade, projecting three-layer porch, and its open pointed door.
    v.box(13, 6, 9, 25, 6, 14, ashlar)
    v.box(14, 6, 8, 24, 6, 8, ashlar)
    portal_top = {0: 19, 1: 18, 2: 17, 3: 15, 4: 13}
    for dx, top in portal_top.items():
        for sign in (-1, 1) if dx else (1,):
            x = 19 + sign * dx
            v.clear(x, 7, 9, x, top, 15)
    for z, material, expand in ((9, ashlar, 1), (10, stone, 0), (11, pale, 0)):
        for dx in (-5, 5):
            v.box(19 + dx, 7, z, 19 + dx, 14, z, material)
        for dx, top in portal_top.items():
            for sign in (-1, 1) if dx else (1,):
                x = 19 + sign * dx
                v.box(x, top + 1, z, x, top + 1 + expand, z, material)
    for x in (13, 25):
        v.box(x, 7, 10, x, 14, 12, stone)
        v.box(x, 15, 10, x, 15, 12, slab())
    # Open wooden leaves are flush with the inner jambs, not across the entrance.
    v.box(15, 7, 14, 15, 12, 15, log())
    v.box(23, 7, 14, 23, 12, 15, log())
    v.clear(16, 7, 9, 22, 12, 15)

    # Two slim flanking lancets and a large upper traceried front window.
    for center in (10, 28):
        front_aperture(12, 14, center, 10, {0: 23, 1: 21})
        for x in (center - 2, center + 2):
            v.box(x, 9, 11, x, 22, 11, ashlar)
        v.set(center, 25, 11, slab())
        v.box(center - 2, 9, 11, center + 2, 9, 11, pale)
    front_aperture(12, 14, 19, 29, {0: 39, 1: 38, 2: 36, 3: 33})
    for dx, top in {0: 39, 1: 38, 2: 36, 3: 33}.items():
        for sign in (-1, 1) if dx else (1,):
            v.set(19 + dx * sign, top + 1, 11, ashlar)
    for x in (15, 23):
        v.box(x, 28, 11, x, 34, 11, ashlar)
    for x in (18, 20):
        v.box(x, 29, 14, x, 36, 14, ashlar)
    v.box(16, 33, 14, 22, 33, 14, ashlar)
    v.box(15, 28, 11, 23, 28, 11, pale)
    # Small heraldic mosaic echoes the reference's central hanging cross.
    v.box(17, 22, 11, 21, 27, 11, dark)
    v.box(19, 23, 10, 19, 26, 10, pale)
    v.box(18, 25, 10, 20, 25, 10, pale)
    v.set(19, 21, 11, dark)
    for x in (7, 31):
        v.box(x - 1, 2, 11, x + 1, 9, 13, stone)
        v.box(x, 10, 11, x, 28, 12, ashlar)
        for y in (6, 13, 25):
            v.box(x - 1, y, 10, x + 1, y, 13, slab("smooth_stone"))
        pinnacle(x, 12, 29, 9)

    # Five small pointed dormers on each long roof slope.
    for z in bays:
        for left in (True, False):
            lo, hi, face, inner = (10, 14, 10, 11) if left else (24, 28, 28, 27)
            v.clear(lo, 33, z - 1, hi, 36, z + 1)
            for dz in (-2, 2):
                v.box(lo, 32, z + dz, hi, 37, z + dz, dark)
            v.box(face, 32, z - 1, face, 37, z + 1, ashlar)
            v.clear(min(face, inner), 34, z, max(face, inner), 36, z)
            v.box(inner, 34, z, inner, 36, z, glass)
            for dz in range(-2, 3):
                top = 39 - abs(dz)
                v.box(lo, top, z + dz, hi, top, z + dz, dark)
                v.set(face, top, z + dz, ashlar)
            v.set(face, 40, z, slab())

    # Galleries retain a broad, open central nave and three-block walkways.
    for x1, x2 in ((9, 12), (26, 29)):
        v.box(x1, 16, 16, x2, 16, 52, wood)
        rail = x2 if x1 < 19 else x1
        v.box(rail, 17, 16, rail, 17, 52, slab("stone_brick"))
        for z in range(16, 53, 4):
            v.set(rail, 17, z, ashlar)
            v.set(rail, 18, z, slab())
        for z in piers[1:]:
            if z > 52:
                continue
            v.box(rail, 7, z, rail, 15, z, stone)
            v.box(rail - 1, 7, z - 1, rail + 1, 7, z + 1, ashlar)
            v.box(rail - 1, 15, z, rail + 1, 15, z, ashlar)
    # A rear bridge connects both galleries to the single staircase.
    v.box(9, 16, 51, 29, 16, 53, wood)
    v.box(12, 17, 50, 25, 17, 50, slab())
    for x in (12, 19, 25):
        v.set(x, 17, 50, ashlar)
        v.set(x, 18, 50, slab())
    for x in (12, 26):
        v.box(x, 7, 52, x, 15, 52, stone)
    # Transverse oak roof frames are visible from the nave between the dormers.
    for z in (22, 30, 38, 46, 54):
        v.box(9, 28, z, 29, 28, z, log("x"))
        for x in range(9, 30):
            y = 40 - abs(x - 19)
            v.set(x, y, z, wood)
        for x in (9, 29):
            v.box(x, 19, z, x, 28, z, log())

    # Rear right gallery stair: ten rises, with its complete headroom shaft.
    v.clear(26, 7, 39, 28, 19, 49)
    for step in range(10):
        y, z = 7 + step, 40 + step
        if y > 7:
            v.box(26, 7, z, 28, y - 1, z, wood)
        v.box(26, y, z, 28, y, z, stair("spruce", "south"))
    # Separate basement access under the west gallery; the main floor is pierced.
    v.clear(10, 2, 43, 11, 9, 48)
    for step in range(5):
        y, z = 2 + step, 44 + step
        if y > 2:
            v.box(10, 2, z, 11, y - 1, z, stone)
        v.box(10, y, z, 11, y, z, stair("stone_brick", "south"))

    # Modest furnishings preserve a five-block processional route to the dais.
    v.box(14, 7, 50, 24, 7, 53, wood)
    v.box(16, 7, 49, 22, 7, 49, stair("spruce", "south"))
    for z in (24, 30, 36, 42):
        for x1, x2 in ((14, 16), (22, 24)):
            v.box(x1, 7, z, x2, 7, z, stair("spruce", "north"))
            v.set(x1, 8, z, slab("spruce"))
            v.set(x2, 8, z, slab("spruce"))
    # Agreed lower-level passage to the east gallery/wing, cut after decoration.
    v.clear(30, 7, 36, 35, 11, 39)
