package dev.minecraftbuilder.camera;

import com.google.gson.JsonObject;
import com.mojang.blaze3d.platform.NativeImage;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientLifecycleEvents;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.minecraft.client.CameraType;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.client.gui.screens.ConnectScreen;
import net.minecraft.client.gui.screens.DisconnectedScreen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.multiplayer.JoinMultiplayerScreen;
import net.minecraft.client.multiplayer.ServerData;
import net.minecraft.client.multiplayer.resolver.ServerAddress;
import net.minecraft.world.level.chunk.status.ChunkStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.imageio.ImageIO;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.time.Instant;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** One observer, one active request, bounded retained screenshots. No world writes or client teleport hacks. */
public final class CameraClient implements ClientModInitializer, CameraHttpServer.Backend {
    private static final Logger LOGGER = LoggerFactory.getLogger("minecraft-builder-camera");
    private static final long TIMEOUT_NANOS = TimeUnit.SECONDS.toNanos(20);
    private static volatile CameraClient instance;
    private final AtomicReference<Job> active = new AtomicReference<>();
    private final LinkedHashMap<String, Job> jobs = new LinkedHashMap<>();
    private final ExecutorService encoder = Executors.newSingleThreadExecutor(Thread.ofPlatform()
            .daemon(true).name("mcb-camera-encoder").factory());
    private final ScheduledExecutorService watchdog = Executors.newSingleThreadScheduledExecutor(Thread.ofPlatform()
            .daemon(true).name("mcb-camera-watchdog").factory());
    private volatile JsonObject cachedHealth = CameraHttpServer.error("starting", "Waiting for client tick");
    private CameraHttpServer http;
    private AutoConnectPolicy autoConnect;
    private boolean autoConnectSuspended;
    private boolean autoConnectPaused;
    private long nextPauseCheck;

    @Override public void onInitializeClient() {
        String token = System.getenv("MCB_CAMERA_TOKEN");
        if (token == null || token.isBlank()) {
            LOGGER.info("Camera HTTP disabled: set MCB_CAMERA_TOKEN to enable the dedicated observer service");
            encoder.shutdownNow();
            watchdog.shutdownNow();
            return;
        }
        try {
            int port = Integer.parseInt(System.getenv().getOrDefault("MCB_CAMERA_PORT", "8766"));
            if (port < 1024 || port > 65535) throw new IllegalArgumentException("Invalid camera port");
            http = new CameraHttpServer(port, token, this);
            String target = System.getenv("MCB_CAMERA_AUTO_CONNECT");
            if (target != null && !target.isBlank()) autoConnect = new AutoConnectPolicy(target, System.currentTimeMillis());
            instance = this;
            ClientTickEvents.END_CLIENT_TICK.register(this::tick);
            ClientLifecycleEvents.CLIENT_STOPPING.register(this::stop);
            watchdog.scheduleAtFixedRate(this::expire, 1, 1, TimeUnit.SECONDS);
            http.start();
            LOGGER.info("Camera HTTP listening on 127.0.0.1:{} (authenticated)", port);
        } catch (Exception exception) {
            LOGGER.error("Camera service could not start: {}", exception.getClass().getSimpleName());
            encoder.shutdownNow();
            watchdog.shutdownNow();
        }
    }

    @Override public JsonObject health() { return cachedHealth.deepCopy(); }

    @Override public synchronized JsonObject submit(CaptureRequest request) {
        Job job = new Job(request);
        if (!active.compareAndSet(null, job)) return CameraHttpServer.error("camera_busy", "One capture is already active");
        jobs.put(job.id, job);
        while (jobs.size() > 4) jobs.remove(jobs.keySet().iterator().next());
        return job.result.deepCopy();
    }

    @Override public synchronized JsonObject poll(String captureId) {
        Job job = jobs.get(captureId);
        return job == null ? null : job.result.deepCopy();
    }

    private synchronized void expire() {
        Job job = active.get();
        if (job != null && System.nanoTime() - job.createdNanos >= TIMEOUT_NANOS)
            job.fail("capture_timeout", "Scene did not become ready within 20 seconds; no fresh image returned");
        // Keep an expired active job until a client tick can restore its view safely.
        jobs.values().removeIf(value -> value != active.get()
                && System.nanoTime() - value.createdNanos > TimeUnit.MINUTES.toNanos(2));
    }

