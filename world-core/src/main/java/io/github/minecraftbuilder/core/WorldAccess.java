package io.github.minecraftbuilder.core;

/** The adapter must call all engine methods that touch this interface on its world thread. */
public interface WorldAccess {
    String getBlock(BlockPos position);
    /** Apply canonical state without physics; unsupported side effects must be excluded by BlockPolicy. */
    void setBlock(BlockPos position, String canonicalState);
}
