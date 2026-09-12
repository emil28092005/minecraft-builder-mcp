package io.github.minecraftbuilder.paper;

import com.google.gson.*;
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.concurrent.*;

/** Loopback transport; separate agent/admin capabilities, bounded ingress and queues. */
public final class RpcServer implements AutoCloseable {
    public interface Handler { Object call(String method, JsonObject params, boolean admin) throws Exception; }
    public static final class Fault extends RuntimeException {
        public final String code;
        public Fault(String code, String message) { super(message); this.code = code; }
    }
    private final HttpServer server;
    private final ExecutorService executor;
    private static final Gson JSON = new Gson();
    private static final int MAX_BODY = 1_048_576;

    public RpcServer(int port, String adminToken, String agentToken, Handler handler) throws IOException {
        if (adminToken.length() < 32 || agentToken.length() < 32 || adminToken.equals(agentToken))
            throw new IllegalArgumentException("Distinct tokens of at least 32 characters required");
        server = HttpServer.create(new InetSocketAddress(InetAddress.getLoopbackAddress(), port), 16);
        executor = new ThreadPoolExecutor(2, 4, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(32),
            r -> { Thread t = new Thread(r, "mcb-rpc"); t.setDaemon(true); return t; }, new ThreadPoolExecutor.AbortPolicy());
        server.setExecutor(executor);
        server.createContext("/health", exchange -> {
            if (!exchange.getRequestMethod().equals("GET") || !exchange.getRequestURI().getPath().equals("/health")) {
                respond(exchange, 404, Map.of("error", "not_found")); return;
            }
            respond(exchange, 200, Map.of("service", "minecraft-builder-mcp", "version", "0.1.0", "status", "ready"));
        });
        server.createContext("/v1/rpc", exchange -> {
            try {
                if (!exchange.getRequestURI().getPath().equals("/v1/rpc") || !exchange.getRequestMethod().equals("POST")) {
                    respond(exchange, 405, Map.of("ok",false,"error", Map.of("code","method_not_allowed","message","POST /v1/rpc required"))); return;
                }
                if (exchange.getRequestHeaders().containsKey("Origin")) throw new Fault("permission_denied", "Browser origins are not permitted");
                String authorization = exchange.getRequestHeaders().getFirst("Authorization");
                boolean admin = equal(authorization, "Bearer " + adminToken);
                if (!admin && !equal(authorization, "Bearer " + agentToken)) throw new Fault("permission_denied", "Invalid capability token");
                byte[] bytes = exchange.getRequestBody().readNBytes(MAX_BODY + 1);
                if (bytes.length > MAX_BODY) throw new Fault("budget_exceeded", "Request exceeds 1 MiB");
                JsonObject request = JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8)).getAsJsonObject();
                String method = request.get("method").getAsString();
                if (method.startsWith("chat_") && !admin) throw new Fault("permission_denied", "Chat routing requires the administrator capability");
                JsonObject params = request.has("params") ? request.getAsJsonObject("params") : new JsonObject();
                Object result = handler.call(method, params, admin);
                respond(exchange, 200, Map.of("ok", true, "result", result));
            } catch (Exception failure) {
                Throwable e = failure;
                while ((e instanceof ExecutionException || e instanceof CompletionException) && e.getCause() != null) e = e.getCause();
                String code = e instanceof Fault f ? f.code : e instanceof TimeoutException ? "timeout" : "invalid_request";
                String message = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
                respond(exchange, code.equals("permission_denied") ? 403 : 400,
                    Map.of("ok", false, "error", Map.of("code", code, "message", message.substring(0, Math.min(600, message.length())))));
            }
        });
        server.start();
    }
    static boolean equal(String actual, String expected) {
        return actual != null && MessageDigest.isEqual(actual.getBytes(StandardCharsets.UTF_8), expected.getBytes(StandardCharsets.UTF_8));
    }
    private static void respond(HttpExchange e, int status, Object value) throws IOException {
        byte[] bytes = JSON.toJson(value).getBytes(StandardCharsets.UTF_8);
        e.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        e.getResponseHeaders().set("Cache-Control", "no-store");
        e.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = e.getResponseBody()) { out.write(bytes); }
        finally { e.close(); }
    }
    public int port() { return server.getAddress().getPort(); }
    public void close() { server.stop(0); executor.shutdownNow(); }
}
