package io.github.minecraftbuilder.core;

import java.util.List;

/** Pass this exact staged object through persistIntent then commitSlice; it is not accepted from clients. */
public record SliceIntent(String operationId, int sequence, List<Change> changes) {
    public SliceIntent { changes = List.copyOf(changes); }
}
