package dev.minecraftbuilder.camera;

import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import static org.junit.jupiter.api.Assertions.*;

class CaptureRequestTest {
    private static final String POSE = "\"x\":1,\"y\":64,\"z\":-2,\"yaw\":0,\"pitch\":15";

    @Test void suppliesBoundedDefaultsAndKeepsCorrelation() {
        CaptureRequest request = parse("{" + POSE + ",\"afterOperationId\":\"op-42\",\"dimension\":\"minecraft:overworld\"}");
        assertEquals(1280, request.width());
        assertEquals(720, request.height());
        assertEquals(70, request.fov());
        assertEquals("op-42", request.afterOperationId());
    }

    @ParameterizedTest @ValueSource(strings = {"\"width\":1921", "\"width\":320.5", "\"height\":0",
            "\"fov\":111", "\"width\":\"640\"", "\"afterOperationId\":null", "\"shell\":\"noop\""})
    void rejectsUnsafeOrAmbiguousParameters(String extra) {
        assertThrows(IllegalArgumentException.class, () -> parse("{" + POSE + "," + extra + "}"));
    }

    @Test void rejectsNonFiniteAndOutOfWorldPose() {
        assertThrows(IllegalArgumentException.class, () -> parse("{" + POSE.replace("\"x\":1", "\"x\":1e999") + "}"));
        assertThrows(IllegalArgumentException.class, () -> parse("{" + POSE.replace("\"pitch\":15", "\"pitch\":91") + "}"));
        assertThrows(IllegalArgumentException.class, () -> parse("{" + POSE.replace("\"y\":64", "\"y\":4096") + "}"));
    }

    private static CaptureRequest parse(String input) { return CaptureRequest.parse(JsonParser.parseString(input).getAsJsonObject()); }
}
