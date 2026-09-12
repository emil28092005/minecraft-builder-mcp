package io.github.minecraftbuilder.core;

public record Limits(int maxChanges, int maxReadDependencies, int maxBlocksPerSlice, long sliceNanos,
                     long planTtlMillis, int maxConflictDetails) {
    public Limits {
        if (maxChanges < 1 || maxReadDependencies < 0 || maxBlocksPerSlice < 1 || sliceNanos < 1
            || planTtlMillis < 1 || maxConflictDetails < 1) throw new IllegalArgumentException("Invalid limits");
    }
    public static Limits defaults() { return new Limits(100_000, 512, 512, 5_000_000, 600_000, 32); }
}
