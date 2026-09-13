package io.github.minecraftbuilder.terrainworld;

import com.google.gson.stream.JsonWriter;
import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;

/** Detached world surface data. Rendering and file I/O never call the Bukkit API. */
final class SurfaceMap {
    static final int MAX_COLUMNS = 4_194_304;
    final int minX, minZ, maxX, maxZ, width, length;
    private final int[] heights, materials;
    private final BitSet captured;
    private final Map<String, Integer> materialIds = new LinkedHashMap<>();
    private int columns, minY = Integer.MAX_VALUE, maxY = Integer.MIN_VALUE;

    SurfaceMap(int minX, int minZ, int maxX, int maxZ) {
        long w = (long) maxX - minX + 1, l = (long) maxZ - minZ + 1;
        if (w <= 0 || l <= 0 || w > MAX_COLUMNS || l > MAX_COLUMNS || w * l > MAX_COLUMNS)
            throw new IllegalArgumentException("Map bounds must contain 1 to " + MAX_COLUMNS + " columns");
        this.minX = minX; this.minZ = minZ; this.maxX = maxX; this.maxZ = maxZ;
        width = (int) w; length = (int) l;
        heights = new int[width * length]; materials = new int[heights.length];
        captured = new BitSet(heights.length);
    }

    void setColumn(int x, int z, int y, String material) {
        if (x < minX || x > maxX || z < minZ || z > maxZ) throw new IllegalArgumentException("Column outside map");
        if (material == null || !material.matches("minecraft:[a-z0-9_]+")) throw new IllegalArgumentException("Invalid material key");
        int index = (z - minZ) * width + x - minX;
        if (captured.get(index)) throw new IllegalStateException("Column captured twice");
        heights[index] = y;
        materials[index] = materialIds.computeIfAbsent(material, ignored -> materialIds.size());
        captured.set(index); columns++; minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }

    int columns() { return columns; }

    static void validateName(String name) {
        if (name == null || !name.matches("[a-z0-9][a-z0-9_-]{0,47}"))
            throw new IllegalArgumentException("Map name must use 1–48 lowercase letters, digits, underscores or hyphens");
    }

    static void requireUnusedName(Path directory, String name) throws IOException {
        validateName(name);
        for (String extension : List.of(".json", ".png"))
            if (Files.exists(directory.resolve(name + extension), LinkOption.NOFOLLOW_LINKS))
                throw new FileAlreadyExistsException("Map already exists; choose a new name: " + name);
    }

    void write(Path directory, String name, String world, String worldKey, String worldUuid,
               Instant startedAt, Instant finishedAt) throws IOException {
        if (columns != heights.length) throw new IllegalStateException("Cannot export an incomplete map");
        requireUnusedName(directory, name);
        Files.createDirectories(directory);
        Path jsonTemp = Files.createTempFile(directory, ".surface-", ".json.tmp");
        Path pngTemp = Files.createTempFile(directory, ".surface-", ".png.tmp");
        try {
            try (JsonWriter out = new JsonWriter(Files.newBufferedWriter(jsonTemp))) {
                out.beginObject();
                out.name("format").value("minecraft-builder-surface-map-v1");
                out.name("source").value("paper_world_surface");
                out.name("ignored_materials").beginArray().value("minecraft:barrier").endArray();
                out.name("surface_policy").value("Highest block excluding all air variants and ignored_materials; wholly transparent columns use minecraft:air at world minimum Y.");
                out.name("world").value(world); out.name("world_key").value(worldKey); out.name("world_uuid").value(worldUuid);
                out.name("capture_started_at").value(startedAt.toString());
                out.name("capture_finished_at").value(finishedAt.toString());
                out.name("atomic_snapshot").value(false);
                out.name("capture_note").value("Existing chunks read sequentially on the server thread; edits during capture can appear in different chunks at different times.");
                out.name("orientation").value("north_up; x increases right; z increases down");
                out.name("index").value("(z - min_z) * width + (x - min_x)");
                out.name("min_x").value(minX); out.name("max_x").value(maxX);
                out.name("min_z").value(minZ); out.name("max_z").value(maxZ);
                out.name("width").value(width); out.name("length").value(length);
                out.name("columns").value(columns); out.name("min_surface_y").value(minY); out.name("max_surface_y").value(maxY);
                out.name("palette").beginArray();
                for (String material : materialIds.keySet()) out.value(material);
                out.endArray(); out.name("palette_rgb").beginArray();
                for (String material : materialIds.keySet()) out.value(String.format(Locale.ROOT, "#%06x", color(material)));
                out.endArray(); out.name("surface_y").beginArray();
                for (int height : heights) out.value(height);
                out.endArray(); out.name("material_index").beginArray();
                for (int material : materials) out.value(material);
                out.endArray(); out.endObject();
            }
            if (!ImageIO.write(render(), "png", pngTemp.toFile())) throw new IOException("PNG writer unavailable");
            // Neither final filename is replaced, even if another process creates it during capture.
            Files.move(jsonTemp, directory.resolve(name + ".json"));
            Files.move(pngTemp, directory.resolve(name + ".png"));
        } finally {
            Files.deleteIfExists(jsonTemp); Files.deleteIfExists(pngTemp);
        }
    }