    private void tick(Minecraft client) {
        autoConnect(client);
        Job job = active.get();
        JsonObject health = new JsonObject();
        health.addProperty("status", "ok");
        health.addProperty("connected", client.level != null && client.player != null);
        health.addProperty("spectator", client.player != null && client.player.isSpectator());
        health.addProperty("busy", job != null);
        health.addProperty("autoConnectEnabled", autoConnect != null);
        if (autoConnect != null) {
            health.addProperty("autoConnectTarget", autoConnect.target());
            health.addProperty("autoConnectAttempts", autoConnect.attempts());
            health.addProperty("autoConnectPaused", autoConnectPaused || autoConnectSuspended);
        }
        health.addProperty("updatedAt", Instant.now().toString());
        if (client.level != null) health.addProperty("dimension", dimension(client));
        if (client.player != null) health.addProperty("playerId", client.player.getUUID().toString());
        cachedHealth = health;
        if (job == null) return;
        if (job.done) { restore(client, job); active.compareAndSet(job, null); return; }
        if (client.player == null || client.level == null) { job.fail("disconnected", "Camera client is not in a world"); return; }
        if (!client.player.isSpectator()) { job.fail("spectator_required", "Camera account must be in spectator mode"); return; }
        if (client.gui.screen() != null || client.gui.overlay() != null || client.isPaused()) {
            job.fail("view_obstructed", "Close menus and overlays in the observer client"); return;
        }
        if (!job.initialized) {
            // Paper owns teleports. Wait for its position/dimension packet before adjusting the view.
            if (!matchesPosition(client, job.request)) return;
            job.player = client.player;
            job.level = client.level;
            job.saved = new SavedView(client.gui.hud.isHidden(), client.options.fov().get(),
                    client.options.bobView().get(), client.options.fovEffectScale().get(),
                    client.options.getCameraType(), client.player.getYRot(), client.player.getXRot());
            if (!client.gui.hud.isHidden()) client.gui.hud.toggle();
            client.options.fov().set(job.request.fov());
            client.options.bobView().set(false);
            client.options.fovEffectScale().set(0.0);
            client.options.setCameraType(CameraType.FIRST_PERSON);
            client.player.setYRot(job.request.yaw());
            client.player.setXRot(job.request.pitch());
            client.player.setOldRot();
            job.initialized = true;
        }
        if (client.player != job.player || client.level != job.level || !matchesPosition(client, job.request)) {
            job.fail("camera_moved", "Observer moved or changed world during capture"); return;
        }
        if (client.getCameraEntity() != client.player) {
            job.fail("spectating_entity", "Observer must use its own camera, not another entity"); return;
        }
        if (!matchesView(client, job.request)) { job.fail("view_changed", "Observer view changed during capture"); return; }
        if (chunksLoaded(client)) job.stableTicks++; else { job.stableTicks = 0; job.readyFrames = 0; }
    }

    private void autoConnect(Minecraft client) {
        if (autoConnect == null) return;
        long now = System.currentTimeMillis();
        if (now >= nextPauseCheck) {
            autoConnectPaused = java.nio.file.Files.exists(client.gameDirectory.toPath().resolve("config/minecraft-builder-camera.autojoin-disabled"));
            nextPauseCheck = now + 1000;
        }
        if (client.level != null) {
            ServerData server = client.getCurrentServer();
            if (server == null || !server.ip.equals(autoConnect.target())) autoConnectSuspended = true;
        }
        var screen = client.gui.screen();
        boolean eligible = screen instanceof TitleScreen || screen instanceof DisconnectedScreen || screen instanceof JoinMultiplayerScreen;
        if (!autoConnect.due(now, client.level != null || client.getConnection() != null,
                eligible, autoConnectPaused || autoConnectSuspended || client.gui.overlay() != null)) return;
        LOGGER.info("Observer connecting to configured local server (attempt {})", autoConnect.attempts());
        ConnectScreen.startConnecting(new TitleScreen(), client, ServerAddress.parseString(autoConnect.target()),
            new ServerData("Minecraft Builder local camera", autoConnect.target(), ServerData.Type.OTHER), false, null);
    }

