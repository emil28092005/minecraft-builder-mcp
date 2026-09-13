package io.github.minecraftbuilder.paper;

import com.google.gson.*;
import io.github.minecraftbuilder.core.BlockPos;
import java.util.*;
import java.util.function.Function;

/** Optional caller snapshot, checked in the same server task that creates the plan. */
final class ExpectedBlocks {
    private ExpectedBlocks() { }

    static void check(JsonArray entries, Set<BlockPos> desired, Function<String,String> canonical,
                      Function<BlockPos,String> read) {
        check(entries, desired, canonical, read, ignored -> null);
    }

    static void check(JsonArray entries, Set<BlockPos> desired, Function<String,String> canonical,
                      Function<BlockPos,String> read, Function<BlockPos,String> snapshotId) {
        if (entries.size() != desired.size() || entries.size() > 4096)
            throw new RpcServer.Fault("invalid_request", "expected_blocks must cover every desired position exactly once");
        Map<BlockPos,String> expected = new LinkedHashMap<>();
        Map<BlockPos,String> snapshots = new HashMap<>();
        for (JsonElement entry : entries) {
            JsonObject value = entry.getAsJsonObject();
            JsonObject p = value.getAsJsonObject("pos");
            BlockPos at = new BlockPos(integer(p,"x"), integer(p,"y"), integer(p,"z"));
            if (!desired.contains(at) || expected.containsKey(at))
                throw new RpcServer.Fault("invalid_request", "Unexpected or duplicate expected_blocks position");
            expected.put(at, canonical.apply(value.get("state").getAsString()));
            if (value.has("snapshot_id")) {
                JsonElement id=value.get("snapshot_id");
                if(!id.isJsonPrimitive() || !id.getAsJsonPrimitive().isString() || !id.getAsString().matches("[a-f0-9]{64}"))
                    throw new RpcServer.Fault("invalid_request", "snapshot_id must be a SHA-256 digest");
                snapshots.put(at,id.getAsString());
            }
        }
        for (var entry : expected.entrySet()) {
            if (!entry.getValue().equals(read.apply(entry.getKey())))
                throw new RpcServer.Fault("stale_snapshot", "Caller snapshot changed at " + entry.getKey());
            String currentId=snapshotId.apply(entry.getKey()), expectedId=snapshots.get(entry.getKey());
            if(currentId!=null && expectedId==null)
                throw new RpcServer.Fault("invalid_request", "expected_blocks needs snapshot_id for block-entity data at " + entry.getKey() + "; inspect this block again");
            if(expectedId!=null && !expectedId.equals(currentId))
                throw new RpcServer.Fault("stale_snapshot", "Caller block-entity snapshot changed at " + entry.getKey());
        }
    }

    private static int integer(JsonObject value, String name) {
        try { return value.get(name).getAsBigDecimal().intValueExact(); }
        catch (ArithmeticException | NumberFormatException ex) {
            throw new RpcServer.Fault("invalid_request", "Expected position coordinates must be integers");
        }
    }
}
