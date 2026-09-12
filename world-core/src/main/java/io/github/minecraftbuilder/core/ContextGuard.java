package io.github.minecraftbuilder.core;

/** Throw to stop on revoked permission, changed world epoch, unloaded chunks, or changed region. */
@FunctionalInterface
public interface ContextGuard {
    void check(Plan plan);

    /**
     * Validate context for administrative inspection/abandonment, which never writes world blocks.
     * Adapters may omit write-only restrictions (paused writes, protected parts), while retaining
     * project/world/epoch identity, region bounds, and caller authorization. The conservative default
     * preserves the complete write guard for existing adapters until they explicitly separate it.
     */
    default void checkRecovery(Plan plan) { check(plan); }
}
