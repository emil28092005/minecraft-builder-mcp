package io.github.minecraftbuilder.terrainworld;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.TextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Bukkit;
import org.bukkit.Chunk;
import org.bukkit.Color;
import org.bukkit.Location;
import org.bukkit.NamespacedKey;
import org.bukkit.World;
import org.bukkit.entity.Display;
import org.bukkit.entity.TextDisplay;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.Transformation;
import org.joml.Quaternionf;
import org.joml.Vector3f;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

/** Optional, persistent signs for the completed station; no arena destinations are implied. */
public final class StationLabels {
    public static final String TAG = "shacraft_station_v1";
    private static final TextColor INK = TextColor.color(0xf3dfab);
    private static final Map<UUID, Installation> ACTIVE = new HashMap<>();

    /** Position is the visual centre; yaw 0 faces south and yaw -90 faces east. */
    public record LabelSpec(String id, String text, double x, double y, double z,
                            float yaw, float scale, int lineWidth, boolean bold) {}

    private static final List<LabelSpec> LABELS = labels();

    private StationLabels() {}

    /** Immutable positions/text for a build manifest or a review before installation. */
    public static List<LabelSpec> manifest() { return LABELS; }

    /**
     * Schedule installation on the server thread after existing label chunks have
     * loaded their saved entities. This prevents duplicate labels after a restart.
     * No terrain is generated. Only this plugin's marked TextDisplays are replaced.
     */
    public static void install(JavaPlugin plugin, World world) {
        Objects.requireNonNull(plugin); Objects.requireNonNull(world);
        if (!Bukkit.isPrimaryThread()) throw new IllegalStateException("Station labels must be scheduled on the server thread");
        Installation installation = new Installation(plugin, world);
        Installation previous = ACTIVE.put(world.getUID(), installation);
        if (previous != null) previous.close();
        installation.load();
    }

    private static List<LabelSpec> labels() {
        List<LabelSpec> labels = new ArrayList<>();
        labels.add(new LabelSpec("exterior-shacraft", "SHACRAFT", -5.5, 111.2, -81.94, 0, 6.4f, 160, true));
        labels.add(new LabelSpec("smash-header", "S M A S H", -16.5, 122.2, -136.94, 0, 7f, 160, true));
        int[] bayCenters = {-42, -32, -22, -12, -2, 8};
        for (int i = 0; i < bayCenters.length; i++) {
            String number = String.format(java.util.Locale.ROOT, "%02d", i + 1);
            labels.add(new LabelSpec("arena-" + number, number,
                bayCenters[i] + .5, 119.6, -134.95, 0, 1.2f, 120, false));
            labels.add(new LabelSpec("arena-" + number + "-sign", "АРЕНА " + number + "\nСКОРО",
                bayCenters[i] + .5, 114.5, -134.95, 0, 1f, 120, false));
        }
        for (int floor = 1; floor <= 2; floor++) {
            int feet = floor == 1 ? 99 : 113;
            labels.add(new LabelSpec("lift-" + floor + "-front", floor == 1 ? "1 · ВЕСТИБЮЛЬ" : "2 · SMASH",
                -5.5, feet + 6.2, -114.93, 0, 2.4f, 160, true));
            labels.add(new LabelSpec("lift-" + floor + "-selector", floor == 1 ? "2 SMASH ↑" : "1 ВЕСТИБЮЛЬ ↓",
                -5.5, feet + 3.3, -121.92, 0, 1.65f, 160, true));
            labels.add(new LabelSpec("lift-" + floor + "-instruction", "ПКМ по золотой\nпанели",
                -5.5, feet + 1.3, -121.92, 0, 1.2f, 120, false));
        }
        labels.add(new LabelSpec("vestibule-lift-heading", "SHACRAFT", -5.5, 108, -114.93, 0, 3f, 160, true));
        labels.add(new LabelSpec("smash-damage", "УРОН\nЧем выше урон,\nтем сильнее\nотбрасывание",
            -70.96, 116.9, -121.5, -90, 1.1f, 120, false));
        labels.add(new LabelSpec("smash-knockback", "ОТБРАСЫВАНИЕ\nСтолкни соперников\nс острова",
            -70.96, 116.9, -114.5, -90, 1.1f, 120, false));
        labels.add(new LabelSpec("smash-double-jump", "ДВОЙНОЙ ПРЫЖОК\nПрыгни ещё раз,\nчтобы вернуться\nна остров",
            -70.96, 116.9, -107.5, -90, 1.1f, 120, false));
        return List.copyOf(labels);
    }

