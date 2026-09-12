package io.github.minecraftbuilder.core;

import java.util.Objects;

public record Change(BlockPos pos, String expected, String desired) {
    public Change { Objects.requireNonNull(pos); Objects.requireNonNull(expected); Objects.requireNonNull(desired); }
}
