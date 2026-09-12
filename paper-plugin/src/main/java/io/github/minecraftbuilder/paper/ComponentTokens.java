package io.github.minecraftbuilder.paper;

/** Validate before a secret reaches HTTP header builders, whose exception messages can echo values. */
final class ComponentTokens {
    private static final String ERROR = "Invalid component tokens: configure three distinct values of 32..512 safe ASCII characters";

    private ComponentTokens() { }

    static void validate(String admin, String agent, String camera) {
        if (!safe(admin) || !safe(agent) || !safe(camera)
                || admin.equals(agent) || admin.equals(camera) || agent.equals(camera))
            throw new IllegalArgumentException(ERROR);
    }

    private static boolean safe(String value) {
        return value != null && value.matches("[A-Za-z0-9._~-]{32,512}");
    }
}
