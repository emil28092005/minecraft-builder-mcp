package dev.minecraftbuilder.camera;

/** Opt-in loopback connection policy. No game or network dependencies. */
public final class AutoConnectPolicy {
    private final String target;
    private long nextAttempt;
    private int attempts;
    public AutoConnectPolicy(String target, long now) {
        if (!target.matches("127\\.0\\.0\\.1:[0-9]{1,5}")) throw new IllegalArgumentException("Auto-connect requires a literal loopback address and port");
        int port = Integer.parseInt(target.substring(target.indexOf(':')+1));
        if (port < 1024 || port > 65535) throw new IllegalArgumentException("Invalid local server port");
        this.target = target; nextAttempt = now + 10_000;
    }
    public String target() { return target; }
    public int attempts() { return attempts; }
    public boolean due(long now, boolean connected, boolean eligibleScreen, boolean paused) {
        if (connected) { nextAttempt = now + 10_000; return false; }
        if (paused || !eligibleScreen || now < nextAttempt) return false;
        nextAttempt = now + 10_000; attempts++; return true;
    }
}
