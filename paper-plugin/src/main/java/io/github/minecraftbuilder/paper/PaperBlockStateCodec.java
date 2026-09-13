package io.github.minecraftbuilder.paper;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import org.bukkit.block.BlockState;
import org.bukkit.block.TileState;
import org.bukkit.block.data.BlockData;
import org.bukkit.block.data.type.StructureBlock;

/**
 * Narrow, version-checked Paper 26.2 adapter for data the public BlockData API does not serialize.
 * Full snapshot NBT preserves inventories, signs, decorations, entity data and plugin PDC. It never
 * accepts NBT from RPC callers. Unavailable internals fail closed before editing instead of silently
 * degrading undo to block data. Reflection keeps the plugin API-only build.
 */
final class PaperBlockStateCodec {
    private final Class<?> tileClass;
    private final Method saveNbt, getBlockEntity, getRegistryAccess, loadData, parseCompound, remove, putString, place;
    private final Method getWorldHandle, getPosition, getLiveBlockEntity, setLiveBlockEntity;
    private final int placeFlags;
    PaperBlockStateCodec() {
        try {
            tileClass = Class.forName("org.bukkit.craftbukkit.block.CraftBlockEntityState");
            Class<?> compound = Class.forName("net.minecraft.nbt.CompoundTag");
            Class<?> parser = Class.forName("net.minecraft.nbt.TagParser");
            Class<?> block = Class.forName("net.minecraft.world.level.block.Block");
            Class<?> craftState = Class.forName("org.bukkit.craftbukkit.block.CraftBlockState");
            Class<?> entity = Class.forName("net.minecraft.world.level.block.entity.BlockEntity");
            Class<?> position = Class.forName("net.minecraft.core.BlockPos");
            Class<?> level = Class.forName("net.minecraft.world.level.Level");
            saveNbt = entity.getMethod("saveWithFullMetadata", Class.forName("net.minecraft.core.HolderLookup$Provider"));
            getBlockEntity = tileClass.getMethod("getBlockEntity");
            getRegistryAccess = tileClass.getMethod("getRegistryAccess");
            loadData = tileClass.getMethod("loadData", compound);
            parseCompound = parser.getMethod("parseCompoundFully", String.class);
            remove = compound.getMethod("remove", String.class);
            putString = compound.getMethod("putString", String.class, String.class);
            place = craftState.getMethod("place", int.class);
            getWorldHandle = craftState.getMethod("getWorldHandle");
            getPosition = craftState.getMethod("getPosition");
            getLiveBlockEntity = level.getMethod("getBlockEntity", position);
            setLiveBlockEntity = level.getMethod("setBlockEntity", entity);
            // setBlockData(false) omits SKIP_BLOCK_ENTITY_SIDEEFFECTS and can spill containers.
            placeFlags = block.getField("UPDATE_CLIENTS").getInt(null)
                | block.getField("UPDATE_SKIP_ALL_SIDEEFFECTS").getInt(null);
            if (placeFlags != 818) throw new ReflectiveOperationException("Unexpected Paper placement flags");
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException("This Paper version does not provide the required lossless block snapshot API", e);
        }
    }
    String capture(BlockState state) {
        String data = state.getBlockData().getAsString();
        if (!(state instanceof TileState)) return data;
        if (!tileClass.isInstance(state)) throw new IllegalStateException("Unknown block-entity snapshot implementation");
        // The captured BlockState is freshly read or an unplaced default; its underlying entity
        // already contains every value. Craft.getSnapshotNBT calls applyTo during a read and some
        // tile kinds (Structure) can mutate the world or dereference an unplaced snapshot's level.
        Object tag = call(saveNbt, call(getBlockEntity, state), call(getRegistryAccess, state));
        // Coordinates live in Change; all entity data stays. Unplaced defaults compare with placed data.
        call(remove, tag, "x"); call(remove, tag, "y"); call(remove, tag, "z");
        // StringTagVisitor sorts compound keys recursively in pinned Paper 26.2.
        return BlockSnapshots.encode(data, tag.toString());
    }
    void restoreData(BlockState state, String nbt) {
        if (!(state instanceof TileState) || !tileClass.isInstance(state))
            throw new IllegalArgumentException("Stored block entity does not match its block type");
        call(loadData, state, call(parseCompound, null, nbt));
    }
    String prepareData(String nbt, BlockData before, BlockData after) {
        // Structure mode exists in both block data and entity NBT. Loading old NBT otherwise
        // rewrites the new mode back to its previous value. Preserve every unrelated field.
        if (before instanceof StructureBlock oldStructure && after instanceof StructureBlock newStructure
                && oldStructure.getMode() != newStructure.getMode()) {
            Object tag = call(parseCompound, null, nbt);
            call(putString, tag, "mode", newStructure.getMode().name());
            return tag.toString();
        }
        return nbt;
    }
    void place(BlockState state) {
        if (!state.isPlaced()) throw new IllegalArgumentException("Snapshot restore requires a world location");
        // A same-state call may return false although the TileState override copies changed NBT.
        // EditEngine verifies the complete captured value immediately after every write.
        call(place, state, placeFlags);
        if (state instanceof TileState) {
            Object level = call(getWorldHandle, state);
            Object position = call(getPosition, state);
            if (call(getLiveBlockEntity, level, position) == null) {
                // MOVING_PISTON permits a block without an automatically created entity. The
                // copied state owns a detached entity at the target position with restored NBT.
                call(setLiveBlockEntity, level, call(getBlockEntity, state));
                call(place, state, placeFlags); // Apply/mark changed and send the entity update.
            }
        }
    }
    private static Object call(Method method, Object receiver, Object... args) {
        try { return method.invoke(receiver, args); }
        catch (IllegalAccessException | InvocationTargetException e) {
            // Never echo arbitrary sign, book, command or inventory contents from parser exceptions.
            throw new IllegalStateException("Paper block snapshot operation failed: " + method.getName());
        }
    }
}
