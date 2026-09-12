package dev.minecraftbuilder.camera;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** No Minecraft APIs are called by HTTP threads. Backend only queues work and reads cached results. */
public final class CameraHttpServer implements AutoCloseable {
    public interface Backend {
        JsonObject health();
        JsonObject submit(CaptureRequest request);
        JsonObject poll(String captureId);
    }
    private final HttpServer server;
    private final ExecutorService executor = Executors.newFixedThreadPool(2, Thread.ofPlatform()
            .daemon(true).name("mcb-camera-http-", 0).factory());
    private final byte[] authorization;
    private final Backend backend;

    public CameraHttpServer(int port, String token, Backend backend) throws IOException {
        if (token == null || token.length() < 32 || token.length() > 512 || token.chars().anyMatch(Character::isWhitespace))
            throw new IllegalArgumentException("MCB_CAMERA_TOKEN must contain 32..512 non-whitespace characters");
        this.authorization = ("Bearer " + token).getBytes(StandardCharsets.UTF_8);
        this.backend = backend;
        server = HttpServer.create(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 8);
        server.setExecutor(executor);
        server.createContext("/", this::handle);
    }

    public void start() { server.start(); }
    public int port() { return server.getAddress().getPort(); }

    private void handle(HttpExchange exchange) throws IOException {
        try (exchange) {
            String bearer = exchange.getRequestHeaders().getFirst("Authorization");
            if (bearer == null || !MessageDigest.isEqual(authorization, bearer.getBytes(StandardCharsets.UTF_8))) {
                send(exchange, 401, error("unauthorized", "Valid camera bearer token required"));
                return;
            }
            String path = exchange.getRequestURI().getPath();
            String method = exchange.getRequestMethod();
            if (path.equals("/health") && method.equals("GET")) {
                send(exchange, 200, backend.health());
            } else if (path.equals("/v1/capture") && method.equals("POST")) {
                byte[] body = exchange.getRequestBody().readNBytes(8193);
                if (body.length > 8192) {
                    send(exchange, 413, error("request_too_large", "Capture request exceeds 8192 bytes"));
                    return;
                }
                try {
                    JsonObject result = backend.submit(CaptureRequest.parse(JsonParser.parseString(
                            new String(body, StandardCharsets.UTF_8)).getAsJsonObject()));
                    send(exchange, result.has("error") ? 409 : 202, result);
                } catch (RuntimeException exception) {
                    send(exchange, 400, error("invalid_request", "Invalid capture JSON or capture parameters"));
                }
            } else if (path.startsWith("/v1/captures/") && method.equals("GET")) {
                String id = path.substring("/v1/captures/".length());
                if (!id.matches("[0-9a-f-]{36}")) {
                    send(exchange, 400, error("invalid_capture_id", "Expected a capture UUID"));
                    return;
                }
                JsonObject result = backend.poll(id);
                send(exchange, result == null ? 404 : 200,
                        result == null ? error("capture_not_found", "Capture expired or does not exist") : result);
            } else {
                send(exchange, 404, error("not_found", "Unknown camera endpoint or method"));
            }
        }
    }

    public static JsonObject error(String code, String message) {
        JsonObject result = new JsonObject();
        result.addProperty("status", "error");
        result.addProperty("error", code);
        result.addProperty("message", message);
        return result;
    }

    private static void send(HttpExchange exchange, int code, JsonObject result) throws IOException {
        byte[] bytes = result.toString().getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(code, bytes.length);
        exchange.getResponseBody().write(bytes);
    }

    @Override public void close() { server.stop(0); executor.shutdownNow(); }
}