    /** Called after GameRenderer.render, on Minecraft's render thread. Uses the supported GPU screenshot API. */
    public static void afterRender(boolean renderWorld) {
        CameraClient worker = instance;
        if (worker != null && renderWorld) worker.rendered(Minecraft.getInstance());
    }

    private void rendered(Minecraft client) {
        Job job = active.get();
        if (job == null || job.done || !job.initialized || job.readbackStarted || job.stableTicks < 20) return;
        if (client.player != job.player || client.level != job.level || client.gui.screen() != null
                || client.gui.overlay() != null || !matchesPosition(client, job.request) || !matchesView(client, job.request)) {
            job.fail("view_changed", "Observer view changed before frame capture"); return;
        }
        if (!client.gameRenderer.mainCamera().isInitialized() || !chunksLoaded(client)
                || client.levelRenderer.sectionRenderDispatcher() == null || !client.levelRenderer.hasRenderedAllSections()) {
            job.readyFrames = 0; return;
        }
        if (++job.readyFrames < 3) return;
        var target = client.gameRenderer.mainRenderTarget();
        if (target.width <= 0 || target.height <= 0 || (long) target.width * target.height > 16_777_216) {
            job.fail("framebuffer_size", "Observer framebuffer is empty or exceeds 16 megapixels"); return;
        }
        job.readbackStarted = true;
        JsonObject metadata = new JsonObject();
        metadata.addProperty("capturedAt", Instant.now().toString());
        metadata.addProperty("dimension", dimension(client));
        metadata.addProperty("x", client.player.getX());
        metadata.addProperty("y", client.player.getY());
        metadata.addProperty("z", client.player.getZ());
        metadata.addProperty("eyeY", client.gameRenderer.mainCamera().position().y);
        metadata.addProperty("yaw", client.gameRenderer.mainCamera().yRot());
        metadata.addProperty("pitch", client.gameRenderer.mainCamera().xRot());
        metadata.addProperty("fov", job.request.fov());
        metadata.addProperty("readiness", "local_chunks_and_render_queue_stable");
        metadata.addProperty("serverRevisionVerified", false);
        metadata.addProperty("loadedChunkRadius", 1);
        metadata.addProperty("stabilizationTicks", job.stableTicks);
        metadata.addProperty("stabilizationFrames", job.readyFrames);
        if (job.request.afterOperationId() != null) metadata.addProperty("afterOperationId", job.request.afterOperationId());
        try {
            Screenshot.takeScreenshot(target, image -> {
                if (job.done || encoder.isShutdown()) { image.close(); return; }
                try { encoder.execute(() -> encode(job, image, metadata)); }
                catch (RuntimeException error) { image.close(); job.fail("encoding_unavailable", "Image encoder unavailable"); }
            });
        } catch (Exception exception) {
            job.fail("readback_failed", "Could not read observer framebuffer");
        }
    }

    private static void encode(Job job, NativeImage image, JsonObject metadata) {
        try (image; ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
            if (job.done) return;
            int sourceWidth = image.getWidth(), sourceHeight = image.getHeight();
            double scale = Math.min(1, Math.min((double) job.request.width() / sourceWidth,
                    (double) job.request.height() / sourceHeight));
            int width = Math.max(1, (int) Math.round(sourceWidth * scale));
            int height = Math.max(1, (int) Math.round(sourceHeight * scale));
            BufferedImage source = new BufferedImage(sourceWidth, sourceHeight, BufferedImage.TYPE_INT_ARGB);
            source.setRGB(0, 0, sourceWidth, sourceHeight, image.getPixels(), 0, sourceWidth);
            BufferedImage output = new BufferedImage(width, height, BufferedImage.TYPE_INT_RGB);
            Graphics2D graphics = output.createGraphics();
            try {
                graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                graphics.drawImage(source, 0, 0, width, height, null);
            } finally { graphics.dispose(); source.flush(); }
            if (!ImageIO.write(output, "png", bytes)) throw new IllegalStateException("PNG writer unavailable");
            output.flush();
            if (bytes.size() > 8 * 1024 * 1024) { job.fail("image_too_large", "PNG exceeds 8 MiB limit"); return; }
            JsonObject result = metadata.deepCopy();
            result.addProperty("status", "completed");
            result.addProperty("mimeType", "image/png");
            result.addProperty("width", width);
            result.addProperty("height", height);
            result.addProperty("sourceWidth", sourceWidth);
            result.addProperty("sourceHeight", sourceHeight);
            result.addProperty("imageBase64", Base64.getEncoder().encodeToString(bytes.toByteArray()));
            job.finish(result);
        } catch (Exception exception) { job.fail("encoding_failed", "Could not encode observer screenshot"); }
    }

