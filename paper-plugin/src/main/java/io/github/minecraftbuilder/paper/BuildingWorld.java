package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.*;
import org.bukkit.*;
import org.bukkit.block.data.BlockData;
import java.util.*;

/** Small tested policy; unsupported existing contents are protected too. */
final class BuildingWorld implements WorldAccess, BlockPolicy {
    private final World world;
    private final Map<String, BlockData> parsed = new HashMap<>();
    private static final Set<String> MATERIALS = Set.of("air", "stone", "cobblestone", "mossy_cobblestone",
        "stone_bricks", "mossy_stone_bricks", "cracked_stone_bricks", "chiseled_stone_bricks", "smooth_stone",
        "granite", "polished_granite", "diorite", "polished_diorite", "andesite", "polished_andesite",
        "deepslate", "cobbled_deepslate", "polished_deepslate", "deepslate_bricks", "deepslate_tiles",
        "bricks", "quartz_block", "quartz_pillar", "smooth_quartz", "sandstone", "cut_sandstone", "smooth_sandstone",
        "red_sandstone", "terracotta", "white_terracotta", "black_terracotta", "orange_terracotta",
        "white_concrete", "gray_concrete", "black_concrete", "glass", "tinted_glass", "obsidian",
        "dirt", "grass_block", "bedrock", "oak_planks", "spruce_planks", "birch_planks", "dark_oak_planks",
        "oak_log", "spruce_log", "birch_log", "dark_oak_log", "stripped_oak_log", "stripped_spruce_log",
        "stone_brick_stairs", "cobblestone_stairs", "oak_stairs", "spruce_stairs", "deepslate_tile_stairs",
        "stone_brick_slab", "cobblestone_slab", "oak_slab", "spruce_slab", "smooth_stone_slab");
    BuildingWorld(World world) { this.world = world; }
    static List<String> supportedMaterials() { return MATERIALS.stream().sorted().map(s->"minecraft:"+s).toList(); }
    BlockData data(String state) { return parsed.computeIfAbsent(state, Bukkit::createBlockData).clone(); }
    String canonical(String state) { if (!supports(state)) throw new RpcServer.Fault("unsupported_block", "Unsupported block: " + state); return data(state).getAsString(); }
    public boolean supports(String state) {
        try {
            BlockData data = data(state);
            return MATERIALS.contains(data.getMaterial().getKey().getKey())
                && !(data instanceof org.bukkit.block.data.Waterlogged w && w.isWaterlogged());
        } catch (IllegalArgumentException e) { return false; }
    }
    private void ready(BlockPos p) {
        if (!Bukkit.isPrimaryThread()) throw new IllegalStateException("World access outside server thread");
        if (p.y() < world.getMinHeight() || p.y() >= world.getMaxHeight()) throw new RpcServer.Fault("out_of_bounds", "Position exceeds world height");
        if (!world.isChunkLoaded(p.x() >> 4, p.z() >> 4)) throw new RpcServer.Fault("chunk_not_loaded", "Visit/load the target chunks before editing");
        if (!world.getWorldBorder().isInside(new Location(world,p.x()+0.5,p.y(),p.z()+0.5))) throw new RpcServer.Fault("out_of_bounds", "Position exceeds world border");
    }
    public String getBlock(BlockPos p) { ready(p); return world.getBlockAt(p.x(),p.y(),p.z()).getBlockData().getAsString(); }
    public void setBlock(BlockPos p, String state) {
        ready(p);
        // A neighbour may have changed since prepare. Never remove supports next to
        // dynamic/unsupported blocks merely because the target itself still matches.
        for (BlockPos d : List.of(new BlockPos(1,0,0),new BlockPos(-1,0,0),new BlockPos(0,1,0),new BlockPos(0,-1,0),new BlockPos(0,0,1),new BlockPos(0,0,-1))) {
            BlockPos n=p.add(d);
            if(n.y()>=world.getMinHeight()&&n.y()<world.getMaxHeight()&&!supports(getBlock(n)))
                throw new RpcServer.Fault("unsupported_block","Adjacent environment changed at "+n);
        }
        world.getBlockAt(p.x(),p.y(),p.z()).setBlockData(data(state), false);
    }
}
