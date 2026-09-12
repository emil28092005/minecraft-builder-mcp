package io.github.minecraftbuilder.paper;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ComponentTokensTest {
    private static final String ADMIN = "a".repeat(32), AGENT = "b".repeat(32), CAMERA = "c".repeat(32);

    @Test void acceptsDistinctBoundedSafeBearerTokens() {
        assertDoesNotThrow(() -> ComponentTokens.validate(ADMIN, AGENT, CAMERA));
        assertDoesNotThrow(() -> ComponentTokens.validate("a".repeat(512), "b".repeat(512), "c".repeat(506) + ".-_~09"));
    }

    @Test void rejectsHeaderInjectionWhitespaceUnicodeLengthAndNullWithoutEchoingSecret() {
        for (String invalid : new String[]{null, "", "short", "x".repeat(513), "dummy-private-token-that-must-not-leak\n",
                "dummy-private-token-that-must-not-leak\r\nInjected: yes", "x".repeat(31) + " ", "x".repeat(31) + "ж"}) {
            IllegalArgumentException error = assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate(ADMIN, AGENT, invalid));
            assertEquals("Invalid component tokens: configure three distinct values of 32..512 safe ASCII characters", error.getMessage());
            assertFalse(error.getMessage().contains("dummy-private"));
            assertFalse(error.getMessage().contains(ADMIN));
            assertFalse(error.getMessage().contains(AGENT));
        }
        assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate("x\n".repeat(32), AGENT, CAMERA));
        assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate(ADMIN, "x\n".repeat(32), CAMERA));
    }

    @Test void rejectsSharedCapabilitiesForEveryPair() {
        assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate(ADMIN, ADMIN, CAMERA));
        assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate(ADMIN, AGENT, ADMIN));
        assertThrows(IllegalArgumentException.class, () -> ComponentTokens.validate(ADMIN, AGENT, AGENT));
    }
}
