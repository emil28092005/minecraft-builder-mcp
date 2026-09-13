package io.github.minecraftbuilder.core;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/** Small deterministic geometry language. Coordinates are world coordinates; later operations win. */
public final class RecipeCompiler {
    private static final int MAX_DEPTH = 8;
    private static final int MAX_EXPANDED_OPERATIONS = 4096;
    private RecipeCompiler() { }

    public static Map<BlockPos, String> compile(JsonObject recipe, int maxBlocks) {
        if (maxBlocks < 1 || maxBlocks > 2_000_000) throw new IllegalArgumentException("Invalid recipe block limit");
        fields(recipe, Set.of("version", "operations"));
        if (integer(recipe, "version") != 1) throw new IllegalArgumentException("Unsupported recipe version");
        Builder builder = new Builder(maxBlocks);
        builder.operations(array(recipe, "operations"), new BlockPos(0, 0, 0), 0);
        return java.util.Collections.unmodifiableMap(new LinkedHashMap<>(builder.blocks));
    }

    private static final class Builder {
        final int maxBlocks;
        final long maxVisits;
        long visits;
        int operationCount;
        final Map<BlockPos, String> blocks = new LinkedHashMap<>();
        Builder(int maxBlocks) { this.maxBlocks = maxBlocks; maxVisits = Math.min(2_000_000L, (long) maxBlocks * 16); }
        void operations(JsonArray operations, BlockPos offset, int depth) {
            if (depth > MAX_DEPTH) throw new IllegalArgumentException("Recipe nesting exceeds limit");
            if (operations.size() > MAX_EXPANDED_OPERATIONS) throw new IllegalArgumentException("Too many operations");
            for (JsonElement element : operations) {
                if (++operationCount > MAX_EXPANDED_OPERATIONS) throw new IllegalArgumentException("Expanded operation count exceeds limit");
                if (!element.isJsonObject()) throw new IllegalArgumentException("Operation must be an object");
                JsonObject operation = element.getAsJsonObject();
                String type = string(operation, "type");
                switch (type) {
                    case "box" -> box(operation, offset);
                    case "line" -> line(operation, offset);
                    case "cylinder" -> cylinder(operation, offset);
                    case "repeat" -> repeat(operation, offset, depth);
                    default -> throw new IllegalArgumentException("Unsupported operation: " + type);
                }
            }
        }
        void box(JsonObject operation, BlockPos offset) {
            fields(operation, Set.of("type", "min", "max", "block", "hollow"));
            BlockPos min = position(operation, "min").add(offset);
            BlockPos max = position(operation, "max").add(offset);
            Region region = new Region("recipe", min, max);
            charge(region.volume());
            String block = block(operation); boolean hollow = bool(operation, "hollow", false);
            for (long y = min.y(); y <= max.y(); y++) for (long z = min.z(); z <= max.z(); z++) for (long x = min.x(); x <= max.x(); x++) {
                if (!hollow || x == min.x() || x == max.x() || y == min.y() || y == max.y() || z == min.z() || z == max.z())
                    put(new BlockPos((int) x, (int) y, (int) z), block);
            }
        }
        void line(JsonObject operation, BlockPos offset) {
            fields(operation, Set.of("type", "from", "to", "block"));
            BlockPos from = position(operation, "from").add(offset), to = position(operation, "to").add(offset);
            long dx = (long) to.x() - from.x(), dy = (long) to.y() - from.y(), dz = (long) to.z() - from.z();
            long steps = Math.max(Math.max(Math.abs(dx), Math.abs(dy)), Math.abs(dz));
            charge(steps + 1); String block = block(operation);
            if (steps == 0) { put(from, block); return; }
            for (long step = 0; step <= steps; step++) {
                put(new BlockPos(interpolate(from.x(), dx, step, steps), interpolate(from.y(), dy, step, steps),
                    interpolate(from.z(), dz, step, steps)), block);
            }
        }
        void cylinder(JsonObject operation, BlockPos offset) {
            fields(operation, Set.of("type", "center", "radius", "height", "block", "hollow"));
            BlockPos center = position(operation, "center").add(offset);
            int radius = integer(operation, "radius"), height = integer(operation, "height");
            if (radius < 0 || height < 1) throw new IllegalArgumentException("Cylinder radius must be nonnegative and height positive");
            long diameter = Math.addExact(Math.multiplyExact((long) radius, 2), 1);
            charge(Math.multiplyExact(Math.multiplyExact(diameter, diameter), height));
            Math.subtractExact(center.x(), radius); Math.addExact(center.x(), radius);
            Math.subtractExact(center.z(), radius); Math.addExact(center.z(), radius);
            Math.addExact(center.y(), height - 1);
            long outer = (long) radius * radius, inner = (long) (radius - 1) * (radius - 1);
            String block = block(operation); boolean hollow = bool(operation, "hollow", false);
            for (int y = 0; y < height; y++) for (int z = -radius; z <= radius; z++) for (int x = -radius; x <= radius; x++) {
                long distance = (long) x * x + (long) z * z;
                if (distance <= outer && (!hollow || radius == 0 || distance > inner))
                    put(center.add(new BlockPos(x, y, z)), block);
            }
        }
        void repeat(JsonObject operation, BlockPos offset, int depth) {
            fields(operation, Set.of("type", "count", "offset", "operations"));
            int count = integer(operation, "count");
            if (count < 1 || count > 1024) throw new IllegalArgumentException("Repeat count must be 1..1024");
            BlockPos step = position(operation, "offset"); JsonArray children = array(operation, "operations");
            for (int i = 0; i < count; i++) {
                BlockPos displacement = new BlockPos(Math.multiplyExact(step.x(), i), Math.multiplyExact(step.y(), i),
                    Math.multiplyExact(step.z(), i));
                operations(children, offset.add(displacement), depth + 1);
            }
        }
        void charge(long amount) {
            visits = Math.addExact(visits, amount);
            if (visits > maxVisits) throw new IllegalArgumentException("Recipe scan budget exceeded");
        }
        void put(BlockPos position, String block) {
            if (!blocks.containsKey(position) && blocks.size() >= maxBlocks) throw new IllegalArgumentException("Recipe block limit exceeded");
            blocks.put(position, block);
        }
    }

