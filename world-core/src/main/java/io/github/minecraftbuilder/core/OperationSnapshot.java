package io.github.minecraftbuilder.core;

import java.util.List;

/** Journal wire format; clients should use the bounded OperationView. */
public record OperationSnapshot(String id, String planId, String idempotencyKey, OperationStatus status,
                                int cursor, int skipped, int preflightCursor, int nextSequence,
                                List<Receipt> receipts, SliceIntent pending, List<Conflict> conflicts,
                                String message, boolean cancellationRequested, long abandonedRevision,
                                List<BlockPos> abandonedPositions) {
    public OperationSnapshot {
        receipts = List.copyOf(receipts); conflicts = List.copyOf(conflicts);
        // Older journal version 1 records have no abandonment metadata.
        abandonedPositions = abandonedPositions == null ? List.of() : List.copyOf(abandonedPositions);
    }
}
