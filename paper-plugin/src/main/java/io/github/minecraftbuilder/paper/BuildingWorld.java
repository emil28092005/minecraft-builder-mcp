package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.*;
import org.bukkit.*;
import org.bukkit.block.BlockState;
import org.bukkit.block.data.BlockData;
import java.util.*;

/** Live registry block data with private, lossless block-entity snapshots for guarded edits and undo. */
final class BuildingWorld implements WorldAccess, BlockPolicy {
    private final World world;
    private final PaperBlockStateCodec snapshots = new PaperBlockStateCodec();
    private final Map<String, BlockData> parsed = new LinkedHashMap<>(128, 0.75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, BlockData> entry) { return size() > 4096; }
    };

    BuildingWorld(World world) { this.world = world; }
    static List<String> supportedMaterials() { return Registry.BLOCK.stream().map(type -> type.getKey().toString()).sorted().toList(); }
    BlockData data(String state) { return parsed.computeIfAbsent(state, Bukkit::createBlockData).clone(); }
    String canonical(String state) {
        // Opaque journal payloads are internal: model-supplied data is always parsed as BlockData.
        try { return data(state).getAsString(); }
        catch (IllegalArgumentException e) { throw new RpcServer.Fault("unsupported_block", "Invalid registered block or block properties"); }
    }
    public boolean supports(String state) {
        try { return supportsData(data(BlockSnapshots.state(state))); }
        catch (IllegalArgumentException | NullPointerException e) { return false; }
    }
    static boolean supportsData(BlockData data) {
        // A parsed BlockData already represents a registered block, unlike item-only Materials.
        return data != null && data.getMaterial() != null && !data.getMaterial().isLegacy();
    }
    static Map<String, String> publicSnapshot(String value) { return BlockSnapshots.publicView(value); }
    static String snapshotId(String value) { return BlockSnapshots.snapshotId(value); }
    static String canonicalSnapshotState(String value) { return BlockSnapshots.state(value); }

    private void ready(BlockPos p) {
        if (!Bukkit.isPrimaryThread()) throw new IllegalStateException("World access outside server thread");
        if (p.y() < world.getMinHeight() || p.y() >= world.getMaxHeight()) throw new RpcServer.Fault("out_of_bounds", "Position exceeds world height");
        if (!world.isChunkLoaded(p.x() >> 4, p.z() >> 4)) throw new RpcServer.Fault("chunk_not_loaded", "Visit/load the target chunks before editing");
        if (!world.getWorldBorder().isInside(new Location(world,p.x()+0.5,p.y(),p.z()+0.5))) throw new RpcServer.Fault("out_of_bounds", "Position exceeds world border");
    }
    public String getBlock(BlockPos p) { ready(p); return world.getBlockAt(p.x(),p.y(),p.z()).getBlockData().getAsString(); }
    public String captureBlock(BlockPos p) {
        ready(p);
        return snapshots.capture(world.getBlockAt(p.x(),p.y(),p.z()).getState());
    }
    public String prepareBlock(BlockPos p, String desired, String capturedBefore) {
        if (BlockSnapshots.captured(desired)) return desired; // Exact private undo snapshot, never merge it.
        BlockData after = data(desired);
        BlockSnapshots.Value before = BlockSnapshots.decode(capturedBefore);
        if (before.nbt() != null && data(before.state()).getMaterial() == after.getMaterial())
            return BlockSnapshots.encode(after.getAsString(), snapshots.prepareData(before.nbt(), data(before.state()), after));
        return snapshots.capture(after.createBlockState());
    }
    public void setBlock(BlockPos p, String state) {
        setCapturedBlock(p, prepareBlock(p, canonical(state), captureBlock(p)));
    }
    public void setCapturedBlock(BlockPos p, String capturedState) {
        ready(p);
        BlockSnapshots.Value value = BlockSnapshots.decode(capturedState);
        BlockState state = data(value.state()).createBlockState().copy(new Location(world, p.x(), p.y(), p.z()));
        if (value.nbt() != null) snapshots.restoreData(state, value.nbt());
        snapshots.place(state);
    }
}
