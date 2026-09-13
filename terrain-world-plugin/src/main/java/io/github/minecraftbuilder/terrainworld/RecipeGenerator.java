package io.github.minecraftbuilder.terrainworld;

import com.google.gson.JsonObject;
import io.github.minecraftbuilder.core.TerrainRecipe;
import org.bukkit.*;
import org.bukkit.block.Biome;
import org.bukkit.generator.*;
import java.util.*;

/** Immutable initial terrain. Never reads or edits an existing chunk. */
public final class RecipeGenerator extends ChunkGenerator {
    final TerrainRecipe recipe;
    private final Material rock, soil, surface;
    private final int depth;
    private final Integer waterLevel;
    private final NaturalTerrain natural;
    private final String profile;

    public RecipeGenerator(JsonObject source) {
        this(source, null);
    }
    public RecipeGenerator(JsonObject source, Integer waterLevel) {
        this(source, waterLevel, "recipe-v1");
    }
    public RecipeGenerator(JsonObject source, Integer waterLevel, String profile) {
        recipe = new TerrainRecipe(source);
        if (!Set.of("recipe-v1", "shacraft-natural-v1").contains(profile))
            throw new IllegalArgumentException("Unknown terrain profile");
        this.profile = profile;
        natural = profile.equals("shacraft-natural-v1") ? new NaturalTerrain(source.get("seed").getAsInt()) : null;
        if (natural != null && !source.getAsJsonArray("features").isEmpty())
            throw new IllegalArgumentException("Natural profile uses its own landforms; recipe features must be empty");
        this.waterLevel = waterLevel;
        if (!recipe.mode().equals("sculpt") || !source.getAsJsonArray("preserve").isEmpty())
            throw new IllegalArgumentException("New worlds require sculpt mode without preserve masks");
        var palette = source.getAsJsonObject("palette");
        rock = Objects.requireNonNull(Material.matchMaterial(palette.get("rock").getAsString()));
        soil = Objects.requireNonNull(Material.matchMaterial(palette.get("soil").getAsString()));
        surface = Objects.requireNonNull(Material.matchMaterial(palette.get("surface").getAsString()));
        depth = palette.get("soil_depth").getAsInt();
    }

    public String identity() {
        String legacy = "recipe-generator-v1:" + recipe.id() + ":water=" + waterLevel;
        return natural == null ? legacy : legacy + ":profile=" + profile + ":materials=slope-v1";
    }
    public int height(int x, int z) { return natural == null ? recipe.surfaceHeight(x, z) : (int)Math.floor(natural.height(x, z)); }
    public int visibleHeight(int x, int z) { return waterLevel == null ? height(x, z) : Math.max(height(x, z), waterLevel); }
    public Material surfaceMaterial(int x, int z) {
        boolean wet = waterLevel != null && height(x,z) < waterLevel;
        if (natural == null) return wet ? rock : surface;
        double variation = natural.rockVariation(x,z);
        boolean cliff = natural.slope(x,z) > 1.05 + .22 * variation;
        if (wet || cliff) return variation > .1 ? Material.ANDESITE : Material.STONE;
        return surface;
    }

    @Override public void generateNoise(WorldInfo info, Random random, int cx, int cz, ChunkData data) {
        for (int x = 0; x < 16; x++) for (int z = 0; z < 16; z++) {
            int top = height(cx * 16 + x, cz * 16 + z);
            if (waterLevel != null && (waterLevel <= data.getMinHeight() || waterLevel >= data.getMaxHeight() - 1))
                throw new IllegalArgumentException("Water level outside world height");
            if (top <= data.getMinHeight() || top >= data.getMaxHeight() - 1)
                throw new IllegalArgumentException("Recipe surface outside world height");
            data.setBlock(x, data.getMinHeight(), z, Material.BEDROCK);
            Material topMaterial = surfaceMaterial(cx*16+x,cz*16+z);
            int soilDepth = natural != null && topMaterial != surface ? 0 : depth;
            int dirtStart = Math.max(data.getMinHeight() + 1, top - soilDepth);
            data.setRegion(x, data.getMinHeight() + 1, z, x + 1, dirtStart, z + 1, rock);
            data.setRegion(x, dirtStart, z, x + 1, top, z + 1, soil);
            data.setBlock(x, top, z, topMaterial);
            if (waterLevel != null && top < waterLevel)
                data.setRegion(x, top + 1, z, x + 1, waterLevel + 1, z + 1, Material.WATER);
        }
    }

    @Override public int getBaseHeight(WorldInfo world, Random random, int x, int z, HeightMap map) {
        return (map == HeightMap.OCEAN_FLOOR || map == HeightMap.OCEAN_FLOOR_WG ? height(x, z) : visibleHeight(x, z)) + 1;
    }
    @Override public Location getFixedSpawnLocation(World world, Random random) {
        return new Location(world, .5, height(0, 0) + 1, .5, 180, 0);
    }
    @Override public BiomeProvider getDefaultBiomeProvider(WorldInfo world) {
        return new BiomeProvider() {
            @Override public Biome getBiome(WorldInfo info, int x, int y, int z) { return Biome.PLAINS; }
            @Override public List<Biome> getBiomes(WorldInfo info) { return List.of(Biome.PLAINS); }
        };
    }
    @Override public boolean shouldGenerateNoise() { return false; }
    @Override public boolean shouldGenerateSurface() { return false; }
    @Override public boolean shouldGenerateCaves() { return false; }
    @Override public boolean shouldGenerateDecorations() { return false; }
    @Override public boolean shouldGenerateMobs() { return false; }
    @Override public boolean shouldGenerateStructures() { return false; }
}