    private static String dimension(Minecraft client) { return client.level.dimension().identifier().toString(); }

    private static boolean matchesPosition(Minecraft client, CaptureRequest request) {
        return client.player != null && client.level != null
                && (request.dimension() == null || request.dimension().equals(dimension(client)))
                && Math.abs(client.player.getX() - request.x()) <= 0.05
                && Math.abs(client.player.getY() - request.y()) <= 0.05
                && Math.abs(client.player.getZ() - request.z()) <= 0.05;
    }

    private static boolean matchesView(Minecraft client, CaptureRequest request) {
        return client.gui.hud.isHidden() && client.options.getCameraType() == CameraType.FIRST_PERSON
                && client.options.fov().get() == request.fov()
                && Math.abs(Math.IEEEremainder(client.player.getYRot() - request.yaw(), 360)) <= 0.1
                && Math.abs(client.player.getXRot() - request.pitch()) <= 0.1;
    }

    private static boolean chunksLoaded(Minecraft client) {
        int cx = Math.floorDiv(client.player.blockPosition().getX(), 16);
        int cz = Math.floorDiv(client.player.blockPosition().getZ(), 16);
        for (int dx = -1; dx <= 1; dx++) for (int dz = -1; dz <= 1; dz++)
            if (client.level.getChunkSource().getChunk(cx + dx, cz + dz, ChunkStatus.FULL, false) == null) return false;
        return true;
    }

    private static void restore(Minecraft client, Job job) {
        SavedView saved = job.saved;
        if (saved == null) return;
        if (client.gui.hud.isHidden() != saved.hudHidden) client.gui.hud.toggle();
        client.options.fov().set(saved.fov);
        client.options.bobView().set(saved.bobView);
        client.options.fovEffectScale().set(saved.fovEffectScale);
        client.options.setCameraType(saved.cameraType);
        if (client.player == job.player) {
            client.player.setYRot(saved.yaw);
            client.player.setXRot(saved.pitch);
            client.player.setOldRot();
        }
        job.saved = null;
    }

    private void stop(Minecraft client) {
        instance = null;
        Job job = active.getAndSet(null);
        if (job != null) { job.fail("client_stopping", "Camera client is stopping"); restore(client, job); }
        if (http != null) http.close();
        watchdog.shutdownNow();
        encoder.shutdown();
    }

    private record SavedView(boolean hudHidden, int fov, boolean bobView, double fovEffectScale,
                             CameraType cameraType, float yaw, float pitch) {}

    private static final class Job {
        final String id = UUID.randomUUID().toString();
        final CaptureRequest request;
        final long createdNanos = System.nanoTime();
        volatile JsonObject result;
        volatile boolean done;
        boolean initialized, readbackStarted;
        int stableTicks, readyFrames;
        SavedView saved;
        LocalPlayer player;
        ClientLevel level;
        Job(CaptureRequest request) {
            this.request = request;
            result = new JsonObject();
            result.addProperty("status", "pending");
            result.addProperty("captureId", id);
        }
        synchronized void finish(JsonObject value) {
            if (done) return;
            value.addProperty("captureId", id);
            result = value;
            done = true;
        }
        void fail(String code, String message) { finish(CameraHttpServer.error(code, message)); }
    }
}
