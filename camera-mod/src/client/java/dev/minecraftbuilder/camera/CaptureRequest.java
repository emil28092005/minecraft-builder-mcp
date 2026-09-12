package dev.minecraftbuilder.camera;

import com.google.gson.JsonObject;
import java.util.Set;

/** Coordinates are the observer's feet, matching Paper teleports; the reply also gives eye position. */
public record CaptureRequest(double x, double y, double z, float yaw, float pitch, int fov,
                             int width, int height, String dimension, String afterOperationId) {
    private static final Set<String> FIELDS = Set.of("x", "y", "z", "yaw", "pitch", "fov", "width",
            "height", "dimension", "world", "world_id", "afterOperationId");

    public static CaptureRequest parse(JsonObject body) {
        if (!FIELDS.containsAll(body.keySet())) throw new IllegalArgumentException("Unknown capture field");
        double x = number(body, "x"), y = number(body, "y"), z = number(body, "z");
        double yaw = number(body, "yaw"), pitch = number(body, "pitch");
        if (Math.abs(x) > 29_999_984 || Math.abs(z) > 29_999_984 || y < -2048 || y > 2048)
            throw new IllegalArgumentException("Position is outside the camera coordinate limits");
        if (Math.abs(yaw) > 360 || Math.abs(pitch) > 90)
            throw new IllegalArgumentException("yaw must be -360..360 and pitch -90..90");
        int fov = integer(body, "fov", 70, 30, 110);
        int width = integer(body, "width", 1280, 320, 1920);
        int height = integer(body, "height", 720, 180, 1080);
        return new CaptureRequest(x, y, z, (float) yaw, (float) pitch, fov, width, height,
                string(body, "dimension", 128), string(body, "afterOperationId", 128));
    }

    private static double number(JsonObject body, String name) {
        if (!body.has(name) || !body.get(name).isJsonPrimitive() || !body.getAsJsonPrimitive(name).isNumber())
            throw new IllegalArgumentException(name + " must be a number");
        double value = body.get(name).getAsDouble();
        if (!Double.isFinite(value)) throw new IllegalArgumentException(name + " must be finite");
        return value;
    }

    private static int integer(JsonObject body, String name, int fallback, int min, int max) {
        if (!body.has(name)) return fallback;
        double value = number(body, name);
        if (value != Math.rint(value) || value < min || value > max)
            throw new IllegalArgumentException(name + " must be an integer in " + min + ".." + max);
        return (int) value;
    }

    private static String string(JsonObject body, String name, int max) {
        if (!body.has(name)) return null;
        if (!body.get(name).isJsonPrimitive() || !body.getAsJsonPrimitive(name).isString())
            throw new IllegalArgumentException(name + " must be a string");
        String value = body.get(name).getAsString();
        if (value.isBlank() || value.length() > max) throw new IllegalArgumentException(name + " has invalid length");
        return value;
    }
}
