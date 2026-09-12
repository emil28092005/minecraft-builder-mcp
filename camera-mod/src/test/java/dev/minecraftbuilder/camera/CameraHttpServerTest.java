package dev.minecraftbuilder.camera;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class CameraHttpServerTest {
    private static final String TOKEN = "test-camera-token-with-at-least-32-characters";
    private static final String VALID = "{\"x\":1,\"y\":64,\"z\":-2,\"yaw\":0,\"pitch\":15}";

    @Test void authenticatesBeforeQueueingAndEnforcesRequestBudget() throws Exception {
        AtomicInteger queued = new AtomicInteger();
        CameraHttpServer.Backend backend = new CameraHttpServer.Backend() {
            public JsonObject health() { return JsonParser.parseString("{\"status\":\"ok\"}").getAsJsonObject(); }
            public JsonObject submit(CaptureRequest request) {
                queued.incrementAndGet();
                return JsonParser.parseString("{\"status\":\"pending\",\"captureId\":\"00000000-0000-0000-0000-000000000000\"}").getAsJsonObject();
            }
            public JsonObject poll(String id) { return null; }
        };
        try (CameraHttpServer server = new CameraHttpServer(0, TOKEN, backend); HttpClient client = HttpClient.newHttpClient()) {
            server.start();
            String base = "http://127.0.0.1:" + server.port();
            assertEquals(401, send(client, base + "/v1/capture", "POST", VALID, "wrong").statusCode());
            assertEquals(0, queued.get());
            assertEquals(202, send(client, base + "/v1/capture", "POST", VALID, TOKEN).statusCode());
            assertEquals(1, queued.get());
            assertEquals(413, send(client, base + "/v1/capture", "POST", " ".repeat(8193), TOKEN).statusCode());
            assertEquals(400, send(client, base + "/v1/capture", "POST", "{\"x\":true}", TOKEN).statusCode());
            assertEquals(1, queued.get());
            assertEquals(404, send(client, base + "/v1/captures/00000000-0000-0000-0000-000000000000", "GET", "", TOKEN).statusCode());
            assertEquals("no-store", send(client, base + "/health", "GET", "", TOKEN).headers().firstValue("Cache-Control").orElseThrow());
        }
    }

    @Test void rejectsTokenlessOrWeakService() {
        assertThrows(IllegalArgumentException.class, () -> new CameraHttpServer(0, null, null));
        assertThrows(IllegalArgumentException.class, () -> new CameraHttpServer(0, "weak", null));
    }

    private static HttpResponse<String> send(HttpClient client, String url, String method, String body, String token) throws Exception {
        return client.send(HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(5))
                .header("Authorization", "Bearer " + token).method(method, HttpRequest.BodyPublishers.ofString(body)).build(),
                HttpResponse.BodyHandlers.ofString());
    }
}
