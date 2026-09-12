package io.github.minecraftbuilder.core;

import java.util.List;
import java.util.Objects;

/** An immutable snapshot. No-change entries remain read dependencies in the plan. */
public record Plan(String id, String projectId, String worldEpoch, Region region, List<Change> changes,
                   List<Dependency> dependencies, long createdAtMillis, long expiresAtMillis, String undoOf) {
    public Plan {
        Objects.requireNonNull(id); Objects.requireNonNull(projectId); Objects.requireNonNull(worldEpoch);
        Objects.requireNonNull(region); changes = List.copyOf(changes); dependencies = List.copyOf(dependencies);
    }
    public record Dependency(BlockPos pos, String expected) {
        public Dependency { Objects.requireNonNull(pos); Objects.requireNonNull(expected); }
    }
}
