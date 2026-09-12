package io.github.minecraftbuilder.paper;

import org.junit.jupiter.api.Test;
import java.net.*;
import java.net.http.*;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class RpcServerTest {
    private static final String ADMIN = "a".repeat(48), AGENT = "b".repeat(48);
    @Test void capabilitiesAreSeparatedAndIngressIsBounded() throws Exception {
        try (RpcServer server = new RpcServer(0,ADMIN,AGENT,(m,p,a)->Map.of("method",m))) {
            HttpClient client=HttpClient.newHttpClient();
            URI endpoint=URI.create("http://127.0.0.1:"+server.port()+"/v1/rpc");
            assertEquals(403,send(client,endpoint,"bad","{\"method\":\"project_context\"}").statusCode());
            assertEquals(403,send(client,endpoint,AGENT,"{\"method\":\"chat_poll\"}").statusCode());
            assertEquals(200,send(client,endpoint,AGENT,"{\"method\":\"project_context\"}").statusCode());
            assertEquals(200,send(client,endpoint,ADMIN,"{\"method\":\"chat_poll\"}").statusCode());
            assertTrue(send(client,endpoint,ADMIN,"x".repeat(1_048_577)).body().contains("budget_exceeded"));
            assertEquals(400,send(client,endpoint,ADMIN,"not-json").statusCode());
        }
    }
    private HttpResponse<String> send(HttpClient client,URI uri,String token,String body) throws Exception {
        return client.send(HttpRequest.newBuilder(uri).header("Authorization","Bearer "+token).POST(HttpRequest.BodyPublishers.ofString(body)).build(),HttpResponse.BodyHandlers.ofString());
    }
}
