package io.github.minecraftbuilder.core;

import java.util.List;

public record OperationView(String id, String planId, String projectId, OperationStatus status,
                            int totalChanges, int processed, int written, int skipped,
                            int preflightChecked, List<Conflict> conflicts, String message,
                            boolean needsFlush, boolean cancellationRequested) { }
