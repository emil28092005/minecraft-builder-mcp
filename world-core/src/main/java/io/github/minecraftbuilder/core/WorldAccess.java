package io.github.minecraftbuilder.core;

/** The adapter must call all engine methods that touch this interface on its world thread. */
public interface WorldAccess {
    String getBlock(BlockPos position);
    /** Public canonical block data; callers cannot supply private captured payloads through this method. */
    void setBlock(BlockPos position, String canonicalState);

    /** Durable comparison/undo value, including private block-entity data when the adapter supports it. */
    default String captureBlock(BlockPos position) { return getBlock(position); }

    /** Resolve the desired durable value without mutating the world. Captured undo values stay exact. */
    default String prepareBlock(BlockPos position, String desired, String capturedBefore) { return desired; }

    /** Restore a durable captured value. Must suppress immediate drop/removal side effects. */
    default void setCapturedBlock(BlockPos position, String capturedState) { setBlock(position, capturedState); }
}