    BufferedImage render() {
        if (columns != heights.length) throw new IllegalStateException("Cannot render an incomplete map");
        List<String> palette = new ArrayList<>(materialIds.keySet());
        BufferedImage image = new BufferedImage(width, length, BufferedImage.TYPE_INT_RGB);
        for (int z = 0; z < length; z++) for (int x = 0; x < width; x++) {
            int index = z * width + x;
            String material = palette.get(materials[index]);
            int base = color(material);
            double dx = (height(x + 1, z) - height(x - 1, z)) / 2.0;
            double dz = (height(x, z + 1) - height(x, z - 1)) / 2.0;
            double norm = Math.sqrt(dx * dx + dz * dz + 1);
            double light = (-dx * -.55 - dz * -.55 + .63) / norm;
            double shade = Math.clamp(.76 + .36 * light, .44, 1.13);
            // Survey blocks retain their categorical color; water has no false land relief.
            if (material.endsWith("_concrete") || material.endsWith("_wool") || material.endsWith("_terracotta")) shade = 1;
            if (material.equals("minecraft:water")) shade = .96;
            image.setRGB(x, z, shaded(base, shade));
        }
        return image;
    }

    private double height(int x, int z) {
        return heights[Math.clamp(z, 0, length - 1) * width + Math.clamp(x, 0, width - 1)];
    }

    private static int shaded(int color, double shade) {
        int r = (int) Math.clamp((color >> 16 & 255) * shade, 0, 255);
        int g = (int) Math.clamp((color >> 8 & 255) * shade, 0, 255);
        int b = (int) Math.clamp((color & 255) * shade, 0, 255);
        return r << 16 | g << 8 | b;
    }

    static int color(String key) {
        String material = key.replaceFirst("^minecraft:", "");
        String pigment = material.replaceFirst("_(concrete|wool|terracotta)$", "");
        if (!pigment.equals(material)) {
            Integer color = switch (pigment) {
                case "white" -> 0xf0f0e6; case "orange" -> 0xf78d27; case "magenta" -> 0xdc52c7;
                case "light_blue" -> 0x68c8ec; case "yellow" -> 0xf6d34a; case "lime" -> 0x98d84d;
                case "pink" -> 0xf394b5; case "gray" -> 0x545c61; case "light_gray" -> 0xa4aaa6;
                case "cyan" -> 0x23b6b6; case "purple" -> 0x9460ce; case "blue" -> 0x4a69d8;
                case "brown" -> 0x916044; case "green" -> 0x527c31; case "red" -> 0xe3544b;
                case "black" -> 0x26282d; default -> null;
            };
            if (color != null) return color;
        }
        if (material.contains("leaves")) return 0x397548;
        if (material.contains("spruce") || material.contains("dark_oak")) return 0x75583c;
        if (material.endsWith("_planks") || material.endsWith("_log")) return 0xa48458;
        if (material.contains("copper")) return 0x639f8d;
        if (material.contains("quartz")) return 0xe9e4d5;
        if (material.contains("sandstone")) return 0xc8bb83;
        if (material.contains("deepslate") || material.equals("obsidian")) return 0x555a64;
        if (material.contains("stone_brick")) return 0x9ca49e;
        return switch (material) {
            case "water", "bubble_column" -> 0x367dba;
            case "grass_block", "short_grass", "tall_grass", "moss_block" -> 0x79a957;
            case "dirt", "coarse_dirt", "rooted_dirt", "dirt_path", "farmland" -> 0x937454;
            case "podzol", "mud" -> 0x675746;
            case "stone", "cobblestone", "smooth_stone" -> 0xa2a8a3;
            case "andesite", "polished_andesite" -> 0x929e98;
            case "diorite", "polished_diorite" -> 0xb8bebb;
            case "granite", "polished_granite" -> 0xae8980;
            case "sand" -> 0xd7cc9a;
            case "gravel" -> 0xa49f97;
            case "snow", "snow_block", "powder_snow" -> 0xe8eff1;
            case "ice", "packed_ice", "blue_ice" -> 0x93c7dc;
            case "gold_block", "glowstone", "lantern" -> 0xf4cf58;
            case "sea_lantern" -> 0xb4ece2;
            case "terracotta", "bricks" -> 0xb6775d;
            case "glass", "tinted_glass" -> 0xacced3;
            case "air", "cave_air", "void_air" -> 0x18232e;
            default -> 0x8a8988;
        };
    }
}
