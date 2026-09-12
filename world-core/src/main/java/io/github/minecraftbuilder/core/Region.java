package io.github.minecraftbuilder.core;

import java.util.Objects;

public record Region(String worldId, BlockPos min, BlockPos max) {
    public Region {
        Objects.requireNonNull(worldId); Objects.requireNonNull(min); Objects.requireNonNull(max);
        if (worldId.isBlank() || min.x() > max.x() || min.y() > max.y() || min.z() > max.z())
            throw new IllegalArgumentException("Invalid inclusive region bounds");
    }
    public boolean contains(BlockPos pos) {
        return pos.x() >= min.x() && pos.x() <= max.x() && pos.y() >= min.y() && pos.y() <= max.y()
            && pos.z() >= min.z() && pos.z() <= max.z();
    }
    public long volume() {
        return Math.multiplyExact(Math.multiplyExact((long) max.x() - min.x() + 1,
            (long) max.y() - min.y() + 1), (long) max.z() - min.z() + 1);
    }
}