    private static int interpolate(int start, long delta, long step, long steps) {
        // Integer arithmetic gives deterministic nearest-voxel endpoints without floating-point drift.
        long numerator = Math.multiplyExact(delta, step);
        long rounded = Math.floorDiv(Math.addExact(Math.multiplyExact(numerator, 2), steps), Math.multiplyExact(steps, 2));
        return Math.toIntExact(Math.addExact(start, rounded));
    }
    private static String block(JsonObject object) {
        String block = string(object, "block");
        if (block.length() > 1024 || !block.matches("minecraft:[a-z0-9_]+(?:\\[[a-z0-9_=,]+\\])?"))
            throw new IllegalArgumentException("Expected a Minecraft block state string");
        return block;
    }
    private static BlockPos position(JsonObject parent, String name) {
        JsonElement value = required(parent, name);
        if (!value.isJsonObject()) throw new IllegalArgumentException(name + " must be a position object");
        JsonObject object = value.getAsJsonObject(); fields(object, Set.of("x", "y", "z"));
        return new BlockPos(integer(object, "x"), integer(object, "y"), integer(object, "z"));
    }
    private static int integer(JsonObject object, String name) {
        JsonElement value = required(object, name);
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber() || !value.getAsString().matches("-?(0|[1-9][0-9]*)"))
            throw new IllegalArgumentException(name + " must be an integer");
        try { return Integer.parseInt(value.getAsString()); }
        catch (NumberFormatException e) { throw new IllegalArgumentException(name + " exceeds 32-bit bounds", e); }
    }
    private static String string(JsonObject object, String name) {
        JsonElement value = required(object, name);
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) throw new IllegalArgumentException(name + " must be a string");
        return value.getAsString();
    }
    private static boolean bool(JsonObject object, String name, boolean fallback) {
        if (!object.has(name)) return fallback;
        JsonElement value = object.get(name);
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isBoolean()) throw new IllegalArgumentException(name + " must be a boolean");
        return value.getAsBoolean();
    }
    private static JsonArray array(JsonObject object, String name) {
        JsonElement value = required(object, name);
        if (!value.isJsonArray()) throw new IllegalArgumentException(name + " must be an array");
        return value.getAsJsonArray();
    }
    private static JsonElement required(JsonObject object, String name) {
        if (object == null || !object.has(name) || object.get(name).isJsonNull()) throw new IllegalArgumentException("Missing field: " + name);
        return object.get(name);
    }
    private static void fields(JsonObject object, Set<String> accepted) {
        if (object == null) throw new IllegalArgumentException("Expected an object");
        for (String key : object.keySet()) if (!accepted.contains(key)) throw new IllegalArgumentException("Unknown field: " + key);
    }
}