    private static void configure(TextDisplay display, LabelSpec label, NamespacedKey owner, NamespacedKey id) {
        display.text(Component.text(label.text(), INK).decoration(TextDecoration.BOLD, label.bold()));
        display.setBillboard(Display.Billboard.FIXED);
        display.setRotation(label.yaw(), 0);
        display.setAlignment(TextDisplay.TextAlignment.CENTER);
        display.setLineWidth(label.lineWidth());
        display.setDefaultBackground(false);
        display.setBackgroundColor(Color.fromARGB(0, 0, 0, 0));
        display.setSeeThrough(false);
        display.setShadowed(true);
        display.setTextOpacity((byte) 255);
        display.setBrightness(new Display.Brightness(15, 15));
        display.setViewRange(label.id().equals("exterior-shacraft") ? 2f : 1f);
        display.setShadowRadius(0); display.setShadowStrength(0);
        display.setInterpolationDuration(0); display.setTeleportDuration(0);
        float lines = label.text().split("\n", -1).length;
        // Minecraft text is bottom-centred and uses 0.025 blocks per font pixel.
        display.setTransformation(new Transformation(new Vector3f(0, -.125f * label.scale() * lines, 0),
            new Quaternionf(), new Vector3f(label.scale()), new Quaternionf()));
        // Disable the optional display bounding-box cull; normal view distance still applies.
        display.setDisplayWidth(0); display.setDisplayHeight(0);
        display.setPersistent(true);
        display.addScoreboardTag(TAG);
        display.getPersistentDataContainer().set(owner, PersistentDataType.STRING, TAG);
        display.getPersistentDataContainer().set(id, PersistentDataType.STRING, label.id());
    }

    private static final class Installation {
        private final JavaPlugin plugin;
        private final World world;
        private final List<Chunk> ownedTickets = new ArrayList<>();
        private List<Chunk> chunks = List.of();
        private boolean closed;
        private int attempts;

        Installation(JavaPlugin plugin, World world) { this.plugin = plugin; this.world = world; }

        void load() {
            record Column(int x, int z) {}
            var columns = new LinkedHashSet<Column>();
            for (LabelSpec label : LABELS)
                columns.add(new Column(Math.floorDiv((int) Math.floor(label.x()), 16),
                    Math.floorDiv((int) Math.floor(label.z()), 16)));
            for (Column column : columns) {
                if (!world.isChunkGenerated(column.x(), column.z())) {
                    fail("Station label chunk is not generated: " + column.x() + "," + column.z()); return;
                }
            }
            List<CompletableFuture<Chunk>> loads = columns.stream()
                .map(c -> world.getChunkAtAsync(c.x(), c.z(), false)).toList();
            CompletableFuture.allOf(loads.toArray(CompletableFuture[]::new)).whenComplete((unused, error) -> {
                if (!plugin.isEnabled() || closed) return;
                Bukkit.getScheduler().runTask(plugin, () -> {
                    if (closed) return;
                    if (error != null) { fail("Cannot load station label chunks: " + error.getMessage()); return; }
                    chunks = loads.stream().map(CompletableFuture::join).toList();
                    if (chunks.stream().anyMatch(Objects::isNull)) { fail("An existing station chunk is unavailable"); return; }
                    for (Chunk chunk : chunks) if (chunk.addPluginChunkTicket(plugin)) ownedTickets.add(chunk);
                    waitForEntities();
                });
            });
        }

        void waitForEntities() {
            if (closed || !plugin.isEnabled()) { close(); return; }
            if (chunks.stream().anyMatch(c -> !c.isEntitiesLoaded())) {
                if (++attempts >= 100) { fail("Station entity data did not load; existing labels retained"); return; }
                Bukkit.getScheduler().runTaskLater(plugin, this::waitForEntities, 1L); return;
            }
            NamespacedKey owner = new NamespacedKey(plugin, "station_label_set");
            NamespacedKey id = new NamespacedKey(plugin, "station_label_id");
            List<TextDisplay> previous = world.getEntitiesByClass(TextDisplay.class).stream()
                .filter(e -> TAG.equals(e.getPersistentDataContainer().get(owner, PersistentDataType.STRING))).toList();
            List<TextDisplay> created = new ArrayList<>();
            try {
                for (LabelSpec label : LABELS) {
                    Location location = new Location(world, label.x(), label.y(), label.z(), label.yaw(), 0);
                    created.add(world.spawn(location, TextDisplay.class, display -> configure(display, label, owner, id)));
                }
                previous.forEach(TextDisplay::remove);
                plugin.getLogger().info("Station labels installed: " + created.size() + "; replaced=" + previous.size());
            } catch (Exception error) {
                created.forEach(TextDisplay::remove);
                plugin.getLogger().warning("Station labels not installed; previous labels retained: " + error.getMessage());
            } finally { close(); }
        }

        void fail(String message) { plugin.getLogger().warning(message); close(); }

        void close() {
            if (closed) return;
            closed = true;
            for (Chunk chunk : ownedTickets) chunk.removePluginChunkTicket(plugin);
            ownedTickets.clear();
            ACTIVE.remove(world.getUID(), this);
        }
    }
}
